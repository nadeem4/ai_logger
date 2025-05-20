import os
from typing import List, Optional, Dict, Any, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator, Json

# --- Helper Functions (if any, e.g., for parsing complex env vars) ---

class Settings(BaseSettings):
    """
    Configuration settings for the AI Logging package.
    Settings are loaded from environment variables.
    """
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore', case_sensitive=False)

    # --- AILogger Core Settings ---
    ai_logging_default_level: str = Field(default="INFO", validation_alias="AI_LOGGING_DEFAULT_LEVEL")

    # --- AIHandler Batching & Flushing ---
    ai_logging_batch_size: int = Field(default=10, gt=0, validation_alias="AI_LOGGING_BATCH_SIZE")
    ai_logging_flush_interval_seconds: float = Field(default=5.0, gt=0, validation_alias="AI_LOGGING_FLUSH_INTERVAL_SECONDS")

    # --- AIHandler Retry & Circuit Breaker ---
    ai_logging_max_retries: int = Field(default=3, ge=0, validation_alias="AI_LOGGING_MAX_RETRIES")
    ai_logging_retry_backoff_factor: float = Field(default=2.0, ge=0, validation_alias="AI_LOGGING_RETRY_BACKOFF_FACTOR")
    # TODO: Add circuit breaker specific settings (e.g., fail_threshold, reset_timeout)

    # --- OpenAI API & Model Configuration ---
    openai_api_key: Optional[str] = Field(default=None, validation_alias="OPENAI_API_KEY")
    ai_logging_gpt4_model_name: str = Field(default="gpt-4", validation_alias="AI_LOGGING_GPT4_MODEL_NAME")
    ai_logging_gpt35_model_name: str = Field(default="gpt-3.5-turbo", validation_alias="AI_LOGGING_GPT35_MODEL_NAME")
    # Example: Threshold for routing to more expensive model like GPT-4
    ai_logging_gpt4_severity_threshold: str = Field(default="ERROR", validation_alias="AI_LOGGING_GPT4_SEVERITY_THRESHOLD") # e.g., ERROR, CRITICAL

    # --- Local HuggingFace Model Configuration ---
    ai_logging_enable_local_model: bool = Field(default=False, validation_alias="AI_LOGGING_ENABLE_LOCAL_MODEL")
    ai_logging_local_model_name_or_path: str = Field(default="distilgpt2", validation_alias="AI_LOGGING_LOCAL_MODEL_NAME_OR_PATH")
    # Example: Threshold for routing to local model (e.g., if OpenAI fails or for lower severity)
    ai_logging_local_model_severity_threshold: str = Field(default="DEBUG", validation_alias="AI_LOGGING_LOCAL_MODEL_SEVERITY_THRESHOLD")

    # --- Jinja2 Templating ---
    ai_logging_jinja_template_dir: Optional[str] = Field(default=None, validation_alias="AI_LOGGING_JINJA_TEMPLATE_DIR") # Path to custom templates
    ai_logging_jinja_log_prompt_template_name: str = Field(default="default_log_prompt.jinja2", validation_alias="AI_LOGGING_JINJA_LOG_PROMPT_TEMPLATE_NAME")

    # --- PII Scrubbing ---
    # Rules can be provided as a JSON string in an environment variable
    # Example: '[{"name": "custom_rule", "regex": "\\d+", "replacement": "[NUM]"}]'
    ai_logging_pii_rules_json: Optional[Json[List[Dict[str, str]]]] = Field(default=None, validation_alias="AI_LOGGING_PII_RULES_JSON")
    ai_logging_pii_use_default_rules: bool = Field(default=True, validation_alias="AI_LOGGING_PII_USE_DEFAULT_RULES")

    # --- AI Response Handling ---
    # 'LOG' (to a separate logger), 'CALLBACK', 'FILE', 'NONE'
    ai_logging_ai_response_handler_type: str = Field(default="LOG", validation_alias="AI_LOGGING_AI_RESPONSE_HANDLER_TYPE")
    ai_logging_ai_response_log_logger_name: str = Field(default="ai_logging.ai_responses", validation_alias="AI_LOGGING_AI_RESPONSE_LOG_LOGGER_NAME")
    ai_logging_ai_response_file_path: Optional[str] = Field(default=None, validation_alias="AI_LOGGING_AI_RESPONSE_FILE_PATH")
    # For CALLBACK type, the application would need to register a callback function.

    # --- Prometheus Metrics ---
    ai_logging_prometheus_enabled: bool = Field(default=True, validation_alias="AI_LOGGING_PROMETHEUS_ENABLED")
    ai_logging_prometheus_port: int = Field(default=9095, gt=1023, lt=65536, validation_alias="AI_LOGGING_PROMETHEUS_PORT") # Common port for app metrics

    # --- LangChain Specific (if any beyond model names) ---
    # e.g., specific chain configurations, if not handled by LLMRouter internally

    @validator("ai_logging_default_level", "ai_logging_gpt4_severity_threshold", "ai_logging_local_model_severity_threshold", pre=True, allow_reuse=True)
    def validate_log_level_names(cls, value: str) -> str:
        """Validates that log level strings are valid."""
        if isinstance(value, str):
            upper_value = value.upper()
            if upper_value not in ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"):
                raise ValueError(f"Invalid log level name: {value}")
            return upper_value
        raise ValueError(f"Log level name must be a string, got {type(value)}")

    @validator("ai_logging_pii_rules_json", pre=True, allow_reuse=True)
    def parse_pii_rules_json_string(cls, value: Any) -> Any:
        """Allows PII rules to be passed as a JSON string that Pydantic can then parse."""
        if isinstance(value, str):
            # Pydantic's Json type will handle the actual parsing and validation
            return value
        # If it's already parsed (e.g. from a .env file that pydantic handles differently), pass through
        if value is None or isinstance(value, list):
            return value
        raise ValueError("PII rules must be a JSON string or a list of dicts.")

# --- Singleton Instance ---
# This makes it easy to access settings from anywhere in the package.
_settings_instance: Optional[Settings] = None
_settings_lock = object() # Using a simple object for lock, could use threading.Lock if needed for complex init

def get_settings() -> Settings:
    """
    Returns a singleton instance of the Settings.
    Loads settings from environment variables on first call.
    """
    global _settings_instance
    if _settings_instance is None:
        # In a multithreaded context, a lock might be needed here for thread-safe singleton creation,
        # though Python module imports are generally thread-safe. Pydantic's BaseSettings instantiation
        # itself should be safe.
        with _settings_lock: # Basic lock to prevent re-entry if used in threads before instance is set
            if _settings_instance is None: # Double-check locking pattern
                 _settings_instance = Settings()
    return _settings_instance

if __name__ == "__main__":
    # Example of how to use and test the settings
    # Create a .env file in the same directory as this script for testing, e.g.:
    # AI_LOGGING_DEFAULT_LEVEL=DEBUG
    # OPENAI_API_KEY="your_actual_openai_key_if_testing_real_calls"
    # AI_LOGGING_BATCH_SIZE=5
    # AI_LOGGING_PII_RULES_JSON='[{"name": "test_rule", "regex": "secret-data-\\d+", "replacement": "[SECRET]"}]'

    print("Loading settings...")
    try:
        settings = get_settings()
        print("\n--- Loaded Settings ---")
        print(f"Default Log Level: {settings.ai_logging_default_level}")
        print(f"OpenAI API Key: {'********' if settings.openai_api_key else 'Not set'}")
        print(f"Batch Size: {settings.ai_logging_batch_size}")
        print(f"GPT-4 Model: {settings.ai_logging_gpt4_model_name}")
        print(f"Enable Local Model: {settings.ai_logging_enable_local_model}")
        print(f"Prometheus Enabled: {settings.ai_logging_prometheus_enabled}")
        print(f"Prometheus Port: {settings.ai_logging_prometheus_port}")

        if settings.ai_logging_pii_rules_json:
            print("Custom PII Rules (from JSON string):")
            for rule in settings.ai_logging_pii_rules_json:
                print(f"  - Name: {rule.get('name')}, Regex: {rule.get('regex')}, Replacement: {rule.get('replacement')}")
        else:
            print("Custom PII Rules: Not set (will use defaults if enabled)")
        
        print(f"Use Default PII Rules: {settings.ai_logging_pii_use_default_rules}")

        # Test accessing a setting that might not be in .env to see default
        print(f"Flush Interval (default or .env): {settings.ai_logging_flush_interval_seconds}s")

        # Example of a setting that might fail validation if .env is misconfigured
        # (e.g., AI_LOGGING_BATCH_SIZE=-1) - Pydantic would raise an error.

    except Exception as e:
        print(f"Error loading or validating settings: {e}")

    print("\n--- Settings Demo Complete ---")
    print("To test with environment variables, create a '.env' file or set them in your shell.")
    print("Example .env content:")
    print("AI_LOGGING_DEFAULT_LEVEL=DEBUG")
    print("AI_LOGGING_BATCH_SIZE=7")
    print('AI_LOGGING_PII_RULES_JSON=\'[{"name": "custom_rule", "regex": "example-regex", "replacement": "[CUSTOM]"}]\'')
