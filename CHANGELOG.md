# Changelog
All notable changes to logscribe are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/) · Versioning: [SemVer](https://semver.org/)

## [Unreleased]
### Changed
- Renamed the package from `loglens` to `logscribe`. PyPI rejected the `loglens`
  registration as too similar to an existing project (`log-lens` v0.7.1, a CLI for
  analyzing Apache/Nginx server logs) -- PyPI's name-similarity guard collapses
  separators, so `loglens` and `log-lens` reduce to the same string. `logscribe` was
  verified clear on every form (`logscribe`, `log-scribe`, `log_scribe`, `log.scribe`,
  `logscribes`, `logscriber`) before adoption. This affects the import path
  (`import logscribe`), the CLI (`logscribe-check`), the `LOGSCRIBE_*` environment
  variable prefix (was `LOGLENS_*`), the Prometheus metric namespace
  (`logscribe_*`, was `loglens_*`), and the default AI-response logger name
  (`logscribe.ai_responses`, was `loglens.ai_responses`). Public class names are
  unchanged.
### Added
- Real OpenAI and Anthropic providers with severity-based fast/capable routing.
- Prometheus metrics (optional `[metrics]` extra) and health-check CLI (`logscribe-check`).
- PII scrubbing (default + custom regex rules), Jinja2 prompt templates, async queue logging.
- Documentation: rewritten README, `docs/PRIVACY.md`, `CONTRIBUTING.md`, issue templates, and
  runnable examples (`examples/basic_usage.py`, `examples/fastapi_middleware.py`,
  `examples/custom_pii_rules.py`, `examples/custom_prompt_template.py`).
### Fixed
- Timed-flush deadlock; circuit breaker half-open recovery; non-blocking retries.
- README quickstart no longer silently discards the AI response or races
  `logging.shutdown()` when stdout isn't attached to a terminal; documented that the
  response logs at `INFO` to `logscribe.ai_responses` and must be enabled to be seen.
- `examples/basic_usage.py` now enables `logscribe.ai_responses` so its own demo actually
  prints the AI's analysis instead of pointing at a silent logger.
- `docs/PRIVACY.md` now documents two scrubbing failure modes: a custom rule with an invalid
  regex is silently dropped (only a `print()`, no log/warning/exception), and data nested
  past `max_depth` (default 10) in `extras` passes through completely unscrubbed.
- Quoted all four `pip install logscribe[...]` lines in the README install section so they
  don't fail with `zsh: no matches found` on macOS's default shell.
