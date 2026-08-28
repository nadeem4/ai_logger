import logging
import time

from loglens import AIHandler, get_async_logging_setup
from loglens.router.llm_router import LLMRouter


class CapturingProvider:
    model = "fake"

    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return "AI: 1 error, root cause likely DB"


def test_end_to_end_pipeline():
    logger = logging.getLogger("e2e")
    original_handlers = logger.handlers
    original_level = logger.level
    listener = None
    h = None
    try:
        fast, capable = CapturingProvider(), CapturingProvider()
        responses = []
        h = AIHandler(
            batch_size=3,
            flush_interval=60,
            llm_router=LLMRouter(fast=fast, capable=capable),
            ai_response_callback=responses.append,
        )
        qh, listener = get_async_logging_setup(h)
        logger.setLevel(logging.DEBUG)
        logger.handlers = [qh]
        listener.start()

        logger.info("user alice@example.com logged in")
        logger.warning("disk 90%")
        logger.error("db connect failed to 10.0.0.5")

        deadline = time.time() + 5
        while time.time() < deadline and not responses:
            time.sleep(0.05)
        listener.stop()
        h.close()

        assert responses and "root cause" in responses[0]
        all_prompts = "".join(capable.prompts + fast.prompts)
        assert "alice@example.com" not in all_prompts  # PII scrubbed
        assert "[REDACTED_EMAIL]" in all_prompts
        assert capable.prompts, "ERROR in batch should route to capable tier"
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
