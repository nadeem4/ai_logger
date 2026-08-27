def test_module_imports():
    from ai_logging.utils import pii_filter  # currently raises NameError: Optional
    assert hasattr(pii_filter, "scrub_pii_from_dict")

def test_scrubs_email():
    from ai_logging.utils.pii_filter import scrub_pii_from_dict
    out = scrub_pii_from_dict({"msg": "contact alice@example.com now"})
    assert out["msg"] == "contact [REDACTED_EMAIL] now"
