import logging
import logging.handlers
import queue
from typing import Tuple


def get_async_logging_setup(
    *handlers: logging.Handler,
) -> Tuple[logging.handlers.QueueHandler, logging.handlers.QueueListener]:
    """
    Sets up asynchronous logging using a standard Python queue.

    This function creates a queue, a QueueHandler to put log records into the
    queue, and a QueueListener to process records from the queue using the
    provided downstream handlers.

    Args:
        *handlers: One or more logging.Handler instances that will perform the
                   actual logging (e.g., StreamHandler, FileHandler, AIHandler)
                   from the listener's thread.

    Returns:
        A tuple containing:
            - queue_handler (logging.handlers.QueueHandler): This handler should
              be added to your logger(s). It will enqueue log records.
            - listener (logging.handlers.QueueListener): This listener must be
              started (listener.start()) by the application to begin processing
              log records from the queue. It should also be stopped
              (listener.stop()) on application exit.

    Raises:
        ValueError: If no downstream handlers are provided.
    """
    if not handlers:
        raise ValueError(
            "At least one downstream handler must be provided to process logs from the queue."
        )

    # Create an unbounded queue to hold log records
    log_queue: queue.Queue = queue.Queue(-1)

    # Create a QueueHandler. This handler will be added to the logger(s)
    # and will put log records into log_queue.
    queue_handler = logging.handlers.QueueHandler(log_queue)

    # Create a QueueListener. This listener runs in a separate thread,
    # monitors log_queue, and dispatches records to the downstream handlers.
    listener = logging.handlers.QueueListener(log_queue, *handlers, respect_handler_level=True)

    return queue_handler, listener


if __name__ == "__main__":
    # This section is for demonstration and basic testing of this module.
    # It shows how to use get_async_logging_setup.

    # 1. Get a logger instance
    demo_logger = logging.getLogger("loglens.demo_async")
    demo_logger.setLevel(logging.DEBUG)  # Process all messages from DEBUG upwards

    # 2. Create downstream handler(s) - e.g., a console handler
    console_formatter = logging.Formatter(
        "%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)  # Console handler will only show INFO and above

    # 3. Get the asynchronous logging setup
    # Pass the console_handler to be managed by the listener
    async_handler, log_listener = get_async_logging_setup(console_handler)

    # 4. Add the async_handler (QueueHandler) to the logger
    demo_logger.addHandler(async_handler)

    # 5. Start the listener (essential for processing logs)
    print("Starting QueueListener...")
    log_listener.start()
    print("QueueListener started.")

    # 6. Log some messages
    demo_logger.debug("This is a DEBUG message from the main thread.")  # Will be queued
    demo_logger.info("This is an INFO message from the main thread.")  # Will be queued
    demo_logger.warning("This is a WARNING message from the main thread.")  # Will be queued

    # Give the listener thread some time to process the queued messages
    import time

    time.sleep(0.5)

    # 7. Stop the listener (important for clean shutdown)
    print("Stopping QueueListener...")
    log_listener.stop()
    print("QueueListener stopped.")

    # Logs after listener stop might be lost if the queue is not processed.
    # The QueueHandler doesn't have a fallback by default if the listener is down.
    demo_logger.info(
        "This message is logged after listener stop (likely lost or remains in queue)."
    )

    # To ensure all messages are flushed before stopping, especially if the queue might be large
    # or processing slow, one might need more sophisticated shutdown logic,
    # e.g., checking queue size or using a sentinel object in the queue.
    # For most cases, listener.stop() attempts a graceful shutdown.
    print("Async logging demonstration complete.")
