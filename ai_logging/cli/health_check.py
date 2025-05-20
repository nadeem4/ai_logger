import logging
import argparse

# It's good practice for CLI tools not to configure the root logger directly
# unless explicitly intended. Applications using the library might have their own setup.
# However, for a health check, some minimal output is needed.
cli_logger = logging.getLogger("ai_logging_health_check")
handler = logging.StreamHandler()
formatter = logging.Formatter('[%(levelname)s] %(name)s: %(message)s')
handler.setFormatter(formatter)
cli_logger.addHandler(handler)
cli_logger.setLevel(logging.INFO) # Default level for health check output

# Adjust ai_logging package loggers if too verbose during health check
logging.getLogger("ai_logging").setLevel(logging.WARNING)


def run_health_checks():
    """
    Performs a series of health checks on the ai_logging package configuration and components.
    """
    cli_logger.info("Starting AI Logging Package Health Check...")
    all_checks_ok = True

    # 1. Load Settings
    cli_logger.info("\n--- Checking Configuration Settings ---")
    try:
        from ai_logging.config.settings import get_settings, Settings
        settings = get_settings()
        cli_logger.info("Successfully loaded settings.")
        # Print a few key settings for verification
        cli_logger.info(f"  Default Log Level: {settings.ai_logging_default_level}")
        cli_logger.info(f"  Batch Size: {settings.ai_logging_batch_size}")
        cli_logger.info(f"  OpenAI API Key Set: {'Yes' if settings.openai_api_key else 'No'}")
        cli_logger.info(f"  Enable Local Model: {settings.ai_logging_enable_local_model}")
        if settings.ai_logging_enable_local_model:
            cli_logger.info(f"  Local Model Name/Path: {settings.ai_logging_local_model_name_or_path}")
        cli_logger.info(f"  Prometheus Enabled: {settings.ai_logging_prometheus_enabled}")
        if settings.ai_logging_prometheus_enabled:
            cli_logger.info(f"  Prometheus Port: {settings.ai_logging_prometheus_port}")

    except Exception as e:
        cli_logger.error(f"Failed to load settings: {e}")
        all_checks_ok = False
        # Cannot proceed with most other checks if settings fail
        cli_logger.info("\nHealth Check Result: FAILED (Settings could not be loaded)")
        return False

    # 2. Check LLM Router and Model Availability
    cli_logger.info("\n--- Checking LLM Router & Models ---")
    try:
        from ai_logging.router.llm_router import LLMRouter
        # Mute internal LLMRouter info logs for cleaner health check output
        logging.getLogger("ai_logging.router.llm_router").setLevel(logging.WARNING)
        
        router = LLMRouter(settings=settings)
        cli_logger.info("LLMRouter initialized.")
        
        available_models = list(router.llms.keys())
        if available_models:
            cli_logger.info(f"  Available LLM clients in router: {', '.join(available_models)}")
            if not settings.openai_api_key and ("gpt4" in available_models or "gpt35" in available_models) :
                 cli_logger.warning("  OpenAI models are listed but OPENAI_API_KEY is not set. They might not function.")
        else:
            cli_logger.warning("  No LLM clients were initialized in the LLMRouter. AI functionality will be limited.")
            all_checks_ok = False # Depending on strictness, this could be a failure

    except Exception as e:
        cli_logger.error(f"Failed to initialize or check LLMRouter: {e}")
        all_checks_ok = False

    # 3. Check Jinja2 Template Loading
    cli_logger.info("\n--- Checking Jinja2 Template ---")
    try:
        import jinja2
        from ai_logging.handlers.ai_handler import AIHandler # To access its template loading logic
        
        # Temporarily set AIHandler's logger to WARNING to avoid its info logs here
        logging.getLogger("ai_logging.handlers.ai_handler").setLevel(logging.WARNING)

        # We need an AIHandler instance to check its template
        # This is a bit indirect but tests the same logic AIHandler uses.
        temp_ai_handler = AIHandler(settings=settings) # Uses placeholder LLMs by default
        
        if isinstance(temp_ai_handler.jinja_template, jinja2.Template):
            cli_logger.info(f"Successfully loaded/created Jinja2 template for AI prompts.")
            # Check if it's the fallback or a loaded one
            if "Log Batch Summary" in temp_ai_handler.jinja_template.render(logs=[]): # Crude check for fallback
                 if settings.ai_logging_jinja_template_dir or \
                    settings.ai_logging_jinja_log_prompt_template_name != "default_log_prompt.jinja2":
                    cli_logger.warning(f"  Using a fallback Jinja2 template. Specified template '{settings.ai_logging_jinja_log_prompt_template_name}' might be missing or invalid.")
                 else:
                    cli_logger.info(f"  Using the default built-in Jinja2 template.")
            else:
                cli_logger.info(f"  Successfully loaded custom/packaged Jinja2 template: {settings.ai_logging_jinja_log_prompt_template_name}")
        else:
            cli_logger.error("Jinja2 template object in AIHandler is not a valid Jinja2.Template instance.")
            all_checks_ok = False
        temp_ai_handler.close() # Clean up timer
    except Exception as e:
        cli_logger.error(f"Failed during Jinja2 template check: {e}")
        all_checks_ok = False


    # 4. Check Prometheus Metrics Server (if enabled)
    cli_logger.info("\n--- Checking Prometheus Metrics Server ---")
    if settings.ai_logging_prometheus_enabled:
        try:
            from ai_logging.metrics.prometheus import start_prometheus_server_if_enabled, get_metrics_instance
            # Mute prometheus module's info logs for cleaner output
            logging.getLogger("ai_logging.metrics.prometheus").setLevel(logging.WARNING)

            # Check if prometheus_client is installed
            import prometheus_client # type: ignore
            cli_logger.info("  prometheus_client library is installed.")

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
                 if any(not isinstance(m, prometheus_client.metrics.MetricWrapperBase) for m in vars(metrics_instance).values() if hasattr(m, '_type')): # Check if real metrics
                     cli_logger.warning("  Prometheus metrics are using placeholders. Ensure 'prometheus_client' is installed and no init errors occurred.")

            cli_logger.info(f"  Prometheus is configured to run on port {settings.ai_logging_prometheus_port}.")
            cli_logger.info("  Note: This check does not guarantee the server can start (e.g., port might be in use).")

        except ImportError:
            cli_logger.warning("  'prometheus_client' library is not installed, but Prometheus is enabled. Metrics will not be exposed.")
            # all_checks_ok = False # Depending on strictness
        except Exception as e:
            cli_logger.error(f"Failed during Prometheus server check: {e}")
            all_checks_ok = False
    else:
        cli_logger.info("  Prometheus metrics server is disabled by configuration.")

    # Final Result
    cli_logger.info("\n--- Health Check Summary ---")
    if all_checks_ok:
        cli_logger.info("All essential checks passed. AI Logging package appears to be configured correctly.")
        cli_logger.info("Note: Functional tests (e.g., actual AI calls) are not part of this health check.")
        return True
    else:
        cli_logger.warning("One or more health checks failed. Please review the output above for details.")
        return False

def main():
    parser = argparse.ArgumentParser(description="Health check for the AI Logging package.")
    # Add any arguments if needed in the future, e.g., --verbose
    args = parser.parse_args()

    if run_health_checks():
        # Optionally, exit with code 0 for success
        # import sys
        # sys.exit(0)
        pass
    else:
        # Optionally, exit with code 1 for failure
        # import sys
        # sys.exit(1)
        pass

if __name__ == "__main__":
    main()
