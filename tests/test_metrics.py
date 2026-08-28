import logging
import socket
import sys

import pytest

from logscribe.config.settings import Settings
from logscribe.handlers.ai_handler import AIHandler
from logscribe.metrics import prometheus as prometheus_module
from logscribe.metrics.prometheus import AILoggingMetrics, _NoopMetric


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("0.0.0.0", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(autouse=True)
def _reset_prometheus_server_flag(monkeypatch):
    # start_prometheus_server_if_enabled() guards against starting the HTTP
    # server twice via a module-level flag. Reset it per test so each test's
    # "did it (attempt to) start?" assertion is not decided by test order.
    monkeypatch.setattr(prometheus_module, "_prometheus_server_started_flag", False)


class FakeRouter:
    def __init__(self):
        self.calls = []

    def route_prompt(self, prompt, records):
        self.calls.append((prompt, records))
        return "ok"


def test_real_metrics_labeled_counter_readback():
    from prometheus_client import CollectorRegistry

    registry = CollectorRegistry()
    metrics = AILoggingMetrics(registry=registry)

    metrics.ai_calls_total.labels(model="llm", status="success").inc()

    assert (
        registry.get_sample_value("logscribe_ai_calls_total", {"model": "llm", "status": "success"})
        == 1.0
    )


def test_handler_integration_records_processed_counter():
    from prometheus_client import CollectorRegistry

    registry = CollectorRegistry()
    metrics = AILoggingMetrics(registry=registry)

    h = AIHandler(
        llm_router=FakeRouter(),
        batch_size=3,
        flush_interval=60,
    )
    h.metrics = metrics

    for i in range(3):
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, f"m{i}", None, None))

    h.close()  # deterministic: close() drains and joins the worker
    assert len(h.llm_router.calls) == 1
    assert registry.get_sample_value("logscribe_handler_records_processed_total") == 3.0


def test_noop_metrics_fallback_when_prometheus_client_unimportable(monkeypatch):
    monkeypatch.setitem(sys.modules, "prometheus_client", None)

    # Reload-free: AILoggingMetrics imports prometheus_client lazily inside
    # its constructor, so setting sys.modules entry to None makes that
    # import raise ImportError, forcing the no-op path.
    metrics = AILoggingMetrics()

    # Full chained call must not raise.
    metrics.ai_calls_total.labels(model="llm", status="success").inc()
    metrics.ai_call_latency_seconds.labels(model="llm").observe(0.5)
    metrics.ai_circuit_breaker_currently_open.labels(model="llm").set(1)
    metrics.ai_handler_records_processed_total.inc()
    metrics.ai_handler_batches_processed_total.inc()
    metrics.ai_handler_batch_size_records.observe(3)


def test_disabled_by_settings_uses_noop_metrics():
    # The second (and separately spec'd, item 7) way into the no-op branch:
    # prometheus_client is importable, but logscribe_prometheus_enabled is
    # False. Built via a Settings instance directly (consistent with how
    # AILoggingMetrics is built elsewhere in this file, and simpler than
    # round-tripping through the get_settings() singleton + monkeypatch env).
    settings = Settings(logscribe_prometheus_enabled=False)
    metrics = AILoggingMetrics(settings=settings)

    # These must really be no-ops, not real Counters/Histograms/Gauges.
    assert isinstance(metrics.ai_calls_total, _NoopMetric)
    assert isinstance(metrics.ai_call_latency_seconds, _NoopMetric)
    assert isinstance(metrics.ai_circuit_breaker_currently_open, _NoopMetric)
    assert isinstance(metrics.ai_handler_records_processed_total, _NoopMetric)

    # Full chained call must not raise.
    metrics.ai_calls_total.labels(model="llm", status="success").inc()
    metrics.ai_call_latency_seconds.labels(model="llm").observe(0.5)
    metrics.ai_circuit_breaker_currently_open.labels(model="llm").set(1)
    metrics.ai_handler_records_processed_total.inc()
    metrics.ai_handler_batches_processed_total.inc()
    metrics.ai_handler_batch_size_records.observe(3)


def test_two_default_instances_get_distinct_registries():
    # get_metrics_instance() constructs AILoggingMetrics() with no explicit
    # registry at most once per process (it's a singleton), so nothing else
    # in the suite proves that two independently-constructed instances with
    # registry=None don't collide. If the default registry were ever changed
    # to a shared object (e.g. a mutable default argument, or module-level
    # REGISTRY reuse), the second AILoggingMetrics() call below would raise
    # `ValueError: Duplicated timeseries in CollectorRegistry` the moment it
    # tries to register the same metric names a second time.
    metrics_a = AILoggingMetrics()
    metrics_b = AILoggingMetrics()

    assert metrics_a.registry is not None
    assert metrics_b.registry is not None
    assert metrics_a.registry is not metrics_b.registry

    metrics_a.ai_calls_total.labels(model="llm", status="success").inc()
    metrics_b.ai_calls_total.labels(model="llm", status="success").inc()

    assert (
        metrics_a.registry.get_sample_value(
            "logscribe_ai_calls_total", {"model": "llm", "status": "success"}
        )
        == 1.0
    )
    assert (
        metrics_b.registry.get_sample_value(
            "logscribe_ai_calls_total", {"model": "llm", "status": "success"}
        )
        == 1.0
    )


def test_start_prometheus_server_disabled_by_settings(caplog):
    settings = Settings(logscribe_prometheus_enabled=False)
    with caplog.at_level(logging.INFO, logger="logscribe.metrics.prometheus"):
        prometheus_module.start_prometheus_server_if_enabled(settings)
    assert "disabled by configuration" in caplog.text


def test_start_prometheus_server_starts_and_is_idempotent(caplog):
    settings = Settings(logscribe_prometheus_enabled=True, logscribe_prometheus_port=_free_port())
    with caplog.at_level(logging.DEBUG, logger="logscribe.metrics.prometheus"):
        prometheus_module.start_prometheus_server_if_enabled(settings)
        assert prometheus_module._prometheus_server_started_flag is True
        # A second call must not attempt to bind the port again -- it should
        # short-circuit on the "already started" guard instead.
        prometheus_module.start_prometheus_server_if_enabled(settings)
    assert "started on port" in caplog.text
    assert "already started" in caplog.text


def test_start_prometheus_server_reports_port_already_in_use(caplog):
    # start_http_server() binds "0.0.0.0" by default, so the blocking socket
    # must occupy that same wildcard address for the port collision to be
    # genuine (binding only "localhost" on the same port does not conflict).
    blocking_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocking_socket.bind(("0.0.0.0", 0))
    port = blocking_socket.getsockname()[1]
    blocking_socket.listen(1)
    try:
        settings = Settings(logscribe_prometheus_enabled=True, logscribe_prometheus_port=port)
        with caplog.at_level(logging.DEBUG, logger="logscribe.metrics.prometheus"):
            prometheus_module.start_prometheus_server_if_enabled(settings)
        assert "Port might be in use" in caplog.text
        assert prometheus_module._prometheus_server_started_flag is False
    finally:
        blocking_socket.close()


def test_start_prometheus_server_handles_missing_prometheus_client(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "prometheus_client", None)
    settings = Settings(logscribe_prometheus_enabled=True, logscribe_prometheus_port=_free_port())
    with caplog.at_level(logging.WARNING, logger="logscribe.metrics.prometheus"):
        prometheus_module.start_prometheus_server_if_enabled(settings)
    assert "prometheus_client not installed" in caplog.text
    assert prometheus_module._prometheus_server_started_flag is False


def test_start_prometheus_server_handles_unexpected_error(monkeypatch, caplog):
    def boom():
        raise RuntimeError("metrics singleton exploded")

    monkeypatch.setattr(prometheus_module, "get_metrics_instance", boom)
    settings = Settings(logscribe_prometheus_enabled=True, logscribe_prometheus_port=_free_port())
    with caplog.at_level(logging.ERROR, logger="logscribe.metrics.prometheus"):
        prometheus_module.start_prometheus_server_if_enabled(settings)
    assert "unexpected error occurred while starting Prometheus server" in caplog.text
    assert prometheus_module._prometheus_server_started_flag is False
