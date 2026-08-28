# This file marks logscribe.metrics as a sub-package.

from .prometheus import AILoggingMetrics, get_metrics_instance, start_prometheus_server_if_enabled

__all__ = [
    "get_metrics_instance",
    "start_prometheus_server_if_enabled",
    "AILoggingMetrics",  # Exposing the class itself might be useful for type hinting or direct instantiation
]
