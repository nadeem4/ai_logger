# Shared pytest fixtures for the logscribe test suite.
import pytest

from logscribe.config.settings import reset_settings


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reset_settings()
    yield
    reset_settings()
