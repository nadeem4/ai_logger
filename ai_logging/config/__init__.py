# This file marks ai_logging.config as a sub-package.

from .settings import get_settings, Settings

__all__ = [
    "get_settings",
    "Settings",
]
