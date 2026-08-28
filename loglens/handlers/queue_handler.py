import logging
import logging.handlers
import queue


def get_async_logging_setup(
    *handlers: logging.Handler,
) -> tuple[logging.handlers.QueueHandler, logging.handlers.QueueListener]:
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
