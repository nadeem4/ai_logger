import re
from ai_logging.utils.pii_filter import scrub_pii_from_dict, scrub_text, compile_rules, DEFAULT_PII_RULES


def test_module_imports():
    from ai_logging.utils import pii_filter  # currently raises NameError: Optional
    assert hasattr(pii_filter, "scrub_pii_from_dict")

def test_scrubs_email():
    from ai_logging.utils.pii_filter import scrub_pii_from_dict
    out = scrub_pii_from_dict({"msg": "contact alice@example.com now"})
    assert out["msg"] == "contact [REDACTED_EMAIL] now"

def test_scrubs_ipv4():
    assert scrub_pii_from_dict({"m": "host 10.0.0.1 down"})["m"] == "host [REDACTED_IP] down"

def test_scrubs_visa_card():
    assert "[REDACTED_CREDIT_CARD]" in scrub_pii_from_dict({"m": "card 4111111111111111"})["m"]

def test_nested_dict_and_lists_are_scrubbed():
    data = {"a": {"b": ["bob@x.io", {"c": "10.1.1.1"}]}}
    out = scrub_pii_from_dict(data)
    assert out["a"]["b"][0] == "[REDACTED_EMAIL]"
    assert out["a"]["b"][1]["c"] == "[REDACTED_IP]"

def test_custom_rule_applied():
    rules = [{"name": "order", "regex": r"ORD-\d+", "replacement": "[ORDER]"}]
    out = scrub_pii_from_dict({"m": "see ORD-123"}, custom_rules=rules)
    assert out["m"] == "see [ORDER]"

def test_defaults_can_be_disabled():
    out = scrub_pii_from_dict({"m": "a@b.co"}, use_default_rules=False)
    assert out["m"] == "a@b.co"

def test_non_string_values_pass_through():
    out = scrub_pii_from_dict({"n": 42, "f": 1.5, "b": True, "none": None})
    assert out == {"n": 42, "f": 1.5, "b": True, "none": None}

def test_invalid_custom_regex_is_skipped_not_fatal():
    rules = [{"name": "bad", "regex": "([", "replacement": "x"}]
    out = scrub_pii_from_dict({"m": "hello"}, custom_rules=rules)
    assert out["m"] == "hello"
