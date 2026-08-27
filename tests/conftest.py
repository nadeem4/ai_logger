# Shared pytest fixtures for the ai_logging test suite.
import pytest

from ai_logging.config.settings import reset_settings


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    reset_settings()
    yield
    reset_settings()
