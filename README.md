# loglens

**`loglens` is a Python logging toolkit designed to enhance standard logging with AI-powered analysis, insights, and intelligent routing.**

It seamlessly integrates with the standard Python `logging` module, allowing you to send processed log data to Large Language Models (LLMs) via OpenAI or Anthropic for advanced analysis, anomaly detection, or summarization.

## Key Features

*   **AI-Powered Log Analysis**: Send batches of logs to LLMs for insights.
*   **Intelligent Routing**: Route logs to a fast or capable model tier based on the highest log severity in a batch, using pluggable OpenAI and Anthropic providers.
*   **Asynchronous Logging**: Built-in support for `QueueHandler` and `QueueListener` to prevent blocking application threads.
*   **PII Scrubbing**: Automatically detect and redact common Personally Identifiable Information (PII) from logs before sending them to AI models. Customizable rules.
*   **JSON Formatting**: Flexible JSON log formatter for structured logging.
*   **Micro-batching**: Collects log records into batches before processing to optimize AI API calls.
*   **Jinja2 Prompt Templating**: Customize prompts sent to LLMs using Jinja2 templates. A default template is provided.
*   **Configuration via Environment Variables**: Uses Pydantic for robust settings management (e.g., API keys, model names, batch sizes, feature flags).
*   **Prometheus Metrics**: Exposes key operational metrics (e.g., logs processed, AI calls, errors, latencies, queue depth, circuit breaker state) for monitoring.
*   **Circuit Breaker**: CLOSED / OPEN / HALF_OPEN circuit breaker with real half-open recovery to temporarily halt AI calls if models are consistently failing.
*   **Retry Mechanism**: Automatic retries with exponential backoff for AI API calls.
*   **Health Check CLI**: A command-line tool to verify package configuration and component health.
*   **Extensible**: Designed to be extended with custom PII rules, Jinja2 templates, and AI response handlers.

## Installation

```bash
pip install loglens
```

Core dependencies are `pydantic`, `pydantic-settings`, and `Jinja2`. Optional extras (declared in `pyproject.toml`) add support for specific providers and metrics:

```bash
pip install loglens[openai]       # OpenAI provider
pip install loglens[anthropic]    # Anthropic provider
pip install loglens[metrics]      # Prometheus metrics
```

## Quick Start

```python
import logging
import time
import os
from loglens import (
    AIHandler,
    get_async_logging_setup,
    start_prometheus_server_if_enabled,
    get_settings
)

# --- 0. Set Environment Variables (example) ---
# These should be set in your environment or a .env file
# os.environ["OPENAI_API_KEY"] = "YOUR_OPENAI_API_KEY" # Required for OpenAI
# os.environ["LOGLENS_PROMETHEUS_ENABLED"] = "true"
# os.environ["LOGLENS_FLUSH_INTERVAL_SECONDS"] = "10"

def main():
    # --- 1. Start Prometheus Server (optional, based on settings) ---
    settings = get_settings()
    start_prometheus_server_if_enabled(settings)
    if settings.loglens_prometheus_enabled:
        print(f"Prometheus server (if not already running) attempted start on port {settings.loglens_prometheus_port}")

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
    print(f"Waiting for logs to be processed (approx {settings.loglens_flush_interval_seconds + 2}s)...")
    time.sleep(settings.loglens_flush_interval_seconds + 2) # Wait for AIHandler's flush interval + buffer

    print("Shutting down...")
    log_listener.stop()
    # logging.shutdown() # In a real app, ensure this is called on exit

if __name__ == "__main__":
    main()
```

See `examples/basic_usage.py` for a more detailed example.

## Configuration

The package is configured primarily through environment variables. A `.env` file can also be used (it will be loaded automatically if present in the working directory where `get_settings()` is first called).

Key environment variables (see `loglens/config/settings.py` for all options):

*   `OPENAI_API_KEY`: Your OpenAI API key (required for OpenAI models).
*   `LOGLENS_DEFAULT_LEVEL`: Default log level for the `AILogger` class (e.g., `INFO`).
*   `LOGLENS_BATCH_SIZE`: Number of log records to batch before sending to AI (default: `10`).
*   `LOGLENS_FLUSH_INTERVAL_SECONDS`: Interval in seconds to flush logs even if batch size isn't met (default: `5.0`).
*   `LOGLENS_MAX_RETRIES`: Max retries for AI API calls (default: `3`).
*   `ANTHROPIC_API_KEY`: Your Anthropic API key (required for the Anthropic provider).
*   `LOGLENS_PROVIDER`: Which provider to route to, `openai` or `anthropic` (default: `openai`).
*   `LOGLENS_FAST_MODEL`: Model used for the fast tier (default: `gpt-4o-mini`).
*   `LOGLENS_CAPABLE_MODEL`: Model used for the capable tier (default: `gpt-4o`).
*   `LOGLENS_CAPABLE_SEVERITY_THRESHOLD`: Log level at or above which the capable tier is used (default: `ERROR`).
*   `LOGLENS_CB_FAILURE_THRESHOLD`: Consecutive batch failures before the circuit breaker opens (default: `3`).
*   `LOGLENS_CB_RESET_TIMEOUT_SECONDS`: Seconds the circuit breaker stays open before allowing a half-open trial request (default: `60.0`).
*   `LOGLENS_JINJA_TEMPLATE_DIR`: Path to a directory containing custom Jinja2 prompt templates.
*   `LOGLENS_JINJA_LOG_PROMPT_TEMPLATE_NAME`: Filename of the Jinja2 template to use for log prompts (default: `default_log_prompt.jinja2`).
*   `LOGLENS_PII_RULES_JSON`: JSON string defining custom PII scrubbing rules.
*   `LOGLENS_PII_USE_DEFAULT_RULES`: Set to `false` to disable default PII rules (default: `true`).
*   `LOGLENS_PROMETHEUS_ENABLED`: Set to `true` to enable Prometheus metrics (default: `true`).
*   `LOGLENS_PROMETHEUS_PORT`: Port for the Prometheus metrics server (default: `9095`).

## Core Components

*   **`AILogger` (in `loglens.logger`)**: Custom logger class (optional, standard loggers work fine with `AIHandler`).
*   **`get_ai_logger()` (in `loglens.logger`)**: Helper to get an `AILogger` instance.
*   **`AIHandler` (in `loglens.handlers.ai_handler`)**: The core handler that processes logs, batches them, scrubs PII, formats prompts, routes to LLMs, and handles responses.
*   **`get_async_logging_setup()` (in `loglens.handlers.queue_handler`)**: Sets up `QueueHandler` and `QueueListener` for asynchronous logging with downstream handlers (like `AIHandler`).
*   **`JsonFormatter` (in `loglens.utils.json_formatter`)**: A `logging.Formatter` that outputs log records as JSON strings.
*   **`scrub_pii_from_dict()` (in `loglens.utils.pii_filter`)**: Utility to scrub PII from dictionaries.
*   **`LLMRouter` (in `loglens.router.llm_router`)**: Routes a prompt to a fast or capable provider based on the highest log severity in the batch, against a configurable threshold.
*   **`LLMProvider` / `OpenAIProvider` / `AnthropicProvider` / `ProviderError` (in `loglens.providers`)**: The provider layer `LLMRouter` routes to. Each provider lazily imports its SDK and raises `ProviderError` with a `pip install ...` message if it's missing.
*   **`CircuitBreaker` (in `loglens.utils.circuit_breaker`)**: CLOSED / OPEN / HALF_OPEN state machine that protects AI calls from repeatedly hitting a failing provider.
*   **`Settings` / `get_settings()` (in `loglens.config.settings`)**: Pydantic-based configuration management.
*   **Prometheus Metrics (in `loglens.metrics.prometheus`)**: Provides metrics via `get_metrics_instance()` and starts the server via `start_prometheus_server_if_enabled()`.

## Health Check CLI

A CLI tool is provided to check the health and configuration of the `loglens` package.

```bash
loglens-check
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

*   Support for more LLM providers and local model types.
*   Advanced PII detection rules and techniques.
*   Callback mechanisms for AI responses.
*   Comprehensive test suite.
*   Detailed documentation for each module.

## License

MIT License. See [LICENSE](LICENSE) for the full text.
