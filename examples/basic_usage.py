"""Minimal, runnable loglens quickstart.

Attaches AIHandler to a logger via the async queue setup (see README's
Quickstart), logs a few messages -- including one that trips the default
PII scrubber and one with a traceback -- waits for AIHandler's background
worker to flush and call the LLM, then shuts everything down cleanly.

Run:
    export OPENAI_API_KEY=sk-...
    # or: export ANTHROPIC_API_KEY=sk-ant-...  LOGLENS_PROVIDER=anthropic
    python examples/basic_usage.py

Without a provider API key configured, AIHandler still runs end-to-end
(batching, PII scrubbing, prompt rendering) -- route_prompt() just returns
None and no AI call is made. That's fine for a library caller, but it is
not a useful first thing for someone running *this script* to see, so this
example instead prints setup instructions and exits with status 1.
"""

import logging
import sys
import time

from loglens import AIHandler, get_async_logging_setup, get_settings


def _provider_key_configured() -> bool:
    """True if the configured provider (LOGLENS_PROVIDER, default
    'openai') has its API key set."""
    settings = get_settings()
    if settings.loglens_provider == "anthropic":
        return bool(settings.anthropic_api_key)
    return bool(settings.openai_api_key)


def run_demo() -> None:
    """Logs a handful of messages through AIHandler and waits for them to
    be batched, scrubbed, rendered, and routed to the LLM."""
    logger = logging.getLogger("loglens.examples.basic_usage")
    logger.setLevel(logging.DEBUG)

    ai_handler = AIHandler(level=logging.INFO)
    queue_handler, listener = get_async_logging_setup(ai_handler)
    logger.addHandler(queue_handler)
    listener.start()

    try:
        logger.info("user 'demo@example.com' logged in from 192.168.1.42")
        logger.warning("cache miss rate above threshold: 87%")
        try:
            1 / 0
        except ZeroDivisionError:
            logger.error("division by zero while computing conversion ratio", exc_info=True)

        settings = get_settings()
        wait_seconds = settings.loglens_flush_interval_seconds + 1
        print(f"Waiting {wait_seconds:.1f}s for AIHandler to flush and call the LLM...")
        time.sleep(wait_seconds)
    finally:
        # Order matters: stop the listener first so no more records land in
        # AIHandler's buffer after we start closing it.
        listener.stop()
        ai_handler.close()

    print("Done. Check the 'loglens.ai_responses' logger for the AI's analysis.")


def main() -> int:
    if not _provider_key_configured():
        print(
            "No provider API key is configured, so this demo has nothing to show --\n"
            "route_prompt() would return None the whole time.\n\n"
            "Set one of:\n"
            "  export OPENAI_API_KEY=sk-...\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...   (and LOGLENS_PROVIDER=anthropic)\n\n"
            "then re-run: python examples/basic_usage.py",
            file=sys.stderr,
        )
        return 1

    run_demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
