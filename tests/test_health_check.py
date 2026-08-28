# Exit-code coverage for the `loglens-check` console script.
#
# The autouse clean_settings fixture in conftest.py deletes
# OPENAI_API_KEY / ANTHROPIC_API_KEY and resets the settings singleton
# before each test, so "no key configured" is the default starting state
# here without any extra setup.
#
# main() is called directly (not shelled out to) so these tests do not
# depend on an installed console-script entry point.

from loglens.cli.health_check import main


def test_main_returns_nonzero_when_checks_fail(monkeypatch):
    # No provider API key is configured, so the LLMRouter has no usable
    # providers and the health check reports failure. The exit code must
    # agree with that "one or more health checks failed" outcome.
    # argparse reads sys.argv by default, which under the test runner
    # contains pytest's own arguments -- pin it so parse_args() sees none.
    monkeypatch.setattr("sys.argv", ["loglens-check"])

    assert main() != 0


def test_main_returns_zero_when_checks_pass(monkeypatch):
    monkeypatch.setattr("sys.argv", ["loglens-check"])
    monkeypatch.setenv("LOGLENS_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    assert main() == 0
