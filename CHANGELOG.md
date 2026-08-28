# Changelog
All notable changes to loglens are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/) · Versioning: [SemVer](https://semver.org/)

## [Unreleased]
### Added
- Real OpenAI and Anthropic providers with severity-based fast/capable routing.
- Prometheus metrics (optional `[metrics]` extra) and health-check CLI (`loglens-check`).
- PII scrubbing (default + custom regex rules), Jinja2 prompt templates, async queue logging.
### Fixed
- Timed-flush deadlock; circuit breaker half-open recovery; non-blocking retries.
