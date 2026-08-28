import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from typing import TextIO

# It's good practice for CLI tools not to configure the root logger directly
# unless explicitly intended. Applications using the library might have their own setup.
# However, for a health check, some minimal output is needed.
cli_logger = logging.getLogger("logscribe_health_check")
handler = logging.StreamHandler()  # defaults to sys.stderr -- keeps stdout clean for --json
formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
handler.setFormatter(formatter)
cli_logger.addHandler(handler)
cli_logger.setLevel(logging.INFO)  # Default level for health check output

# Adjust logscribe package loggers if too verbose during health check
logging.getLogger("logscribe").setLevel(logging.WARNING)


@dataclass
class HealthStatus:
    """Structured per-check health state, consumed by both the --json
    output and the human ✅/❌ summary. Field names and provider/metrics
    string values match the documented `logscribe-check --json` contract
    exactly -- this dataclass IS that contract."""

    settings_ok: bool = False
    providers: dict[str, str] = field(
        default_factory=lambda: {"openai": "no_key", "anthropic": "no_key"}
    )
    template_ok: bool = False
    # "disabled" is the safe default: it's what's true whenever we haven't
    # been able to determine otherwise (e.g. settings failed to load before
    # we could check), and it matches what a config with metrics turned off
    # would report -- neither state claims something we don't know.
    metrics: str = "disabled"
    ok: bool = False


def _check_provider_state(provider_name: str, api_key: str | None) -> str:
    """Returns 'no_key', 'sdk_missing', or 'ok' for a single provider.

    A missing key is reported before SDK availability is even checked --
    "no_key" is the fix a user should make first regardless of what else is
    wrong, and it's the one case we can tell apart from "ok" without ever
    touching the optional SDK.

    SDK importability is probed by actually constructing the provider
    (which does its own lazy `import openai` / `import anthropic` inside
    __init__ and raises ProviderError if the SDK isn't installed) rather
    than duplicating an `import openai` here -- this reuses the exact
    lazy-import path production code already takes, and constructing the
    SDK's client object makes no network call.
    """
    if not api_key:
        return "no_key"

    from ..providers.base import ProviderError

    try:
        if provider_name == "openai":
            from ..providers.openai_provider import OpenAIProvider

            OpenAIProvider(model="gpt-4o-mini", api_key=api_key)
        else:
            from ..providers.anthropic_provider import AnthropicProvider

            AnthropicProvider(model="claude-3-5-haiku-latest", api_key=api_key)
    except ProviderError:
        return "sdk_missing"
    return "ok"


def run_health_checks(status: HealthStatus | None = None) -> bool:
    """
    Performs a series of health checks on the logscribe package configuration and components.

    If `status` is given, the fine-grained per-check state (settings_ok,
    providers, template_ok, metrics) is recorded onto it as a side effect --
    this is how collect_health_status() gets its structured result out of
    the same checks this function already performs, without running every
    check twice.
    """
    if status is None:
        status = HealthStatus()

    cli_logger.info("Starting LogScribe Package Health Check...")
    all_checks_ok = True

    # 1. Load Settings
    cli_logger.info("\n--- Checking Configuration Settings ---")
    try:
        from logscribe.config.settings import get_settings

        settings = get_settings()
        status.settings_ok = True
        cli_logger.info("Successfully loaded settings.")
        # Print a few key settings for verification
        cli_logger.info(f"  Default Log Level: {settings.logscribe_default_level}")
        cli_logger.info(f"  Batch Size: {settings.logscribe_batch_size}")
        cli_logger.info(f"  Provider: {settings.logscribe_provider}")
        cli_logger.info(f"  Fast Model: {settings.logscribe_fast_model}")
        cli_logger.info(f"  Capable Model: {settings.logscribe_capable_model}")
        cli_logger.info(
            f"  Capable Severity Threshold: {settings.logscribe_capable_severity_threshold}"
        )
        cli_logger.info(f"  OpenAI API Key Set: {'Yes' if settings.openai_api_key else 'No'}")
        cli_logger.info(f"  Anthropic API Key Set: {'Yes' if settings.anthropic_api_key else 'No'}")
        cli_logger.info(f"  Prometheus Enabled: {settings.logscribe_prometheus_enabled}")
        if settings.logscribe_prometheus_enabled:
            cli_logger.info(f"  Prometheus Port: {settings.logscribe_prometheus_port}")

    except Exception as e:
        cli_logger.error(f"Failed to load settings: {e}")
        all_checks_ok = False
        status.settings_ok = False
        status.ok = False
        # Cannot proceed with most other checks if settings fail
        cli_logger.info("\nHealth Check Result: FAILED (Settings could not be loaded)")
        return False

    # Independently record per-provider state (ok/no_key/sdk_missing) for
    # BOTH providers, regardless of which one settings.logscribe_provider
    # selects -- this is diagnostic info the LLMRouter check below does not
    # surface on its own, since the router only builds the configured
    # provider.
    status.providers["openai"] = _check_provider_state("openai", settings.openai_api_key)
    status.providers["anthropic"] = _check_provider_state("anthropic", settings.anthropic_api_key)

    # 2. Check LLM Router and Model Availability
    cli_logger.info("\n--- Checking LLM Router & Models ---")
    try:
        from logscribe.router.llm_router import LLMRouter

        # Mute internal LLMRouter info logs for cleaner health check output
        logging.getLogger("logscribe.router.llm_router").setLevel(logging.WARNING)

        router = LLMRouter(settings=settings)
        cli_logger.info("LLMRouter initialized.")

        cli_logger.info(f"  Configured provider: {settings.logscribe_provider}")
        cli_logger.info(f"  Fast model: {settings.logscribe_fast_model}")
        cli_logger.info(f"  Capable model: {settings.logscribe_capable_model}")
        cli_logger.info(
            f"  Capable severity threshold: {settings.logscribe_capable_severity_threshold}"
        )

        if router.fast is not None or router.capable is not None:
            cli_logger.info("  LLM providers are configured and available.")
        else:
            key_name = (
                "ANTHROPIC_API_KEY"
                if settings.logscribe_provider == "anthropic"
                else "OPENAI_API_KEY"
            )
            cli_logger.warning(
                f"  No LLM providers were initialized in the LLMRouter ({key_name} not set). "
                "AI functionality will be limited."
            )
            all_checks_ok = False  # Depending on strictness, this could be a failure

    except Exception as e:
        cli_logger.error(f"Failed to initialize or check LLMRouter: {e}")
        all_checks_ok = False

    # 3. Check Jinja2 Template Loading
    cli_logger.info("\n--- Checking Jinja2 Template ---")
    try:
        import jinja2

        from logscribe.handlers.ai_handler import AIHandler  # To access its template loading logic

        # Temporarily set AIHandler's logger to WARNING to avoid its info logs here
        logging.getLogger("logscribe.handlers.ai_handler").setLevel(logging.WARNING)

        # We need an AIHandler instance to check its template
        # This is a bit indirect but tests the same logic AIHandler uses.
        temp_ai_handler = AIHandler(settings=settings)  # Uses placeholder LLMs by default

        if isinstance(temp_ai_handler.jinja_template, jinja2.Template):
            status.template_ok = True
            cli_logger.info("Successfully loaded/created Jinja2 template for AI prompts.")
            # Check if it's the fallback or a loaded one
            if "Log Batch Summary" in temp_ai_handler.jinja_template.render(
                logs=[]
            ):  # Crude check for fallback
                if (
                    settings.logscribe_jinja_template_dir
                    or settings.logscribe_jinja_log_prompt_template_name
                    != "default_log_prompt.jinja2"
                ):
                    cli_logger.warning(
                        f"  Using a fallback Jinja2 template. Specified template '{settings.logscribe_jinja_log_prompt_template_name}' might be missing or invalid."
                    )
                else:
                    cli_logger.info("  Using the default built-in Jinja2 template.")
            else:
                cli_logger.info(
                    f"  Successfully loaded custom/packaged Jinja2 template: {settings.logscribe_jinja_log_prompt_template_name}"
                )
        else:
            cli_logger.error(
                "Jinja2 template object in AIHandler is not a valid Jinja2.Template instance."
            )
            all_checks_ok = False
        temp_ai_handler.close()  # Clean up timer
    except Exception as e:
        cli_logger.error(f"Failed during Jinja2 template check: {e}")
        all_checks_ok = False

    # 4. Check Prometheus Metrics Server (if enabled)
    cli_logger.info("\n--- Checking Prometheus Metrics Server ---")
    if settings.logscribe_prometheus_enabled:
        try:
            from logscribe.metrics.prometheus import get_metrics_instance

            # Mute prometheus module's info logs for cleaner output
            logging.getLogger("logscribe.metrics.prometheus").setLevel(logging.WARNING)

            # Check if prometheus_client is installed
            import prometheus_client  # type: ignore

            cli_logger.info("  prometheus_client library is installed.")
            status.metrics = "enabled"

            # Test starting the server (it won't start if already started or port conflict)
            # This is a basic check; a real test would try to scrape metrics.
            # For CLI, we just check if the start function runs without immediate error.
            # The function itself logs if it starts or encounters issues.
            # We don't want to actually *keep* it running from a health check CLI.
            # This is more of a "can it attempt to start" check.
            # A better check might be to try to bind to the port.

            # For now, just initialize metrics instance to see if it loads.
            metrics_instance = get_metrics_instance()
            if metrics_instance:
                cli_logger.info("  Prometheus metrics module initialized.")
                if any(
                    not isinstance(m, prometheus_client.metrics.MetricWrapperBase)
                    for m in vars(metrics_instance).values()
                    if hasattr(m, "_type")
                ):  # Check if real metrics
                    cli_logger.warning(
                        "  Prometheus metrics are using placeholders. Ensure 'prometheus_client' is installed and no init errors occurred."
                    )

            cli_logger.info(
                f"  Prometheus is configured to run on port {settings.logscribe_prometheus_port}."
            )
            cli_logger.info(
                "  Note: This check does not guarantee the server can start (e.g., port might be in use)."
            )

        except ImportError:
            cli_logger.warning(
                "  'prometheus_client' library is not installed, but Prometheus is enabled. Metrics will not be exposed."
            )
            status.metrics = "sdk_missing"
            # all_checks_ok = False # Depending on strictness
        except Exception as e:
            cli_logger.error(f"Failed during Prometheus server check: {e}")
            all_checks_ok = False
    else:
        cli_logger.info("  Prometheus metrics server is disabled by configuration.")
        status.metrics = "disabled"

    # Final Result
    cli_logger.info("\n--- Health Check Summary ---")
    if all_checks_ok:
        cli_logger.info(
            "All essential checks passed. LogScribe package appears to be configured correctly."
        )
        cli_logger.info(
            "Note: Functional tests (e.g., actual AI calls) are not part of this health check."
        )
    else:
        cli_logger.warning(
            "One or more health checks failed. Please review the output above for details."
        )

    status.ok = all_checks_ok
    return all_checks_ok


def collect_health_status() -> HealthStatus:
    """Runs the health checks and returns the structured HealthStatus that
    backs both --json output and the human ✅/❌ summary. This is the
    single entry point that performs the checks exactly once; run_health_checks()
    (kept for backward compatibility with its existing bool-returning
    callers/tests) is a thin function that also fills in the same status
    object when one is passed to it."""
    status = HealthStatus()
    run_health_checks(status)
    return status


# --- Human-readable ✅/❌ summary -------------------------------------------

_PIP_HINTS = {
    "openai": "pip install 'openai>=1'",
    "anthropic": "pip install anthropic",
}
_KEY_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _pick_glyphs(stream: TextIO) -> tuple[str, str]:
    """Returns (ok_glyph, fail_glyph). Windows consoles historically default
    to a narrow codepage (cp1252) that cannot encode U+2705/U+274C -- if the
    target stream's encoding can't represent them, fall back to a plain
    ASCII marker instead of crashing with UnicodeEncodeError."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        "✅❌".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return "[OK]", "[FAIL]"
    return "✅", "❌"


def _provider_lines(status: HealthStatus, ok_glyph: str, fail_glyph: str) -> list[str]:
    lines = []
    for name in ("openai", "anthropic"):
        state = status.providers.get(name, "no_key")
        if state == "ok":
            lines.append(f"{ok_glyph} {name}: ready")
        elif state == "no_key":
            lines.append(f"{fail_glyph} {name}: {_KEY_ENV_VARS[name]} not set")
        else:  # sdk_missing
            lines.append(f"{fail_glyph} {name}: SDK not installed -- {_PIP_HINTS[name]}")
    return lines


def print_human_report(status: HealthStatus, stream: TextIO | None = None) -> None:
    """Prints one ✅/❌ line per check, with a fix hint on failure."""
    target = stream if stream is not None else sys.stdout
    ok_glyph, fail_glyph = _pick_glyphs(target)

    lines = [
        f"{ok_glyph if status.settings_ok else fail_glyph} settings: "
        + ("loaded" if status.settings_ok else "failed to load -- see log output above"),
        *_provider_lines(status, ok_glyph, fail_glyph),
        f"{ok_glyph if status.template_ok else fail_glyph} template: "
        + ("loaded" if status.template_ok else "failed to load -- see log output above"),
    ]

    if status.metrics == "enabled":
        lines.append(f"{ok_glyph} metrics: enabled (prometheus_client)")
    elif status.metrics == "disabled":
        lines.append(f"{ok_glyph} metrics: disabled by configuration")
    else:  # sdk_missing
        lines.append(
            f"{fail_glyph} metrics: prometheus_client not installed -- pip install prometheus_client"
        )

    lines.append(
        f"{ok_glyph if status.ok else fail_glyph} overall: "
        + ("healthy" if status.ok else "unhealthy")
    )

    for line in lines:
        print(line, file=target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Health check for the LogScribe package.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON to stdout instead of the human-readable report.",
    )
    args = parser.parse_args()

    if args.json:
        # Keep the diagnostic log dump (already routed to stderr) quiet so
        # stdout stays exactly one JSON object and nothing else. Restore
        # the previous level afterwards -- cli_logger is a module-level
        # singleton, so leaving it raised would silently mute human-mode
        # runs later in the same process.
        previous_level = cli_logger.level
        cli_logger.setLevel(logging.CRITICAL + 1)
        try:
            status = collect_health_status()
        finally:
            cli_logger.setLevel(previous_level)
        print(json.dumps(asdict(status)))
    else:
        status = collect_health_status()
        print_human_report(status)

    return 0 if status.ok else 1


if __name__ == "__main__":
    sys.exit(main())
