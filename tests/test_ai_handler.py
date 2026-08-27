import logging, threading, time
import pytest
from ai_logging.handlers.ai_handler import AIHandler
from ai_logging.metrics.prometheus import PlaceholderMetric

class FakeRouter:
    def __init__(self):
        self.calls = []
    def route_prompt(self, prompt, records):
        self.calls.append((prompt, records))
        return "ok"

def make_handler(**kw):
    kw.setdefault("llm_router", FakeRouter())
    kw.setdefault("batch_size", 100)
    kw.setdefault("flush_interval", 0.2)
    return AIHandler(**kw)

def test_timed_flush_does_not_deadlock():
    h = make_handler()
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "hi", None, None)
    h.emit(rec)
    done = threading.Event()
    def wait_for_flush():
        deadline = time.time() + 3
        while time.time() < deadline:
            if h.llm_router.calls:
                done.set(); return
            time.sleep(0.05)
    t = threading.Thread(target=wait_for_flush, daemon=True); t.start(); t.join(4)
    h.close()
    assert done.is_set(), "timed flush deadlocked or never fired"

def test_batch_size_triggers_flush():
    h = make_handler(batch_size=3, flush_interval=60)
    for i in range(3):
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, f"m{i}", None, None))
    assert len(h.llm_router.calls) == 1
    prompt, records = h.llm_router.calls[0]
    assert len(records) == 3
    h.close()

def test_close_drains_buffer():
    h = make_handler(batch_size=100, flush_interval=60)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "last", None, None))
    h.close()
    assert len(h.llm_router.calls) == 1

def test_router_exception_never_propagates_to_caller():
    class BoomRouter:
        def route_prompt(self, p, r): raise RuntimeError("api down")
    h = make_handler(llm_router=BoomRouter(), batch_size=1, flush_interval=60, max_retries=0)
    h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "x", None, None))  # must not raise
    h.close()

def test_pii_scrubbed_before_prompt():
    h = make_handler(batch_size=1, flush_interval=60)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "user bob@x.io logged in", None, None))
    prompt, records = h.llm_router.calls[0]
    assert "bob@x.io" not in prompt
    assert "[REDACTED_EMAIL]" in prompt
    h.close()

# --- Review fix-round-1 tests below ---
#
# `AIHandler.metrics` is normally `get_metrics_instance()`, which — with
# prometheus_client installed and prometheus enabled by default — returns
# real `prometheus_client.Counter`/`Histogram` objects. The handler's
# call-sites pass label names as kwargs to `.inc()`/`.observe()` (e.g.
# `.inc(model_name="llm", status="success")`), which the real client
# rejects with TypeError; that mismatch is Task 10's to fix, not ours.
# Today that TypeError fires on every batch and is absorbed by flush()'s
# broad `except Exception`, which incidentally short-circuits the retry
# loop and the response callback before either can be exercised. The
# `PlaceholderMetric` class (used before `_replace_placeholders_with_real_metrics`
# swaps in real client objects) accepts arbitrary `**labels` and never
# raises, so substituting it as the handler's `.metrics` after construction
# lets these tests exercise the real retry-loop and response-delivery code
# paths without touching the metrics call-sites or `prometheus.py`.


class _PlaceholderHandlerMetrics:
    """Stand-in for AILoggingMetrics using only PlaceholderMetric attributes,
    so AIHandler's metrics calls never raise regardless of the real
    prometheus_client label-API mismatch (Task 10's territory)."""

    def __init__(self):
        self.ai_handler_records_processed_total = PlaceholderMetric("stub_records_total", "d")
        self.ai_handler_batches_processed_total = PlaceholderMetric("stub_batches_total", "d")
        self.ai_handler_batch_size_bytes = PlaceholderMetric("stub_batch_size", "d")
        self.ai_calls_total = PlaceholderMetric("stub_ai_calls_total", "d")
        self.ai_call_latency_seconds = PlaceholderMetric("stub_ai_call_latency", "d")
        self.ai_call_errors_total = PlaceholderMetric("stub_ai_call_errors_total", "d")
        self.ai_circuit_breaker_state_changes_total = PlaceholderMetric("stub_cb_state_changes", "d")
        self.ai_circuit_breaker_currently_open = PlaceholderMetric("stub_cb_currently_open", "d")


def test_retry_loop_single_failure_does_not_sleep():
    # Covers the brief's "verify a single failure doesn't sleep" requirement
    # against the real retry-loop code path (see module note above for why
    # the metrics are stubbed).
    class BoomRouter:
        def __init__(self):
            self.call_count = 0
        def route_prompt(self, p, r):
            self.call_count += 1
            raise RuntimeError("api down")

    router = BoomRouter()
    h = make_handler(llm_router=router, batch_size=1, flush_interval=60, max_retries=0)
    h.metrics = _PlaceholderHandlerMetrics()
    start = time.time()
    h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "x", None, None))  # must not raise, must not sleep
    elapsed = time.time() - start
    assert router.call_count == 1, "max_retries=0 must mean exactly one attempt"
    assert elapsed < 0.5, f"a single failed attempt must not sleep (took {elapsed:.2f}s)"
    h.close()


@pytest.mark.xfail(strict=True, reason="metrics label API mismatch — fixed by Task 10")
def test_ai_response_callback_invoked_on_success():
    received = []
    h = make_handler(batch_size=1, flush_interval=60, ai_response_callback=received.append)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "hi", None, None))
    assert received == ["ok"]
    h.close()


def test_close_stops_flush_timer_permanently():
    # Races close() against a Timer thread that has already entered
    # _timed_flush (i.e. past the point where close()'s cancel() would be a
    # no-op) to reproduce the self-re-arming-timer-on-a-closed-handler bug.
    h = make_handler(batch_size=100, flush_interval=60)
    barrier = threading.Barrier(2)

    def fire_timed_flush():
        barrier.wait()
        h._timed_flush()

    t = threading.Thread(target=fire_timed_flush)
    t.start()
    barrier.wait()
    h.close()
    t.join(2)
    time.sleep(0.1)  # let any resurrected timer's start() call settle
    assert h._flush_timer is None, "no flush timer may survive close()"
