import logging
import sys

import pytest

from ai_logging.config.settings import Settings
from ai_logging.metrics.prometheus import AILoggingMetrics, _NoopMetric
from ai_logging.handlers.ai_handler import AIHandler


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
        registry.get_sample_value(
            "ai_logging_ai_calls_total", {"model": "llm", "status": "success"}
        )
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
    assert (
        registry.get_sample_value("ai_logging_handler_records_processed_total")
        == 3.0
    )


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
    # prometheus_client is importable, but ai_logging_prometheus_enabled is
    # False. Built via a Settings instance directly (consistent with how
    # AILoggingMetrics is built elsewhere in this file, and simpler than
    # round-tripping through the get_settings() singleton + monkeypatch env).
    settings = Settings(ai_logging_prometheus_enabled=False)
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

    assert metrics_a.registry.get_sample_value(
        "ai_logging_ai_calls_total", {"model": "llm", "status": "success"}
    ) == 1.0
    assert metrics_b.registry.get_sample_value(
        "ai_logging_ai_calls_total", {"model": "llm", "status": "success"}
    ) == 1.0
