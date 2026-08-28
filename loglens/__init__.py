# This file marks loglens as a package.

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

# Version of the loglens package, single-sourced from installed package metadata
# (which reads it from pyproject.toml).
from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("loglens")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0.dev0"
