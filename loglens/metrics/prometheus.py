import logging
import threading
from typing import Optional

from ..config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


# --- No-op fallback used when prometheus_client is unavailable or metrics
# are disabled by configuration. Its shape mirrors the real client's API
# (`.labels(...)` returns something with `inc`/`set`/`observe`) so handler
# call-sites never need to know which flavour they got. ---
class _NoopMetric:
    def inc(self, amount: float = 1.0) -> None:
        pass

    def set(self, value: float) -> None:
        pass

    def observe(self, amount: float) -> None:
        pass

    def labels(self, *args, **kwargs) -> "_NoopMetric":
        return self


class AILoggingMetrics:
    """
    Container for Prometheus metrics related to the LogLens package.

    Builds real `prometheus_client` metrics when the library is importable
    and metrics are enabled in settings, otherwise builds `_NoopMetric`
    stand-ins. The choice is made once, at construction time.
    """

    def __init__(self, settings: Optional[Settings] = None, registry=None):
        self.settings = settings or get_settings()

        use_real_metrics = self.settings.loglens_prometheus_enabled
        real_metrics_module = None
        if use_real_metrics:
            try:
                import prometheus_client as real_metrics_module
            except ImportError:
                logger.warning(
                    "prometheus_client not installed, but metrics are enabled in config. "
                    "Falling back to no-op metrics."
                )
                use_real_metrics = False

        if use_real_metrics:
            self.registry = registry if registry is not None else real_metrics_module.CollectorRegistry()
            self._build_real_metrics(real_metrics_module)
        else:
            if not self.settings.loglens_prometheus_enabled:
                logger.info("Prometheus metrics are disabled by configuration.")
            self.registry = registry
            self._build_noop_metrics()

    def _build_real_metrics(self, prometheus_client) -> None:
        Counter = prometheus_client.Counter
        Gauge = prometheus_client.Gauge
        Histogram = prometheus_client.Histogram
        registry = self.registry

        # AIHandler Metrics
        self.ai_handler_records_processed_total = Counter(
            "loglens_handler_records_processed",
            "Total number of log records processed by AIHandler.",
            registry=registry,
        )
        self.ai_handler_batches_processed_total = Counter(
            "loglens_handler_batches_processed",
            "Total number of batches processed by AIHandler.",
            registry=registry,
        )
        self.ai_handler_batch_size_records = Histogram(
            "loglens_handler_batch_size_records",
            "Size of batches processed by AIHandler (number of records).",
            buckets=(1, 2, 5, 10, 15, 20, 30, 50, 75, 100, float("inf")),
            registry=registry,
        )

        # Queue Metrics
        self.queue_depth = Gauge(
            "loglens_queue_depth_records",
            "Number of log records currently in the AI processing queue.",
            registry=registry,
        )

        # AI Call Metrics
        self.ai_calls_total = Counter(
            "loglens_ai_calls",
            "Total number of AI API calls made.",
            labelnames=("model", "status"),
            registry=registry,
        )
        self.ai_call_latency_seconds = Histogram(
            "loglens_ai_call_latency_seconds",
            "Latency of AI API calls in seconds.",
            labelnames=("model",),
            buckets=(0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, float("inf")),
            registry=registry,
        )
        self.ai_call_errors_total = Counter(
            "loglens_ai_call_errors",
            "Total number of errors during AI API calls.",
            labelnames=("model", "error_type"),
            registry=registry,
        )

        # Circuit Breaker Metrics
        self.ai_circuit_breaker_state_changes_total = Counter(
            "loglens_circuit_breaker_state_changes",
            "Total number of times the AI call circuit breaker changed state.",
            labelnames=("model", "new_state"),
            registry=registry,
        )
        self.ai_circuit_breaker_currently_open = Gauge(
            "loglens_circuit_breaker_currently_open",
            "Indicates if the circuit breaker for a model is currently open (1) or not (0).",
            labelnames=("model",),
            registry=registry,
        )

        # PII Scrubbing Metrics
        self.pii_scrubbed_fields_total = Counter(
            "loglens_pii_scrubbed_fields",
            "Total number of fields scrubbed by the PII filter.",
            labelnames=("rule_name",),
            registry=registry,
        )

        logger.info("Prometheus metrics initialized with real prometheus_client objects.")

    def _build_noop_metrics(self) -> None:
        self.ai_handler_records_processed_total = _NoopMetric()
        self.ai_handler_batches_processed_total = _NoopMetric()
        self.ai_handler_batch_size_records = _NoopMetric()
        self.queue_depth = _NoopMetric()
        self.ai_calls_total = _NoopMetric()
        self.ai_call_latency_seconds = _NoopMetric()
        self.ai_call_errors_total = _NoopMetric()
        self.ai_circuit_breaker_state_changes_total = _NoopMetric()
        self.ai_circuit_breaker_currently_open = _NoopMetric()
        self.pii_scrubbed_fields_total = _NoopMetric()


# --- Singleton Instance ---
_metrics_instance: Optional[AILoggingMetrics] = None
_metrics_lock = threading.Lock()


def get_metrics_instance() -> AILoggingMetrics:
    """Returns a singleton instance of AILoggingMetrics."""
    global _metrics_instance
    if _metrics_instance is None:
        with _metrics_lock:
            if _metrics_instance is None:
                _metrics_instance = AILoggingMetrics()
    return _metrics_instance


# --- Prometheus Server Control ---
_prometheus_server_started_flag = False
_prometheus_server_lock = threading.Lock()


def start_prometheus_server_if_enabled(settings: Optional[Settings] = None) -> None:
    """
    Starts the Prometheus HTTP server if enabled in settings and not already started.
    This should typically be called once at application startup.
    """
    global _prometheus_server_started_flag
    app_settings = settings or get_settings()

    if not app_settings.loglens_prometheus_enabled:
        logger.info("Prometheus metrics server is disabled by configuration.")
        return

    with _prometheus_server_lock:
        if _prometheus_server_started_flag:
            logger.debug("Prometheus server already started.")
            return

        try:
            from prometheus_client import start_http_server, REGISTRY

            metrics = get_metrics_instance()
            registry = metrics.registry if metrics.registry is not None else REGISTRY
            port = app_settings.loglens_prometheus_port
            start_http_server(port, registry=registry)
            _prometheus_server_started_flag = True
            logger.info(f"Prometheus metrics server started on port {port}.")
        except ImportError:
            logger.warning(
                "prometheus_client not installed, but metrics server is enabled in config. "
                "Metrics server cannot be started."
            )
        except OSError as e:  # Handle port already in use
            logger.error(f"Failed to start Prometheus server on port {app_settings.loglens_prometheus_port}: {e}. Port might be in use.")
        except Exception as e:
            logger.error(f"An unexpected error occurred while starting Prometheus server: {e}")
