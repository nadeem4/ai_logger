# This file marks ai_logging as a package.

# Expose key components for easier import
from .logger import AILogger, get_ai_logger
from .handlers import AIHandler, get_async_logging_setup
from .utils import JsonFormatter, scrub_pii_from_dict
from .config import get_settings, Settings
from .router import LLMRouter
from .metrics import get_metrics_instance, start_prometheus_server_if_enabled

__all__ = [
    "AILogger",
    "get_ai_logger",
    "AIHandler",
    "get_async_logging_setup",
    "JsonFormatter",
    "scrub_pii_from_dict",
    "get_settings",
    "Settings",
    "LLMRouter",
    "get_metrics_instance",
    "start_prometheus_server_if_enabled",
]

# Version of the ai_logging package
__version__ = "0.1.0" # Keep this in sync with setup.py and pyproject.toml
