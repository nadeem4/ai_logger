import re
from collections.abc import Callable, Mapping, Sequence
from re import Pattern
from typing import Any

# --- Default PII Scrubbing Rules ---
# Each rule is a dictionary with 'name', 'regex', and 'replacement'
# Users can extend or override these.
#
# `Mapping`/`Sequence` (rather than `dict`/`list`) are used below for
# parameter types because they are covariant in their value/element type,
# while `dict`/`list` are invariant. That lets callers pass narrower types --
# e.g. Settings' parsed `list[dict[str, str]]` PII rules, which never carry a
# Pattern or callable replacement -- without a spurious variance mismatch.
RuleValue = str | Pattern | Callable
Rule = Mapping[str, RuleValue]

DEFAULT_PII_RULES: list[dict[str, RuleValue]] = [
    {
        "name": "email",
        "regex": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        "replacement": "[REDACTED_EMAIL]",
    },
    {
        "name": "ipv4",
        "regex": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
        "replacement": "[REDACTED_IP]",
    },
    {
        "name": "credit_card_visa",  # Basic Visa pattern
        "regex": re.compile(r"\b4[0-9]{12}(?:[0-9]{3})?\b"),
        "replacement": "[REDACTED_CREDIT_CARD]",
    },
    {
        "name": "credit_card_mastercard",  # Basic Mastercard pattern
        "regex": re.compile(r"\b5[1-5][0-9]{14}\b"),
        "replacement": "[REDACTED_CREDIT_CARD]",
    },
    {
        "name": "credit_card_amex",  # Basic Amex pattern
        "regex": re.compile(r"\b3[47][0-9]{13}\b"),
        "replacement": "[REDACTED_CREDIT_CARD]",
    },
    # Add more rules as needed (e.g., phone numbers, SSNs - be careful with SSN regex accuracy)
]


def compile_rules(
    rules: Sequence[Rule],
) -> list[Mapping[str, RuleValue]]:
    """Compiles regex strings in rules to re.Pattern objects if not already compiled."""
    compiled_rules: list[Mapping[str, RuleValue]] = []
    for rule in rules:
        if isinstance(rule["regex"], str):
            try:
                compiled_rules.append({**rule, "regex": re.compile(rule["regex"])})
            except re.error as e:
                print(
                    f"Warning: Invalid regex for PII rule '{rule.get('name', 'Unnamed')}': {rule['regex']}. Error: {e}. Skipping rule."
                )
                # Or raise an error, depending on desired strictness
        else:
            compiled_rules.append(rule)
    return compiled_rules


def scrub_text(text: str, compiled_rules: Sequence[Rule]) -> str:
    """
    Scrubs PII from a single string based on the provided compiled rules.
    """
    if not isinstance(text, str):
        return text  # Only scrub strings

    scrubbed_text = text
    for rule in compiled_rules:
        regex_pattern = rule["regex"]
        replacement = rule["replacement"]
        if isinstance(regex_pattern, Pattern):  # re.Pattern
            if callable(replacement):  # Replacement function
                scrubbed_text = regex_pattern.sub(replacement, scrubbed_text)
            else:  # Replacement string
                scrubbed_text = regex_pattern.sub(str(replacement), scrubbed_text)
    return scrubbed_text


def scrub_pii_from_dict(
    data: dict[str, Any],
    custom_rules: Sequence[Rule] | None = None,
    use_default_rules: bool = True,
    max_depth: int = 10,  # Max recursion depth to prevent infinite loops
) -> dict[str, Any]:
    """
    Recursively scrubs PII from string values within a dictionary.

    Args:
        data: The dictionary to scrub.
        custom_rules: A list of custom rule dictionaries. Each rule should have
                      'name' (str), 'regex' (str or re.Pattern), and
                      'replacement' (str or callable).
        use_default_rules: Whether to include the DEFAULT_PII_RULES.
        max_depth: Maximum recursion depth for nested structures.

    Returns:
        A new dictionary with PII scrubbed from its string values.
    """
    all_rules: list[Mapping[str, RuleValue]] = []
    if use_default_rules:
        all_rules.extend(DEFAULT_PII_RULES)
    if custom_rules:
        all_rules.extend(custom_rules)

    if not all_rules:
        return data  # No rules to apply

    compiled_rules = compile_rules(all_rules)

    def _scrub_recursive(current_item: Any, current_depth: int) -> Any:
        if current_depth > max_depth:
            # Consider logging a warning here if a logger is available
            # print("Warning: Max PII scrubbing depth reached.")
            return current_item

        if isinstance(current_item, dict):
            new_dict = {}
            for k, v in current_item.items():
                new_dict[k] = _scrub_recursive(v, current_depth + 1)
            return new_dict
        elif isinstance(current_item, list):
            new_list = []
            for item in current_item:
                new_list.append(_scrub_recursive(item, current_depth + 1))
            return new_list
        elif isinstance(current_item, str):
            return scrub_text(current_item, compiled_rules)
        else:
            return current_item

    return _scrub_recursive(data, 0)
