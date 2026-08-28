# Contributing to loglens

Thanks for taking the time to contribute. This document covers dev setup, the
project's testing conventions, where the code lives, and how a release
happens.

## Dev setup

```bash
git clone https://github.com/nadeem4/loglens.git
cd loglens
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pre-commit install
```

`[dev]` pulls in `loglens[all]` (openai, anthropic, metrics) plus pytest,
ruff, mypy, and pre-commit, so a single install gets you everything CI runs.

## Running the checks locally

These are the same four checks CI runs on every push and PR, plus
pre-commit's own hooks. Run them all before opening a PR:

```bash
ruff check .              # lint -- this covers examples/ too, not just loglens/
ruff format --check .     # formatting
mypy loglens               # type checking -- loglens/ only; examples/ is not type-checked
pytest --cov=loglens --cov-fail-under=80
pre-commit run --all-files
```

CI additionally runs the test suite across Python 3.10-3.13 on Linux, macOS,
and Windows (`.github/workflows/ci.yml`). A change that only works on one OS
or one Python version will fail there even if it passes locally.

## Test-driven development

This project follows **TDD: write a failing test first, then make it pass.**
A PR that adds behavior without a test that would have caught its absence
will be bounced back for a test, not merged with a promise to add one later.
Bug fixes should include a regression test that fails against the old code
and passes against the fix.

`tests/` mirrors `loglens/`'s package structure — e.g. `loglens/handlers/`
behavior is tested in `tests/test_ai_handler.py` and
`tests/test_queue_handler.py`. `tests/conftest.py` has an autouse fixture
that clears `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` and resets the settings
singleton before and after every test — you don't need to do that yourself.

## How routing and providers are structured

`AIHandler` (`loglens/handlers/ai_handler.py`) batches, scrubs, and renders a
prompt, then hands it to an `LLMRouter` (`loglens/router/llm_router.py`),
which picks a "fast" or "capable" provider based on the highest log severity
in the batch and calls `provider.complete(prompt)`. Providers implement the
small `LLMProvider` interface in `loglens/providers/base.py` (one abstract
method: `complete(self, prompt: str) -> str`, raising `ProviderError` on
failure) and lazily import their SDK inside `__init__` so that, e.g.,
`import loglens` never requires `openai` or `anthropic` to be installed.

**To add a new provider:**

1. Add `loglens/providers/<name>_provider.py` with a class implementing
   `LLMProvider`, lazily importing the SDK inside `__init__` and wrapping SDK
   exceptions in `ProviderError` (see `openai_provider.py` /
   `anthropic_provider.py` for the pattern).
2. Wire it into `LLMRouter._build_providers_from_settings()` so
   `LOGLENS_PROVIDER=<name>` selects it.
3. Add an optional dependency group for the SDK in `pyproject.toml`
   (`[project.optional-dependencies]`), and add it to the `all` extra.
4. Add tests in `tests/test_providers.py` and `tests/test_router.py`, and
   extend `loglens/cli/health_check.py`'s provider check + its tests.

## Release process

Releasing is not yet documented — it will be covered in `RELEASING.md`,
which is planned for a later phase. Until that exists, coordinate with a
maintainer before tagging a release.

## Pull requests

- Keep PRs focused; unrelated changes make review slower for everyone.
- Fill out the PR template's checklist, including `CHANGELOG.md`.
- Squash-worthy commit history is appreciated but not required — the merge
  strategy is up to the maintainer.
