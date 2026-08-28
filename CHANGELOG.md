# Changelog
All notable changes to loglens are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/) · Versioning: [SemVer](https://semver.org/)

## [Unreleased]
### Added
- Real OpenAI and Anthropic providers with severity-based fast/capable routing.
- Prometheus metrics (optional `[metrics]` extra) and health-check CLI (`loglens-check`).
- PII scrubbing (default + custom regex rules), Jinja2 prompt templates, async queue logging.
- Documentation: rewritten README, `docs/PRIVACY.md`, `CONTRIBUTING.md`, issue templates, and
  runnable examples (`examples/basic_usage.py`, `examples/fastapi_middleware.py`,
  `examples/custom_pii_rules.py`, `examples/custom_prompt_template.py`).
### Fixed
- Timed-flush deadlock; circuit breaker half-open recovery; non-blocking retries.
- README quickstart no longer silently discards the AI response or races
  `logging.shutdown()` when stdout isn't attached to a terminal; documented that the
  response logs at `INFO` to `loglens.ai_responses` and must be enabled to be seen.
- `examples/basic_usage.py` now enables `loglens.ai_responses` so its own demo actually
  prints the AI's analysis instead of pointing at a silent logger.
- `docs/PRIVACY.md` now documents two scrubbing failure modes: a custom rule with an invalid
  regex is silently dropped (only a `print()`, no log/warning/exception), and data nested
  past `max_depth` (default 10) in `extras` passes through completely unscrubbed.
- Quoted all four `pip install loglens[...]` lines in the README install section so they
  don't fail with `zsh: no matches found` on macOS's default shell.
