"""Custom PII rule demonstrations.

logscribe' default PII rules catch emails, IPv4 addresses, and common credit
card formats (see docs/PRIVACY.md), but not application-specific
identifiers. This example scrubs an internal order ID like "ORD-482910"
two different ways:

  1. LOGSCRIBE_PII_RULES_JSON: a JSON-encoded list of extra rules that
     AIHandler's *default* pii_scrubber (built from Settings) picks up
     automatically -- no code change needed.
  2. pii_scrubber=: a fully custom callable passed straight to AIHandler,
     which replaces the settings-driven default scrubber entirely.

Run:
    python examples/custom_pii_rules.py

No provider API key is required: PII scrubbing happens before any AI call
is made, and without a key route_prompt() simply returns None end-to-end
(see README's Quickstart) while this script still exits 0.
"""

import json
import logging
import os

from logscribe import AIHandler
from logscribe.config.settings import reset_settings
from logscribe.utils.pii_filter import scrub_pii_from_dict

# A rule dict has 'name', 'regex' (str or compiled Pattern), and
# 'replacement' (str or callable) -- see logscribe/utils/pii_filter.py.
ORDER_ID_RULE = {
    "name": "order_id",
    "regex": r"\bORD-\d{6}\b",
    "replacement": "[REDACTED_ORDER_ID]",
}


def demo_env_var_rules() -> None:
    """LOGSCRIBE_PII_RULES_JSON: extra rules loaded from settings and
    applied by AIHandler's default pii_scrubber."""
    os.environ["LOGSCRIBE_PII_RULES_JSON"] = json.dumps([ORDER_ID_RULE])
    reset_settings()  # force Settings to re-read the env var we just set

    handler = AIHandler(batch_size=1, flush_interval=0.2)
    try:
        logger = logging.getLogger("logscribe.examples.custom_pii_rules.env_var")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Refund issued for order ORD-482910")
    finally:
        handler.close()
        del os.environ["LOGSCRIBE_PII_RULES_JSON"]
        reset_settings()

    print("demo_env_var_rules: order ID scrubbed via LOGSCRIBE_PII_RULES_JSON.")


def demo_pii_scrubber_callable() -> None:
    """pii_scrubber=: a callable passed directly to AIHandler, bypassing
    the settings-driven default scrubber entirely."""

    def scrub(record: dict) -> dict:
        return scrub_pii_from_dict(record, custom_rules=[ORDER_ID_RULE])

    handler = AIHandler(batch_size=1, flush_interval=0.2, pii_scrubber=scrub)
    try:
        logger = logging.getLogger("logscribe.examples.custom_pii_rules.callable")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.info("Refund issued for order ORD-777001")
    finally:
        handler.close()

    print("demo_pii_scrubber_callable: order ID scrubbed via pii_scrubber=.")


def main() -> None:
    demo_env_var_rules()
    demo_pii_scrubber_callable()
    print("Done. Both demos scrubbed the ORD-###### pattern before prompt rendering.")


if __name__ == "__main__":
    main()
