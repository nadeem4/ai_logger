# Shared pytest fixtures for the ai_logging test suite.
import pytest

from ai_logging.config.settings import reset_settings


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reset_settings()
    yield
    reset_settings()
