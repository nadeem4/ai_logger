"""Smoke tests for everything under examples/.

Every example in examples/ is linted by CI (`ruff check .` runs over the
whole repo), so these tests exist to catch the next class of bug ruff
can't: examples that reference env vars or APIs that don't actually exist,
or that crash instead of behaving as documented.

examples/fastapi_middleware.py is deliberately excluded from every test
below except the blanket py_compile check: fastapi/uvicorn are not a
loglens dependency in any extra, so importing it would fail in every CI
environment. Its header comment carries the install/run commands instead;
its runtime correctness is unverified here by design (see the module
docstring).

The other three examples are genuinely imported and, where safe, have
their main()/demo functions executed -- each one constructs AIHandler
with a short flush_interval and closes it in a finally block, so no
example run here leaks a background thread or hangs the suite.
"""

import importlib.util
import json
import logging
import py_compile
import tempfile
import types
from pathlib import Path

import jinja2
import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

ALL_EXAMPLE_FILES = sorted(EXAMPLES_DIR.rglob("*.py"))


def _load_example(name: str) -> types.ModuleType:
    """Executes examples/<name>.py as a fresh module, the way `python
    examples/<name>.py` would import it -- module-level code runs, but
    each example's demo/main logic lives behind an `if __name__ ==
    "__main__":` guard (or a `main()`/`demo_*()` function the test calls
    explicitly), so importing alone never starts a background thread."""
    path = EXAMPLES_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"loglens_examples_under_test.{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Every example file must at least compile cleanly -----------------


@pytest.mark.parametrize(
    "example_path",
    ALL_EXAMPLE_FILES,
    ids=[p.relative_to(EXAMPLES_DIR).as_posix() for p in ALL_EXAMPLE_FILES],
)
def test_example_compiles(example_path):
    with tempfile.TemporaryDirectory() as tmp_dir:
        cfile = str(Path(tmp_dir) / "compiled.pyc")
        py_compile.compile(str(example_path), cfile=cfile, doraise=True)


def test_found_expected_example_files():
    # Guards against a typo silently dropping a file out of the
    # parametrized compile check above.
    names = {p.relative_to(EXAMPLES_DIR).as_posix() for p in ALL_EXAMPLE_FILES}
    assert names == {
        "basic_usage.py",
        "fastapi_middleware.py",
        "custom_pii_rules.py",
        "custom_prompt_template.py",
    }


# --- fastapi_middleware.py: py_compile only, plus its documented commands --


def test_fastapi_middleware_documents_install_and_run_commands():
    text = (EXAMPLES_DIR / "fastapi_middleware.py").read_text(encoding="utf-8")
    assert 'pip install "loglens[openai]" fastapi uvicorn' in text
    assert "uvicorn examples.fastapi_middleware:app" in text


# --- basic_usage.py -----------------------------------------------------


def test_basic_usage_exits_1_without_api_key(capsys):
    # The autouse clean_settings fixture (conftest.py) has already deleted
    # OPENAI_API_KEY / ANTHROPIC_API_KEY for this test.
    module = _load_example("basic_usage")

    exit_code = module.main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "OPENAI_API_KEY" in captured.err
    assert "ANTHROPIC_API_KEY" in captured.err
    assert captured.out == ""  # no partial demo output, no traceback


def test_basic_usage_runs_end_to_end_with_a_fake_provider(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LOGLENS_FLUSH_INTERVAL_SECONDS", "0.2")

    calls = []

    def fake_route_prompt(self, prompt, records):
        calls.append((prompt, records))
        return "fake AI analysis"

    monkeypatch.setattr("loglens.router.llm_router.LLMRouter.route_prompt", fake_route_prompt)

    # AIHandler's default response callback lazily adds a plain
    # logging.StreamHandler() to 'loglens.ai_responses' the first time it's
    # used, and only if that logger has no handler yet -- it binds
    # `stream=sys.stderr` at construction time and never rebinds. If some
    # earlier test in the suite already triggered that (this is a
    # process-wide logger, not per-test state), the handler here would be
    # holding a stale, already-restored sys.stderr instead of this test's
    # capsys-patched one, and the assertion below would see nothing.
    # Clearing handlers first forces a fresh one bound to *this* test's
    # capsys stderr, regardless of what ran before it.
    ai_response_logger = logging.getLogger("loglens.ai_responses")
    ai_response_logger.handlers.clear()

    module = _load_example("basic_usage")
    exit_code = module.main()

    assert exit_code == 0
    assert calls, "expected the (faked) LLM to be called at least once"
    captured = capsys.readouterr()
    assert "Done." in captured.out
    # The whole point of this example is to show the AI's response, not just
    # print a closing message -- assert the fake response text actually
    # reached the user. AIHandler's default response logger uses a plain
    # logging.StreamHandler(), which defaults to stderr, so it's
    # captured.err rather than captured.out.
    assert "fake AI analysis" in captured.err


# --- custom_pii_rules.py -------------------------------------------------


def test_custom_pii_rules_scrubs_order_id_both_ways(monkeypatch):
    calls = []

    def fake_route_prompt(self, prompt, records):
        calls.append(prompt)
        return None

    monkeypatch.setattr("loglens.router.llm_router.LLMRouter.route_prompt", fake_route_prompt)

    module = _load_example("custom_pii_rules")
    module.main()

    # One call from demo_env_var_rules(), one from demo_pii_scrubber_callable().
    assert len(calls) == 2
    for prompt in calls:
        assert "ORD-" not in prompt
        assert "[REDACTED_ORDER_ID]" in prompt


# --- custom_prompt_template.py -------------------------------------------


def test_incident_prompt_template_parses_and_has_required_sections():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(EXAMPLES_DIR / "templates")))
    template = env.get_template("incident_prompt.jinja2")
    rendered = template.render(logs=[{"timestamp": "t", "levelname": "ERROR", "message": "m"}])

    assert "SEVERITY:" in rendered
    assert "ROOT CAUSE:" in rendered
    assert "SUGGESTED ACTION:" in rendered


def test_custom_prompt_template_loads_and_renders_incident_template(monkeypatch, capsys):
    calls = []

    def fake_route_prompt(self, prompt, records):
        calls.append(prompt)
        return None

    monkeypatch.setattr("loglens.router.llm_router.LLMRouter.route_prompt", fake_route_prompt)

    module = _load_example("custom_prompt_template")
    module.main()

    captured = capsys.readouterr()
    assert "AIHandler loaded template: incident_prompt.jinja2" in captured.out
    assert len(calls) == 1
    assert "SEVERITY:" in calls[0]
    assert "ROOT CAUSE:" in calls[0]
    assert "SUGGESTED ACTION:" in calls[0]


# --- LOGLENS_PII_RULES_JSON is a real setting, sanity-checked directly --


def test_loglens_pii_rules_json_env_var_is_a_real_setting(monkeypatch):
    from loglens.config.settings import get_settings, reset_settings

    monkeypatch.setenv(
        "LOGLENS_PII_RULES_JSON",
        json.dumps([{"name": "x", "regex": "x", "replacement": "y"}]),
    )
    reset_settings()
    try:
        settings = get_settings()
        assert settings.loglens_pii_rules_json == [{"name": "x", "regex": "x", "replacement": "y"}]
    finally:
        reset_settings()
