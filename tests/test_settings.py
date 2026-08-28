import importlib

import pytest

from loglens.config.settings import get_settings, reset_settings


def test_defaults_load_with_no_env():
    settings = get_settings()
    assert settings.loglens_default_level == "INFO"
    assert settings.loglens_batch_size == 10


def test_batch_size_env_var_honored_after_reset(monkeypatch):
    monkeypatch.setenv("LOGLENS_BATCH_SIZE", "7")
    reset_settings()
    settings = get_settings()
    assert settings.loglens_batch_size == 7


def test_invalid_log_level_raises(monkeypatch):
    monkeypatch.setenv("LOGLENS_DEFAULT_LEVEL", "NOT_A_LEVEL")
    reset_settings()
    with pytest.raises(Exception):
        get_settings()


@pytest.mark.filterwarnings("error::DeprecationWarning")
def test_settings_module_import_raises_no_deprecation_warning():
    import loglens.config.settings as settings_module

    importlib.reload(settings_module)
