"""Custom Jinja2 prompt template demonstration.

Points AIHandler at a project-local template directory and template name
via LOGSCRIBE_JINJA_TEMPLATE_DIR / LOGSCRIBE_JINJA_LOG_PROMPT_TEMPLATE_NAME,
instead of the package's built-in default_log_prompt.jinja2. See
examples/templates/incident_prompt.jinja2 -- it asks the model to
structure its answer as SEVERITY / ROOT CAUSE / SUGGESTED ACTION sections,
which suits an on-call triage workflow better than the generic default.

Run:
    python examples/custom_prompt_template.py

No provider API key is required to see the custom template take effect --
this only demonstrates that AIHandler loads and renders it. Without a key,
route_prompt() returns None end-to-end (see README's Quickstart).
"""

import logging
import os
from pathlib import Path

from logscribe import AIHandler
from logscribe.config.settings import reset_settings

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "incident_prompt.jinja2"


def main() -> None:
    os.environ["LOGSCRIBE_JINJA_TEMPLATE_DIR"] = str(TEMPLATE_DIR)
    os.environ["LOGSCRIBE_JINJA_LOG_PROMPT_TEMPLATE_NAME"] = TEMPLATE_NAME
    reset_settings()  # force Settings to re-read the env vars we just set

    handler = AIHandler(batch_size=1, flush_interval=0.2)
    try:
        # handler.jinja_template.name is the loaded template's filename --
        # it's None for the inline fallback template used when the
        # configured template can't be found, so this confirms the custom
        # template actually loaded.
        print(f"AIHandler loaded template: {handler.jinja_template.name}")

        logger = logging.getLogger("logscribe.examples.custom_prompt_template")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.error("payment-service pod OOMKilled after a memory spike")
    finally:
        handler.close()
        del os.environ["LOGSCRIBE_JINJA_TEMPLATE_DIR"]
        del os.environ["LOGSCRIBE_JINJA_LOG_PROMPT_TEMPLATE_NAME"]
        reset_settings()

    print("Done. The rendered prompt asked for SEVERITY / ROOT CAUSE / SUGGESTED ACTION.")


if __name__ == "__main__":
    main()
