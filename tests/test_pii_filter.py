import re

from loglens.utils.pii_filter import (
    compile_rules,
    scrub_pii_from_dict,
    scrub_text,
)


def test_module_imports():
    from loglens.utils import pii_filter  # currently raises NameError: Optional

    assert hasattr(pii_filter, "scrub_pii_from_dict")


def test_scrubs_email():
    from loglens.utils.pii_filter import scrub_pii_from_dict

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


def test_scrub_text_passes_through_non_string_values_unchanged():
    assert scrub_text(42, []) == 42
    assert scrub_text(None, []) is None


def test_scrub_text_applies_callable_replacement():
    rules = [
        {
            "name": "digits",
            "regex": re.compile(r"\d+"),
            "replacement": lambda m: f"<{m.group(0)}>",
        }
    ]
    assert scrub_text("order 12345 shipped", rules) == "order <12345> shipped"


def test_scrub_pii_from_dict_uses_callable_replacement_end_to_end():
    def mask_ip(match: re.Match) -> str:
        parts = match.group(0).split(".")
        return f"{parts[0]}.{parts[1]}.x.x"

    rules = [
        {
            "name": "ip_mask",
            "regex": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
            "replacement": mask_ip,
        }
    ]
    out = scrub_pii_from_dict({"m": "from 10.1.2.3"}, custom_rules=rules, use_default_rules=False)
    assert out["m"] == "from 10.1.x.x"


def test_compile_rules_mixes_valid_and_invalid_patterns():
    rules = [
        {"name": "good", "regex": r"\d+", "replacement": "[N]"},
        {"name": "bad", "regex": "([", "replacement": "x"},
        {"name": "precompiled", "regex": re.compile(r"[a-z]+"), "replacement": "[W]"},
    ]
    compiled = compile_rules(rules)
    assert len(compiled) == 2  # the invalid one is skipped
    names = {r["name"] for r in compiled}
    assert names == {"good", "precompiled"}
    for rule in compiled:
        assert isinstance(rule["regex"], re.Pattern)


def test_max_depth_stops_recursion_and_returns_item_unscrubbed():
    # Two levels of list nesting with max_depth=1: the innermost string is
    # past the depth limit and must come back untouched rather than scrubbed.
    data = {"a": ["outer", ["alice@example.com"]]}
    out = scrub_pii_from_dict(data, max_depth=1)
    assert out["a"][1][0] == "alice@example.com"
