import threading
from typing import Any

from pydantic import Field, Json, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Helper Functions (if any, e.g., for parsing complex env vars) ---


class Settings(BaseSettings):
    """
    Configuration settings for the LogLens package.
    Settings are loaded from environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- AILogger Core Settings ---
    logscribe_default_level: str = Field(default="INFO", validation_alias="LOGSCRIBE_DEFAULT_LEVEL")

    # --- AIHandler Batching & Flushing ---
    logscribe_batch_size: int = Field(default=10, gt=0, validation_alias="LOGSCRIBE_BATCH_SIZE")
    logscribe_flush_interval_seconds: float = Field(
        default=5.0, gt=0, validation_alias="LOGSCRIBE_FLUSH_INTERVAL_SECONDS"
    )

    # --- AIHandler Retry & Circuit Breaker ---
    logscribe_max_retries: int = Field(default=3, ge=0, validation_alias="LOGSCRIBE_MAX_RETRIES")
    logscribe_retry_backoff_factor: float = Field(
        default=2.0, ge=0, validation_alias="LOGSCRIBE_RETRY_BACKOFF_FACTOR"
    )
    logscribe_cb_failure_threshold: int = Field(
        default=3, gt=0, validation_alias="LOGSCRIBE_CB_FAILURE_THRESHOLD"
    )
    logscribe_cb_reset_timeout_seconds: float = Field(
        default=60.0, gt=0, validation_alias="LOGSCRIBE_CB_RESET_TIMEOUT_SECONDS"
    )

    # --- LLM Provider & Model Configuration ---
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    logscribe_provider: str = Field(
        default="openai", validation_alias="LOGSCRIBE_PROVIDER"
    )  # openai|anthropic
    logscribe_fast_model: str = Field(
        default="gpt-4o-mini", validation_alias="LOGSCRIBE_FAST_MODEL"
    )
    logscribe_capable_model: str = Field(
        default="gpt-4o", validation_alias="LOGSCRIBE_CAPABLE_MODEL"
    )
    # Threshold for routing to the capable (more expensive) model
    logscribe_capable_severity_threshold: str = Field(
        default="ERROR", validation_alias="LOGSCRIBE_CAPABLE_SEVERITY_THRESHOLD"
    )

    # --- Jinja2 Templating ---
    logscribe_jinja_template_dir: str | None = Field(
        default=None, validation_alias="LOGSCRIBE_JINJA_TEMPLATE_DIR"
    )  # Path to custom templates
    logscribe_jinja_log_prompt_template_name: str = Field(
        default="default_log_prompt.jinja2",
        validation_alias="LOGSCRIBE_JINJA_LOG_PROMPT_TEMPLATE_NAME",
    )

    # --- PII Scrubbing ---
    # Rules can be provided as a JSON string in an environment variable
    # Example: '[{"name": "custom_rule", "regex": "\\d+", "replacement": "[NUM]"}]'
    logscribe_pii_rules_json: Json[list[dict[str, str]]] | None = Field(
        default=None, validation_alias="LOGSCRIBE_PII_RULES_JSON"
    )
    logscribe_pii_use_default_rules: bool = Field(
        default=True, validation_alias="LOGSCRIBE_PII_USE_DEFAULT_RULES"
    )

    # --- AI Response Handling ---
    # 'LOG' (to a separate logger), 'CALLBACK', 'FILE', 'NONE'
    logscribe_ai_response_handler_type: str = Field(
        default="LOG", validation_alias="LOGSCRIBE_AI_RESPONSE_HANDLER_TYPE"
    )
    logscribe_ai_response_log_logger_name: str = Field(
        default="logscribe.ai_responses", validation_alias="LOGSCRIBE_AI_RESPONSE_LOG_LOGGER_NAME"
    )
    logscribe_ai_response_file_path: str | None = Field(
        default=None, validation_alias="LOGSCRIBE_AI_RESPONSE_FILE_PATH"
    )
    # For CALLBACK type, the application would need to register a callback function.

    # --- Prometheus Metrics ---
    logscribe_prometheus_enabled: bool = Field(
        default=True, validation_alias="LOGSCRIBE_PROMETHEUS_ENABLED"
    )
    logscribe_prometheus_port: int = Field(
        default=9095, gt=1023, lt=65536, validation_alias="LOGSCRIBE_PROMETHEUS_PORT"
    )  # Common port for app metrics

    # --- LangChain Specific (if any beyond model names) ---
    # e.g., specific chain configurations, if not handled by LLMRouter internally

    @field_validator(
        "logscribe_default_level", "logscribe_capable_severity_threshold", mode="before"
    )
    @classmethod
    def validate_log_level_names(cls, value: str) -> str:
        """Validates that log level strings are valid."""
        if isinstance(value, str):
            upper_value = value.upper()
            if upper_value not in ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"):
                raise ValueError(f"Invalid log level name: {value}")
            return upper_value
        raise ValueError(f"Log level name must be a string, got {type(value)}")

    @field_validator("logscribe_pii_rules_json", mode="before")
    @classmethod
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
_settings_instance: Settings | None = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    """
    Returns a singleton instance of the Settings.
    Loads settings from environment variables on first call.
    """
    global _settings_instance
    if _settings_instance is None:
        with (
            _settings_lock
        ):  # Basic lock to prevent re-entry if used in threads before instance is set
            if _settings_instance is None:  # Double-check locking pattern
                _settings_instance = Settings()
    return _settings_instance


def reset_settings() -> None:
    """Clear the cached Settings singleton (primarily for tests)."""
    global _settings_instance
    _settings_instance = None
