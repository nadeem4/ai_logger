# This file marks logscribe.config as a sub-package.

from .settings import Settings, get_settings

__all__ = [
    "get_settings",
    "Settings",
]
