import re
from typing import Dict, Any, List, Union, Callable, Pattern

# --- Default PII Scrubbing Rules ---
# Each rule is a dictionary with 'name', 'regex', and 'replacement'
# Users can extend or override these.
DEFAULT_PII_RULES: List[Dict[str, Union[str, Pattern]]] = [
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
        "name": "credit_card_visa", # Basic Visa pattern
        "regex": re.compile(r"\b4[0-9]{12}(?:[0-9]{3})?\b"),
        "replacement": "[REDACTED_CREDIT_CARD]",
    },
    {
        "name": "credit_card_mastercard", # Basic Mastercard pattern
        "regex": re.compile(r"\b5[1-5][0-9]{14}\b"),
        "replacement": "[REDACTED_CREDIT_CARD]",
    },
    {
        "name": "credit_card_amex", # Basic Amex pattern
        "regex": re.compile(r"\b3[47][0-9]{13}\b"),
        "replacement": "[REDACTED_CREDIT_CARD]",
    },
    # Add more rules as needed (e.g., phone numbers, SSNs - be careful with SSN regex accuracy)
]

def compile_rules(rules: List[Dict[str, Union[str, Pattern]]]) -> List[Dict[str, Union[str, Pattern, Callable[[str], str]]]]:
    """Compiles regex strings in rules to re.Pattern objects if not already compiled."""
    compiled_rules = []
    for rule in rules:
        if isinstance(rule["regex"], str):
            try:
                compiled_rules.append({**rule, "regex": re.compile(rule["regex"])})
            except re.error as e:
                print(f"Warning: Invalid regex for PII rule '{rule.get('name', 'Unnamed')}': {rule['regex']}. Error: {e}. Skipping rule.")
                # Or raise an error, depending on desired strictness
        else:
            compiled_rules.append(rule)
    return compiled_rules


def scrub_text(text: str, compiled_rules: List[Dict[str, Union[str, Pattern, Callable]]]) -> str:
    """
    Scrubs PII from a single string based on the provided compiled rules.
    """
    if not isinstance(text, str):
        return text # Only scrub strings

    scrubbed_text = text
    for rule in compiled_rules:
        regex_pattern = rule["regex"]
        replacement = rule["replacement"]
        if isinstance(regex_pattern, Pattern): # re.Pattern
            if callable(replacement): # Replacement function
                scrubbed_text = regex_pattern.sub(replacement, scrubbed_text)
            else: # Replacement string
                scrubbed_text = regex_pattern.sub(str(replacement), scrubbed_text)
    return scrubbed_text

def scrub_pii_from_dict(
    data: Dict[str, Any],
    custom_rules: Optional[List[Dict[str, Union[str, Pattern]]]] = None,
    use_default_rules: bool = True,
    max_depth: int = 10 # Max recursion depth to prevent infinite loops
) -> Dict[str, Any]:
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
    all_rules: List[Dict[str, Union[str, Pattern]]] = []
    if use_default_rules:
        all_rules.extend(DEFAULT_PII_RULES)
    if custom_rules:
        all_rules.extend(custom_rules)

    if not all_rules:
        return data # No rules to apply

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


if __name__ == '__main__':
    # Example Usage
    test_data_dict = {
        "user_id": "user123",
        "user_email": "john.doe@example.com",
        "message": "User john.doe@example.com with IP 192.168.1.100 tried to pay with card 4111222233334444.",
        "details": {
            "ip_address": "10.0.0.5",
            "contact_info": ["jane.doe@test.co", "call 555-0100"], # Phone not in default rules
            "payment_attempts": [
                {"card_number": "5100123456789012", "status": "failed"},
                {"card_number": "370012345678901", "status": "approved"}
            ]
        },
        "notes": "Another email test@domain.com and IP 255.255.255.255.",
        "sensitive_id": "SSN-like: 000-00-0000" # Not in default rules
    }

    print("--- Original Dictionary ---")
    import json
    print(json.dumps(test_data_dict, indent=2))

    scrubbed_data_dict = scrub_pii_from_dict(test_data_dict)
    print("\n--- Scrubbed Dictionary (Default Rules) ---")
    print(json.dumps(scrubbed_data_dict, indent=2))

    # Example with custom rules
    custom_phone_rules = [
        {
            "name": "phone_number_simple",
            "regex": re.compile(r"\b\d{3}-\d{3,4}-\d{4}\b|\b\(\d{3}\)\s*\d{3}-\d{4}\b|\b\d{10}\b"), # Basic US phone
            "replacement": "[REDACTED_PHONE]"
        },
        {
            "name": "ssn_like", # Example, real SSN regex is complex and context-dependent
            "regex": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
            "replacement": "[REDACTED_ID]"
        }
    ]
    
    # Example of a replacement function
    def custom_ip_replacer(match_obj: re.Match) -> str:
        ip_parts = match_obj.group(0).split('.')
        return f"{ip_parts[0]}.{ip_parts[1]}.[MASKED].[MASKED]"

    custom_ip_rule = [
        {
            "name": "ipv4_custom_mask",
            "regex": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"), # Same regex as default IP
            "replacement": custom_ip_replacer # Use the function here
        }
    ]

    # Using custom rules, disabling default email rule, and adding custom IP rule
    # To disable a default rule, one would typically construct the rule list manually
    # or provide an 'enabled_rules_names' list to the scrubber.
    # For this example, let's just add new rules.
    
    all_custom_rules = custom_phone_rules + custom_ip_rule
    # If we wanted to replace the default IP rule, we'd pass only custom_rules and not use_default_rules,
    # or filter DEFAULT_PII_RULES.

    scrubbed_data_custom = scrub_pii_from_dict(test_data_dict, custom_rules=all_custom_rules, use_default_rules=True)
    print("\n--- Scrubbed Dictionary (Default + Custom Phone/SSN + Custom IP Masking) ---")
    print(json.dumps(scrubbed_data_custom, indent=2))
    print("Note: The custom IP rule will apply after the default IP rule if both are active and match.")
    print("For precise control, manage the rule list carefully (e.g., use_default_rules=False and pass a full list).")

    # Example: Only custom rules
    only_custom_scrubbed = scrub_pii_from_dict(
        test_data_dict, 
        custom_rules=custom_phone_rules, 
        use_default_rules=False
    )
    print("\n--- Scrubbed Dictionary (Only Custom Phone Rule) ---")
    print(json.dumps(only_custom_scrubbed, indent=2))
    
    print("\n--- PII Filter Demo Complete ---")
