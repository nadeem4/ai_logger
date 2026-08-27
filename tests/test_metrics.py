import logging
import sys

import pytest

from ai_logging.metrics.prometheus import AILoggingMetrics
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

    assert len(h.llm_router.calls) == 1
    assert (
        registry.get_sample_value("ai_logging_handler_records_processed_total")
        == 3.0
    )
    h.close()


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
