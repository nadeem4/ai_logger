import logging
import time

import pytest

from loglens.handlers.queue_handler import get_async_logging_setup


def test_raises_without_any_downstream_handlers():
    with pytest.raises(ValueError, match="At least one downstream handler"):
        get_async_logging_setup()


def test_records_reach_downstream_handler_via_listener_thread():
    received = []

    class CollectingHandler(logging.Handler):
        def emit(self, record):
            received.append(record.getMessage())

    queue_handler, listener = get_async_logging_setup(CollectingHandler())
    test_logger = logging.getLogger("test.queue_handler.delivery")
    test_logger.setLevel(logging.DEBUG)
    test_logger.addHandler(queue_handler)
    test_logger.propagate = False

    listener.start()
    try:
        test_logger.info("hello via queue")
        deadline = time.time() + 2
        while time.time() < deadline and not received:
            time.sleep(0.01)
    finally:
        listener.stop()
        test_logger.removeHandler(queue_handler)

    assert received == ["hello via queue"]
