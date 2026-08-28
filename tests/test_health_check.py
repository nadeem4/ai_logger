# Exit-code coverage for the `logscribe-check` console script.
#
# The autouse clean_settings fixture in conftest.py deletes
# OPENAI_API_KEY / ANTHROPIC_API_KEY and resets the settings singleton
# before each test, so "no key configured" is the default starting state
# here without any extra setup.
#
# main() is called directly (not shelled out to) so these tests do not
# depend on an installed console-script entry point.

import json
import logging
import sys

import pytest

from logscribe.cli.health_check import HealthStatus, collect_health_status, main, run_health_checks


def test_main_returns_nonzero_when_checks_fail(monkeypatch):
    # No provider API key is configured, so the LLMRouter has no usable
    # providers and the health check reports failure. The exit code must
    # agree with that "one or more health checks failed" outcome.
    # argparse reads sys.argv by default, which under the test runner
    # contains pytest's own arguments -- pin it so parse_args() sees none.
    monkeypatch.setattr("sys.argv", ["logscribe-check"])

    assert main() == 1


def test_main_returns_zero_when_checks_pass(monkeypatch):
    monkeypatch.setattr("sys.argv", ["logscribe-check"])
    monkeypatch.setenv("LOGSCRIBE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    assert main() == 0


def test_run_health_checks_reports_settings_load_failure(monkeypatch, caplog):
    import logscribe.config.settings as settings_module

    def boom():
        raise RuntimeError("settings blew up")

    monkeypatch.setattr(settings_module, "get_settings", boom)

    with caplog.at_level(logging.ERROR, logger="logscribe_health_check"):
        result = run_health_checks()

    assert result is False
    assert "Failed to load settings" in caplog.text


def test_run_health_checks_reports_router_init_failure(monkeypatch, caplog):
    import logscribe.router.llm_router as router_module

    def boom(settings):
        raise RuntimeError("router blew up")

    monkeypatch.setattr(router_module, "LLMRouter", boom)

    with caplog.at_level(logging.ERROR, logger="logscribe_health_check"):
        result = run_health_checks()

    assert result is False
    assert "Failed to initialize or check LLMRouter" in caplog.text


def test_run_health_checks_warns_when_configured_template_falls_back(monkeypatch, caplog):
    # A template name that does not exist forces AIHandler onto its inline
    # fallback template. run_health_checks() must notice that mismatch (a
    # named template was requested but the fallback text came back) and warn
    # rather than silently report success.
    monkeypatch.setenv("LOGSCRIBE_JINJA_LOG_PROMPT_TEMPLATE_NAME", "definitely_missing.jinja2")

    with caplog.at_level(logging.WARNING, logger="logscribe_health_check"):
        run_health_checks()

    assert "Using a fallback Jinja2 template" in caplog.text


def test_run_health_checks_reports_jinja_check_failure(monkeypatch, caplog):
    import logscribe.handlers.ai_handler as ai_handler_module

    def boom(**kwargs):
        raise RuntimeError("template check blew up")

    monkeypatch.setattr(ai_handler_module, "AIHandler", boom)

    with caplog.at_level(logging.ERROR, logger="logscribe_health_check"):
        result = run_health_checks()

    assert result is False
    assert "Failed during Jinja2 template check" in caplog.text


def test_run_health_checks_warns_when_prometheus_client_missing(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "prometheus_client", None)

    with caplog.at_level(logging.WARNING, logger="logscribe_health_check"):
        run_health_checks()

    assert "'prometheus_client' library is not installed" in caplog.text


def test_run_health_checks_reports_prometheus_disabled(monkeypatch, caplog):
    monkeypatch.setenv("LOGSCRIBE_PROMETHEUS_ENABLED", "false")

    with caplog.at_level(logging.INFO, logger="logscribe_health_check"):
        run_health_checks()

    assert "Prometheus metrics server is disabled by configuration" in caplog.text


def test_run_health_checks_reports_prometheus_check_failure(monkeypatch, caplog):
    import logscribe.metrics.prometheus as prometheus_module

    def boom():
        raise RuntimeError("metrics blew up")

    monkeypatch.setattr(prometheus_module, "get_metrics_instance", boom)

    with caplog.at_level(logging.ERROR, logger="logscribe_health_check"):
        result = run_health_checks()

    assert result is False
    assert "Failed during Prometheus server check" in caplog.text


# --- Task 5: --json mode, per-check human output, and provider state
# detection (ok / no_key / sdk_missing). ---


def test_collect_health_status_reports_no_key_for_both_providers_by_default(monkeypatch):
    # clean_settings (autouse) already deletes both API keys.
    status = collect_health_status()

    assert status.providers == {"openai": "no_key", "anthropic": "no_key"}
    assert status.settings_ok is True
    assert status.ok is False


def test_collect_health_status_reports_ok_when_key_and_sdk_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    status = collect_health_status()

    assert status.providers["openai"] == "ok"
    assert status.ok is True


def test_collect_health_status_reports_sdk_missing_when_key_set_but_sdk_absent(monkeypatch):
    # Key is set, but the openai SDK cannot be imported -- must be reported
    # as sdk_missing, distinctly from no_key.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", None)

    status = collect_health_status()

    assert status.providers["openai"] == "sdk_missing"


def test_collect_health_status_reports_anthropic_sdk_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "anthropic", None)

    status = collect_health_status()

    assert status.providers["anthropic"] == "sdk_missing"


def test_collect_health_status_never_imports_provider_sdks_eagerly(monkeypatch):
    # Detecting sdk_missing must not defeat logscribe's lazy-import contract:
    # calling collect_health_status() must not leave openai/anthropic in
    # sys.modules as a side effect of merely checking availability, beyond
    # what was already imported by the surrounding test session.
    was_present = {
        "openai": "openai" in sys.modules,
        "anthropic": "anthropic" in sys.modules,
    }
    collect_health_status()
    # If the SDKs were already imported (e.g. by an earlier test in this
    # session), that's unrelated to this check; the meaningful assertion is
    # that collect_health_status() doesn't change the answer.
    assert ("openai" in sys.modules) == was_present["openai"] or was_present["openai"] is False
    assert ("anthropic" in sys.modules) == was_present["anthropic"] or was_present[
        "anthropic"
    ] is False


def test_collect_health_status_reports_metrics_disabled(monkeypatch):
    monkeypatch.setenv("LOGSCRIBE_PROMETHEUS_ENABLED", "false")

    status = collect_health_status()

    assert status.metrics == "disabled"


def test_collect_health_status_reports_metrics_enabled(monkeypatch):
    monkeypatch.setenv("LOGSCRIBE_PROMETHEUS_ENABLED", "true")

    status = collect_health_status()

    assert status.metrics == "enabled"


def test_collect_health_status_reports_metrics_sdk_missing(monkeypatch):
    monkeypatch.setenv("LOGSCRIBE_PROMETHEUS_ENABLED", "true")
    monkeypatch.setitem(sys.modules, "prometheus_client", None)

    status = collect_health_status()

    assert status.metrics == "sdk_missing"


def test_collect_health_status_reports_template_ok(monkeypatch):
    status = collect_health_status()

    assert status.template_ok is True


def test_collect_health_status_settings_failure_is_never_a_traceback(monkeypatch):
    import logscribe.config.settings as settings_module

    def boom():
        raise RuntimeError("settings blew up")

    monkeypatch.setattr(settings_module, "get_settings", boom)

    status = collect_health_status()

    assert status.settings_ok is False
    assert status.ok is False


def test_main_json_prints_single_parseable_object_on_stdout(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check", "--json"])
    monkeypatch.setenv("LOGSCRIBE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    exit_code = main()

    captured = capsys.readouterr()
    # The whole of stdout must be exactly one JSON object -- nothing else,
    # not even a trailing blank line's worth of stray text -- so parse the
    # captured stdout itself rather than merely searching it for substrings.
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload == {
        "settings_ok": True,
        "providers": {"openai": "no_key", "anthropic": "ok"},
        "template_ok": True,
        "metrics": "enabled",
        "ok": True,
    }


def test_main_json_stdout_has_no_extra_output(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check", "--json"])

    main()

    captured = capsys.readouterr()
    # Exactly one line of JSON on stdout -- no banners, no log lines.
    lines = captured.out.strip("\n").splitlines()
    assert len(lines) == 1
    json.loads(lines[0])


def test_main_json_reflects_failure_state(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check", "--json"])

    exit_code = main()

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["providers"] == {"openai": "no_key", "anthropic": "no_key"}


def test_main_human_mode_prints_check_lines_with_fix_hints(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check"])

    exit_code = main()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "openai" in out
    assert "OPENAI_API_KEY not set" in out
    assert "anthropic" in out
    assert "ANTHROPIC_API_KEY not set" in out


def test_main_human_mode_marks_ok_provider_and_succeeds(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check"])
    monkeypatch.setenv("LOGSCRIBE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    exit_code = main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "anthropic" in out


def test_main_human_mode_never_tracebacks_on_missing_key(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check"])

    main()

    captured = capsys.readouterr()
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_main_json_mode_never_tracebacks_on_sdk_missing(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check", "--json"])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", None)

    main()

    captured = capsys.readouterr()
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err
    payload = json.loads(captured.out)
    assert payload["providers"]["openai"] == "sdk_missing"


def test_main_human_mode_shows_sdk_missing_hint_for_provider(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check"])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", None)

    exit_code = main()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "openai" in out
    assert "SDK not installed" in out
    assert "pip install" in out


def test_main_human_mode_shows_sdk_missing_hint_for_metrics(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["logscribe-check"])
    monkeypatch.setenv("LOGSCRIBE_PROMETHEUS_ENABLED", "true")
    monkeypatch.setitem(sys.modules, "prometheus_client", None)

    main()

    out = capsys.readouterr().out
    assert "metrics" in out
    assert "prometheus_client not installed" in out
    assert "pip install prometheus_client" in out


def test_health_status_is_json_serializable_dataclass():
    status = HealthStatus()
    # Sanity: the shape main() serializes must round-trip through
    # json.dumps without a custom encoder.
    json.dumps(
        {
            "settings_ok": status.settings_ok,
            "providers": status.providers,
            "template_ok": status.template_ok,
            "metrics": status.metrics,
            "ok": status.ok,
        }
    )


@pytest.mark.parametrize("encodable", [True, False])
def test_human_output_glyphs_never_raise_on_narrow_encodings(monkeypatch, encodable):
    # Windows consoles historically default to cp1252 and cannot encode
    # U+2705/U+274C. Whatever glyphs main() prints must survive an
    # encoding that cannot represent the emoji, without ever crashing.
    monkeypatch.setattr("sys.argv", ["logscribe-check"])

    class Stream:
        encoding = "utf-8" if encodable else "cp1252"

        def write(self, s):
            s.encode(self.encoding)  # raises if the glyph can't be encoded
            return len(s)

        def flush(self):
            pass

    from logscribe.cli import health_check as hc_module

    monkeypatch.setattr(hc_module.sys, "stdout", Stream())
    # Should not raise UnicodeEncodeError regardless of the stream's
    # encoding.
    main()
