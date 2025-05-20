# AI Logging Package (`ai_logging`)

**`ai_logging` is a Python logging toolkit designed to enhance standard logging with AI-powered analysis, insights, and intelligent routing.**

It seamlessly integrates with the standard Python `logging` module, allowing youto send processed log data to Large Language Models (LLMs) like OpenAI's GPT series or local HuggingFace models for advanced analysis, anomaly detection, or summarization.

## Key Features

*   **AI-Powered Log Analysis**: Send batches of logs to LLMs for insights.
*   **Intelligent Routing**: Route logs to different LLMs (e.g., GPT-4 for critical errors, GPT-3.5 for warnings, local models for debug) based on severity or custom logic using LangChain.
*   **Asynchronous Logging**: Built-in support for `QueueHandler` and `QueueListener` to prevent blocking application threads.
*   **PII Scrubbing**: Automatically detect and redact common Personally Identifiable Information (PII) from logs before sending them to AI models. Customizable rules.
*   **JSON Formatting**: Flexible JSON log formatter for structured logging.
*   **Micro-batching**: Collects log records into batches before processing to optimize AI API calls.
*   **Jinja2 Prompt Templating**: Customize prompts sent to LLMs using Jinja2 templates. A default template is provided.
*   **Configuration via Environment Variables**: Uses Pydantic for robust settings management (e.g., API keys, model names, batch sizes, feature flags).
*   **Prometheus Metrics**: Exposes key operational metrics (e.g., logs processed, AI calls, errors, latencies, queue depth, circuit breaker state) for monitoring.
*   **Circuit Breaker**: Basic circuit breaker pattern to temporarily halt AI calls if models are consistently failing.
*   **Retry Mechanism**: Automatic retries with exponential backoff for AI API calls.
*   **Health Check CLI**: A command-line tool to verify package configuration and component health.
*   **Extensible**: Designed to be extended with custom PII rules, Jinja2 templates, and AI response handlers.

## Installation

```bash
pip install -r requirements.txt
# Or, if/when published to PyPI:
# pip install ai_logging
```

Ensure you have the necessary dependencies, especially if you plan to use specific LLMs (e.g., `openai`, `langchain`, `transformers`, `torch`). Key dependencies are listed in `requirements.txt`.

## Quick Start

```python
import logging
import time
import os
from ai_logging import (
    AIHandler,
    get_async_logging_setup,
    start_prometheus_server_if_enabled,
    get_settings
)

# --- 0. Set Environment Variables (example) ---
# These should be set in your environment or a .env file
# os.environ["OPENAI_API_KEY"] = "YOUR_OPENAI_API_KEY" # Required for OpenAI
# os.environ["AI_LOGGING_PROMETHEUS_ENABLED"] = "true"
# os.environ["AI_LOGGING_FLUSH_INTERVAL_SECONDS"] = "10"

def main():
    # --- 1. Start Prometheus Server (optional, based on settings) ---
    settings = get_settings()
    start_prometheus_server_if_enabled(settings)
    if settings.ai_logging_prometheus_enabled:
        print(f"Prometheus server (if not already running) attempted start on port {settings.ai_logging_prometheus_port}")

    # --- 2. Get a logger ---
    logger = logging.getLogger("my_app")
    logger.setLevel(logging.DEBUG)

    # --- 3. Create AIHandler ---
    # It loads configuration from environment variables by default.
    ai_handler = AIHandler(level=logging.INFO) # Process INFO and above for AI

    # --- 4. Setup Asynchronous Logging (Recommended) ---
    # Create a simple console handler for the listener to also output to (for demo)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s (Listener) - %(message)s'))
    
    async_queue_handler, log_listener = get_async_logging_setup(ai_handler, console_handler)
    logger.addHandler(async_queue_handler)
    log_listener.start()
    print("Async logging with AIHandler started.")

    # --- 5. Log Messages ---
    logger.debug("This is a debug message.")
    logger.info("User 'alice@example.com' logged in.")
    logger.warning("API rate limit approaching for service 'X'.")
    try:
        1 / 0
    except Exception:
        logger.error("An error occurred during calculation.", exc_info=True, extra={"user_id": "bob"})
    
    logger.critical("Database connection lost!")

    # --- 6. Allow time for processing and shutdown ---
    print(f"Waiting for logs to be processed (approx {settings.ai_logging_flush_interval_seconds + 2}s)...")
    time.sleep(settings.ai_logging_flush_interval_seconds + 2) # Wait for AIHandler's flush interval + buffer

    print("Shutting down...")
    log_listener.stop()
    # logging.shutdown() # In a real app, ensure this is called on exit

if __name__ == "__main__":
    main()
```

See `examples/basic_usage.py` for a more detailed example.

## Configuration

The package is configured primarily through environment variables. A `.env` file can also be used (it will be loaded automatically if present in the working directory where `get_settings()` is first called).

Key environment variables (see `ai_logging/config/settings.py` for all options):

*   `OPENAI_API_KEY`: Your OpenAI API key (required for OpenAI models).
*   `AI_LOGGING_DEFAULT_LEVEL`: Default log level for the `AILogger` class (e.g., `INFO`).
*   `AI_LOGGING_BATCH_SIZE`: Number of log records to batch before sending to AI (default: `10`).
*   `AI_LOGGING_FLUSH_INTERVAL_SECONDS`: Interval in seconds to flush logs even if batch size isn't met (default: `5.0`).
*   `AI_LOGGING_MAX_RETRIES`: Max retries for AI API calls (default: `3`).
*   `AI_LOGGING_GPT4_MODEL_NAME`: Model name for GPT-4 (default: `gpt-4`).
*   `AI_LOGGING_GPT35_MODEL_NAME`: Model name for GPT-3.5 (default: `gpt-3.5-turbo`).
*   `AI_LOGGING_GPT4_SEVERITY_THRESHOLD`: Log level at or above which GPT-4 is considered (e.g., `ERROR`).
*   `AI_LOGGING_ENABLE_LOCAL_MODEL`: Set to `true` to enable local HuggingFace models (default: `false`).
*   `AI_LOGGING_LOCAL_MODEL_NAME_OR_PATH`: Name or path for the local model (default: `distilgpt2`).
*   `AI_LOGGING_JINJA_TEMPLATE_DIR`: Path to a directory containing custom Jinja2 prompt templates.
*   `AI_LOGGING_JINJA_LOG_PROMPT_TEMPLATE_NAME`: Filename of the Jinja2 template to use for log prompts (default: `default_log_prompt.jinja2`).
*   `AI_LOGGING_PII_RULES_JSON`: JSON string defining custom PII scrubbing rules.
*   `AI_LOGGING_PII_USE_DEFAULT_RULES`: Set to `false` to disable default PII rules (default: `true`).
*   `AI_LOGGING_PROMETHEUS_ENABLED`: Set to `true` to enable Prometheus metrics (default: `true`).
*   `AI_LOGGING_PROMETHEUS_PORT`: Port for the Prometheus metrics server (default: `9095`).

## Core Components

*   **`AILogger` (in `ai_logging.logger`)**: Custom logger class (optional, standard loggers work fine with `AIHandler`).
*   **`get_ai_logger()` (in `ai_logging.logger`)**: Helper to get an `AILogger` instance.
*   **`AIHandler` (in `ai_logging.handlers.ai_handler`)**: The core handler that processes logs, batches them, scrubs PII, formats prompts, routes to LLMs, and handles responses.
*   **`get_async_logging_setup()` (in `ai_logging.handlers.queue_handler`)**: Sets up `QueueHandler` and `QueueListener` for asynchronous logging with downstream handlers (like `AIHandler`).
*   **`JsonFormatter` (in `ai_logging.utils.json_formatter`)**: A `logging.Formatter` that outputs log records as JSON strings.
*   **`scrub_pii_from_dict()` (in `ai_logging.utils.pii_filter`)**: Utility to scrub PII from dictionaries.
*   **`LLMRouter` (in `ai_logging.router.llm_router`)**: Routes prompts to configured LLMs based on severity or other logic. (Uses LangChain components internally, currently with placeholders if LangChain isn't fully set up).
*   **`Settings` / `get_settings()` (in `ai_logging.config.settings`)**: Pydantic-based configuration management.
*   **Prometheus Metrics (in `ai_logging.metrics.prometheus`)**: Provides metrics via `get_metrics_instance()` and starts the server via `start_prometheus_server_if_enabled()`.

## Health Check CLI

A CLI tool is provided to check the health and configuration of the `ai_logging` package.

```bash
python -m ai_logging.cli.health_check
```

This will:
*   Attempt to load settings.
*   Check for essential configurations (e.g., API keys).
*   Try to initialize the `LLMRouter` and report available models.
*   Verify Jinja2 template loading.
*   Check Prometheus metrics status (if enabled).

## Development & Testing

(Placeholder for development setup, running tests, contributing guidelines)

*   Install development dependencies: `pip install -r requirements-dev.txt` (if such a file exists).
*   Run tests: `pytest` (tests are yet to be written).

## Future Enhancements

*   More sophisticated LangChain integration (e.g., `RouterChain`, specific chains for different log types).
*   More robust circuit breaker logic (e.g., half-open state checks).
*   Support for more LLM providers and local model types.
*   Advanced PII detection rules and techniques.
*   Callback mechanisms for AI responses.
*   Comprehensive test suite.
*   Detailed documentation for each module.

## License

(Placeholder - e.g., MIT License)
