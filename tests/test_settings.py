import importlib

import pytest

from logscribe.config.settings import Settings, get_settings, reset_settings


def test_defaults_load_with_no_env():
    settings = get_settings()
    assert settings.logscribe_default_level == "INFO"
    assert settings.logscribe_batch_size == 10


def test_batch_size_env_var_honored_after_reset(monkeypatch):
    monkeypatch.setenv("LOGSCRIBE_BATCH_SIZE", "7")
    reset_settings()
    settings = get_settings()
    assert settings.logscribe_batch_size == 7


def test_invalid_log_level_raises(monkeypatch):
    monkeypatch.setenv("LOGSCRIBE_DEFAULT_LEVEL", "NOT_A_LEVEL")
    reset_settings()
    with pytest.raises(Exception):
        get_settings()


@pytest.mark.filterwarnings("error::DeprecationWarning")
def test_settings_module_import_raises_no_deprecation_warning():
    import logscribe.config.settings as settings_module

    importlib.reload(settings_module)


def test_non_string_log_level_raises():
    # mode="before" validators see the raw constructor value, so a
    # directly-constructed Settings() (bypassing env-var string coercion)
    # can hand the validator a non-string value.
    with pytest.raises(Exception, match="must be a string"):
        Settings(logscribe_default_level=123)


def test_pii_rules_json_string_is_parsed_into_rule_list():
    settings = Settings(
        logscribe_pii_rules_json='[{"name": "order", "regex": "ORD-\\\\d+", "replacement": "[ORDER]"}]'
    )
    assert settings.logscribe_pii_rules_json == [
        {"name": "order", "regex": "ORD-\\d+", "replacement": "[ORDER]"}
    ]


def test_pii_rules_json_wrong_type_raises():
    with pytest.raises(Exception, match="JSON string or a list of dicts"):
        Settings(logscribe_pii_rules_json=123)
