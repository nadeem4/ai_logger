# Exit-code coverage for the `loglens-check` console script.
#
# The autouse clean_settings fixture in conftest.py deletes
# OPENAI_API_KEY / ANTHROPIC_API_KEY and resets the settings singleton
# before each test, so "no key configured" is the default starting state
# here without any extra setup.
#
# main() is called directly (not shelled out to) so these tests do not
# depend on an installed console-script entry point.

import logging
import sys

from loglens.cli.health_check import main, run_health_checks


def test_main_returns_nonzero_when_checks_fail(monkeypatch):
    # No provider API key is configured, so the LLMRouter has no usable
    # providers and the health check reports failure. The exit code must
    # agree with that "one or more health checks failed" outcome.
    # argparse reads sys.argv by default, which under the test runner
    # contains pytest's own arguments -- pin it so parse_args() sees none.
    monkeypatch.setattr("sys.argv", ["loglens-check"])

    assert main() == 1


def test_main_returns_zero_when_checks_pass(monkeypatch):
    monkeypatch.setattr("sys.argv", ["loglens-check"])
    monkeypatch.setenv("LOGLENS_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    assert main() == 0


def test_run_health_checks_reports_settings_load_failure(monkeypatch, caplog):
    import loglens.config.settings as settings_module

    def boom():
        raise RuntimeError("settings blew up")

    monkeypatch.setattr(settings_module, "get_settings", boom)

    with caplog.at_level(logging.ERROR, logger="loglens_health_check"):
        result = run_health_checks()

    assert result is False
    assert "Failed to load settings" in caplog.text


def test_run_health_checks_reports_router_init_failure(monkeypatch, caplog):
    import loglens.router.llm_router as router_module

    def boom(settings):
        raise RuntimeError("router blew up")

    monkeypatch.setattr(router_module, "LLMRouter", boom)

    with caplog.at_level(logging.ERROR, logger="loglens_health_check"):
        result = run_health_checks()

    assert result is False
    assert "Failed to initialize or check LLMRouter" in caplog.text


def test_run_health_checks_warns_when_configured_template_falls_back(monkeypatch, caplog):
    # A template name that does not exist forces AIHandler onto its inline
    # fallback template. run_health_checks() must notice that mismatch (a
    # named template was requested but the fallback text came back) and warn
    # rather than silently report success.
    monkeypatch.setenv("LOGLENS_JINJA_LOG_PROMPT_TEMPLATE_NAME", "definitely_missing.jinja2")

    with caplog.at_level(logging.WARNING, logger="loglens_health_check"):
        run_health_checks()

    assert "Using a fallback Jinja2 template" in caplog.text


def test_run_health_checks_reports_jinja_check_failure(monkeypatch, caplog):
    import loglens.handlers.ai_handler as ai_handler_module

    def boom(**kwargs):
        raise RuntimeError("template check blew up")

    monkeypatch.setattr(ai_handler_module, "AIHandler", boom)

    with caplog.at_level(logging.ERROR, logger="loglens_health_check"):
        result = run_health_checks()

    assert result is False
    assert "Failed during Jinja2 template check" in caplog.text


def test_run_health_checks_warns_when_prometheus_client_missing(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "prometheus_client", None)

    with caplog.at_level(logging.WARNING, logger="loglens_health_check"):
        run_health_checks()

    assert "'prometheus_client' library is not installed" in caplog.text


def test_run_health_checks_reports_prometheus_disabled(monkeypatch, caplog):
    monkeypatch.setenv("LOGLENS_PROMETHEUS_ENABLED", "false")

    with caplog.at_level(logging.INFO, logger="loglens_health_check"):
        run_health_checks()

    assert "Prometheus metrics server is disabled by configuration" in caplog.text


def test_run_health_checks_reports_prometheus_check_failure(monkeypatch, caplog):
    import loglens.metrics.prometheus as prometheus_module

    def boom():
        raise RuntimeError("metrics blew up")

    monkeypatch.setattr(prometheus_module, "get_metrics_instance", boom)

    with caplog.at_level(logging.ERROR, logger="loglens_health_check"):
        result = run_health_checks()

    assert result is False
    assert "Failed during Prometheus server check" in caplog.text
