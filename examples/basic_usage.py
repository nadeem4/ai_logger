import logging
import time
import os

# Import components from the loglens package
from loglens import (
    get_ai_logger,
    AIHandler,
    JsonFormatter,
    get_async_logging_setup,
    start_prometheus_server_if_enabled,
    get_settings
)

def setup_basic_loglens():
    """Sets up a logger with AIHandler for demonstration."""

    # --- 1. Get loglens specific settings (optional, AIHandler loads them by default) ---
    # You can inspect settings if needed, e.g., to check if Prometheus is enabled.
    settings = get_settings()
    print(f"AI Logging Example: Prometheus enabled in settings: {settings.loglens_prometheus_enabled}")
    print(f"AI Logging Example: OpenAI API Key is set: {'Yes' if settings.openai_api_key else 'No'}")
    
    # --- 2. Start Prometheus Server (if enabled in settings) ---
    # This should ideally be called once at application startup.
    # The function is idempotent, so calling it multiple times is safe.
    start_prometheus_server_if_enabled(settings)
    if settings.loglens_prometheus_enabled:
        print(f"AI Logging Example: Prometheus server (if not already running and prometheus_client is installed) "
              f"attempted to start on port {settings.loglens_prometheus_port}.")
        print(f"  Metrics endpoint: http://localhost:{settings.loglens_prometheus_port}/")


    # --- 3. Get a logger instance ---
    # Using get_ai_logger ensures it's an AILogger instance if logging.setLoggerClass(AILogger)
    # hasn't been called globally. For simplicity, we'll use a standard logger here
    # and add AIHandler to it. AILogger class itself doesn't add AI capabilities
    # without an AIHandler.
    logger = logging.getLogger("my_application")
    logger.setLevel(logging.DEBUG) # Process all messages from DEBUG upwards at logger level

    # --- 4. Create and Configure AIHandler ---
    # The AIHandler will use settings from environment variables by default.
    # You can override batch_size, flush_interval, etc., here if needed.
    ai_handler = AIHandler(
        level=logging.INFO # AIHandler will only process INFO and above
        # batch_size=5, # Example override
        # flush_interval=10.0 # Example override
    )

    # Optional: Set a specific formatter for the AIHandler if you don't want
    # it to use its internal JsonFormatter logic directly for preparing records.
    # However, AIHandler's prepare_record_for_processing is designed to create
    # the dictionary structure it needs. If you add a formatter here, it affects
    # what `record.getMessage()` might return if the formatter is a `logging.Formatter`.
    # For AIHandler, it's often best to let it handle the final dict conversion.
    # If you *do* want to ensure logs passed to AIHandler are JSON strings from the start:
    # json_formatter = JsonFormatter()
    # ai_handler.setFormatter(json_formatter) # This means emit() gets a pre-formatted JSON string

    # --- 5. Optional: Setup Asynchronous Logging using QueueHandler ---
    # This is recommended for performance to avoid blocking application threads.
    # Create a standard console handler for the listener to output to (for this demo)
    console_log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s (Listener) - %(message)s')
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_log_formatter)
    console_handler.setLevel(logging.DEBUG) # Listener's console handler shows all

    # The get_async_logging_setup takes the "downstream" handlers that the listener will use.
    # Here, we pass our AIHandler and a console_handler.
    async_queue_handler, log_listener = get_async_logging_setup(ai_handler, console_handler)
    
    # Add the async_queue_handler to your logger(s).
    logger.addHandler(async_queue_handler)
    
    # Start the listener thread. This is crucial!
    print("AI Logging Example: Starting QueueListener for asynchronous logging...")
    log_listener.start()
    print("AI Logging Example: QueueListener started.")

    # If not using async, you would add ai_handler directly:
    # logger.addHandler(ai_handler)
    # And add a console handler for regular output:
    # simple_console_handler = logging.StreamHandler()
    # simple_console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    # logger.addHandler(simple_console_handler)


    # --- 6. Log some messages ---
    print("\nAI Logging Example: Logging messages...")
    logger.debug("This is a DEBUG message. (Sent to queue, AIHandler might ignore based on its level)")
    logger.info("User 'test_user@example.com' logged in successfully.")
    logger.info("Processing order #12345 for item 'Super Gadget'.")
    
    # Simulate some activity
    time.sleep(1) 
    
    logger.warning("Low disk space warning: /var/log is 90% full.")
    logger.info("User 'another_user@test.co' accessed sensitive resource 'config.ini'. IP: 192.168.1.101")

    # Simulate more activity to potentially trigger a batch flush by size
    for i in range(5):
        logger.info(f"Batch filler message {i+1}. Credit card: 4111000011112222") # PII example
        time.sleep(0.05)

    try:
        x = 1 / 0
    except ZeroDivisionError:
        logger.error("A division by zero error occurred!", exc_info=True, extra={"calculation_details": "1/0"})

    logger.critical("System experiencing critical load! Payment gateway 'stripe' unresponsive. IP: 10.0.0.5")

    # --- 7. Wait for AIHandler to process (especially if timed flush is long) ---
    # The AIHandler has its own flush_interval.
    # If using QueueListener, logs are passed quickly to AIHandler's buffer.
    # For this demo, let's wait a bit longer than AIHandler's default flush interval.
    wait_time = settings.loglens_flush_interval_seconds + 2
    print(f"\nAI Logging Example: Waiting for {wait_time:.1f}s to allow AIHandler to process and flush...")
    time.sleep(wait_time)

    # --- 8. Cleanly shutdown the listener and handlers ---
    print("AI Logging Example: Shutting down...")
    print("AI Logging Example: Stopping QueueListener...")
    log_listener.stop() # Stops the listener thread (logging.handlers.QueueListener has no is_alive())
    print("AI Logging Example: QueueListener stopped.")

    # AIHandler's close method will also flush any remaining logs.
    # This is automatically called on handlers when logging.shutdown() is called,
    # but explicit close is good practice if you manage handlers directly.
    # ai_handler.close() # If not using queue listener or want to be explicit

    # For a clean exit in a real application, ensure logging.shutdown() is called.
    # logging.shutdown() # This will close all handlers

    print("\nAI Logging Example: Basic usage demo complete.")
    print("Check console output for logs processed by the listener and AIHandler's AI interactions.")
    if settings.loglens_prometheus_enabled:
         print(f"If Prometheus server is running, check metrics at http://localhost:{settings.loglens_prometheus_port}/")


if __name__ == "__main__":
    # --- Environment Variable Setup (for testing this example directly) ---
    # In a real app, these would be set in your environment or a .env file.
    # os.environ["LOGLENS_DEFAULT_LEVEL"] = "DEBUG"
    # os.environ["OPENAI_API_KEY"] = "YOUR_OPENAI_API_KEY" # Replace if you want to test real OpenAI calls
    # os.environ["LOGLENS_PROMETHEUS_ENABLED"] = "true"
    # os.environ["LOGLENS_JINJA_LOG_PROMPT_TEMPLATE_NAME"] = "default_log_prompt.jinja2"
    # os.environ["LOGLENS_CAPABLE_MODEL"] = "gpt-4-turbo-preview" # Example
    
    # If OPENAI_API_KEY (or ANTHROPIC_API_KEY, depending on LOGLENS_PROVIDER) is not
    # set, LLMRouter has no provider configured: it logs a warning and route_prompt()
    # returns None instead of making an AI call.
    if not os.getenv("OPENAI_API_KEY"):
        print("WARNING: OPENAI_API_KEY environment variable is not set. LLMRouter will have no provider")
        print("         configured, so AI calls will be skipped (route_prompt() returns None).")
        print("         Set this variable if you want to test with actual OpenAI models.\n")

    setup_basic_loglens()
    logging.shutdown() # Ensure all handlers are closed
