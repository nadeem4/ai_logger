import logging
import queue
import sys
import threading
import time

from loglens.config.settings import Settings
from loglens.handlers.ai_handler import AIHandler
from loglens.metrics.prometheus import AILoggingMetrics


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
                done.set()
                return
            time.sleep(0.05)

    t = threading.Thread(target=wait_for_flush, daemon=True)
    t.start()
    t.join(4)
    h.close()
    assert done.is_set(), "timed flush deadlocked or never fired"


def test_batch_size_triggers_flush():
    h = make_handler(batch_size=3, flush_interval=60)
    for i in range(3):
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, f"m{i}", None, None))
    h.close()  # deterministic: close() drains and joins the worker
    assert len(h.llm_router.calls) == 1
    prompt, records = h.llm_router.calls[0]
    assert len(records) == 3


def test_close_drains_buffer():
    h = make_handler(batch_size=100, flush_interval=60)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "last", None, None))
    h.close()
    assert len(h.llm_router.calls) == 1


def test_router_exception_never_propagates_to_caller():
    # Also restores the coverage lost when processing moved to the worker
    # thread: a batch that raises must not kill the worker, so a second
    # batch emitted afterward must still reach the router.
    class BoomRouter:
        def __init__(self):
            self.calls = 0

        def route_prompt(self, p, r):
            self.calls += 1
            raise RuntimeError("api down")

    router = BoomRouter()
    h = make_handler(llm_router=router, batch_size=1, flush_interval=60, max_retries=0)
    h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "x", None, None))  # must not raise
    h.emit(
        logging.LogRecord("t", logging.ERROR, "f", 1, "y", None, None)
    )  # worker must have survived
    h.close()  # deterministic: close() drains and joins the worker
    assert router.calls == 2, "a batch that raises must not kill the worker thread"


def test_pii_scrubbed_before_prompt():
    h = make_handler(batch_size=1, flush_interval=60)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "user bob@x.io logged in", None, None))
    h.close()  # deterministic: close() drains and joins the worker
    prompt, records = h.llm_router.calls[0]
    assert "bob@x.io" not in prompt
    assert "[REDACTED_EMAIL]" in prompt


def test_retry_loop_single_failure_does_not_sleep():
    # Covers the brief's "verify a single failure doesn't sleep" requirement
    # against the real retry-loop code path.
    class BoomRouter:
        def __init__(self):
            self.call_count = 0

        def route_prompt(self, p, r):
            self.call_count += 1
            raise RuntimeError("api down")

    router = BoomRouter()
    h = make_handler(llm_router=router, batch_size=1, flush_interval=60, max_retries=0)
    h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "x", None, None))  # must not raise
    # Processing (and any retry backoff sleep) now happens on the worker
    # thread, not inside emit(), so time the drain-and-join in close()
    # instead of emit() itself -- that's where the retry loop actually runs.
    start = time.time()
    h.close()
    elapsed = time.time() - start
    assert router.call_count == 1, "max_retries=0 must mean exactly one attempt"
    assert elapsed < 0.5, f"a single failed attempt must not sleep (took {elapsed:.2f}s)"


def test_ai_response_callback_invoked_on_success():
    received = []
    h = make_handler(batch_size=1, flush_interval=60, ai_response_callback=received.append)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "hi", None, None))
    h.close()  # deterministic: close() drains and joins the worker
    assert received == ["ok"]


def test_emit_returns_fast_even_when_provider_is_slow():
    import time

    class SlowRouter:
        def route_prompt(self, p, r):
            time.sleep(1.5)
            return "ok"

    h = make_handler(llm_router=SlowRouter(), batch_size=1, flush_interval=60)
    t0 = time.time()
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "x", None, None))
    assert time.time() - t0 < 0.5, "emit blocked on the AI call"
    h.close()  # close still waits for in-flight work


def test_post_close_emit_is_logged_not_silently_dropped(caplog):
    # Once the worker has exited (after close()), a flush-triggering emit
    # must never silently vanish into a queue nobody drains -- it must be
    # logged instead.
    h = make_handler(batch_size=1, flush_interval=60)
    h.close()
    with caplog.at_level(logging.WARNING, logger="loglens.handlers.ai_handler"):
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "after close", None, None))
    assert not h.llm_router.calls, "router must not be called after the worker has exited"
    assert "no longer running" in caplog.text


def test_close_stops_flush_timer_permanently():
    # Races close() against a Timer thread that has already entered
    # _timed_flush (i.e. past the point where close()'s cancel() would be a
    # no-op) to reproduce the self-re-arming-timer-on-a-closed-handler bug.
    h = make_handler(batch_size=100, flush_interval=60)
    barrier = threading.Barrier(2, timeout=5)

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


# --- Final review wave: regression coverage for the five merge blockers ---


def test_exception_traceback_reaches_the_prompt():
    # JsonFormatter emits the traceback under the key "exception_info".
    # The packaged template used to test `log_entry.exception`, which is
    # always undefined and therefore always falsy, so no traceback ever
    # reached the model -- for exactly the ERROR-and-above batches that get
    # routed to the expensive capable tier.
    h = make_handler(batch_size=1, flush_interval=60)
    assert h.jinja_template.name == "default_log_prompt.jinja2", "packaged template not loaded"
    try:
        1 / 0
    except ZeroDivisionError:
        h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "boom", None, sys.exc_info()))
    h.close()
    prompt, _ = h.llm_router.calls[0]
    assert "ZeroDivisionError" in prompt, "exception type missing from the rendered prompt"
    assert "Traceback" in prompt


def test_exception_traceback_reaches_the_prompt_via_fallback_template():
    # Same bug, second site: the inline fallback template used when the
    # configured template cannot be found.
    from loglens.config.settings import Settings

    settings = Settings(loglens_jinja_log_prompt_template_name="definitely_not_there.jinja2")
    h = AIHandler(settings=settings, llm_router=FakeRouter(), batch_size=1, flush_interval=60)
    assert h.jinja_template.name is None, "expected the inline fallback template"
    try:
        1 / 0
    except ZeroDivisionError:
        h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "boom", None, sys.exc_info()))
    h.close()
    prompt, _ = h.llm_router.calls[0]
    assert "ZeroDivisionError" in prompt, "exception type missing from the fallback-rendered prompt"


def test_prompt_is_not_html_escaped():
    # The prompt is plaintext for an LLM, not HTML: autoescape bought no
    # safety and mangled exactly the payloads worth analysing.
    message = "boom <tag> & 'quote' \"dq\""
    h = make_handler(batch_size=1, flush_interval=60)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, message, None, None))
    h.close()
    prompt, _ = h.llm_router.calls[0]
    assert message in prompt, f"message was mangled in the prompt: {prompt!r}"
    assert "&lt;" not in prompt and "&amp;" not in prompt and "&#39;" not in prompt


def test_none_router_response_is_not_reported_as_a_successful_call():
    # route_prompt() returns None when no provider is configured. Counting
    # that as a success made a key-less deployment report 100% healthy AI
    # calls at sub-millisecond latency while making no calls at all.
    from prometheus_client import CollectorRegistry

    from loglens.metrics.prometheus import AILoggingMetrics

    class NoProviderRouter:
        def route_prompt(self, prompt, records):
            return None

    registry = CollectorRegistry()
    received = []
    h = AIHandler(
        llm_router=NoProviderRouter(),
        batch_size=1,
        flush_interval=60,
        ai_response_callback=received.append,
    )
    h.metrics = AILoggingMetrics(registry=registry)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "x", None, None))
    h.close()

    assert received == [], "callback must not be invoked when no AI call was made"
    assert (
        registry.get_sample_value("loglens_ai_calls_total", {"model": "llm", "status": "success"})
        is None
    ), "a None response must not be counted as a successful AI call"
    assert (
        registry.get_sample_value(
            "loglens_ai_calls_total", {"model": "llm", "status": "no_provider"}
        )
        == 1.0
    )
    assert (
        registry.get_sample_value("loglens_ai_call_latency_seconds_count", {"model": "llm"}) is None
    ), "no latency may be observed for a call that never happened"


def test_handler_constructs_when_provider_sdk_is_missing(monkeypatch, caplog):
    # A key in the environment plus no provider SDK installed (exactly what
    # `pip install -r requirements.txt` produces) must degrade to "no
    # providers" with a warning, not crash the host app at logger setup.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "openai", None)

    with caplog.at_level(logging.WARNING, logger="loglens.router.llm_router"):
        h = AIHandler(batch_size=1, flush_interval=60)  # must not raise
    try:
        assert h.llm_router.fast is None and h.llm_router.capable is None
        assert "openai SDK not installed" in caplog.text
    finally:
        h.close()


def test_clean_shutdown_after_producers_finish_loses_no_records():
    # Regression guard for the shutdown race: producers emit concurrently
    # with a short flush timer, then close() runs once they are done.
    # Every record must reach the router -- nothing may be dropped behind
    # close()'s sentinel.
    iterations, producers, per_producer = 200, 2, 5
    for _ in range(iterations):
        router = FakeRouter()
        h = make_handler(llm_router=router, batch_size=3, flush_interval=0.002)

        def produce():
            for i in range(per_producer):
                h.emit(logging.LogRecord("t", logging.INFO, "f", 1, f"m{i}", None, None))

        threads = [threading.Thread(target=produce) for _ in range(producers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        h.close()

        received = sum(len(records) for _, records in router.calls)
        assert received == producers * per_producer, (
            f"clean shutdown lost {producers * per_producer - received} record(s)"
        )


def test_close_racing_live_emit_never_loses_records_silently(caplog):
    # close() racing live producers: a flush() that passed the liveness
    # check could enqueue *behind* close()'s sentinel, and the worker
    # returned at the sentinel -- dropping everything after it with nothing
    # logged at all. The loss window is the whole queue-drain duration, so
    # the router below sleeps briefly per batch to keep the worker (alive,
    # and draining) busy while the producers keep emitting.
    #
    # Every record must end up accounted for: processed by the router,
    # still sitting in the buffer (emitted after close(), never flushed),
    # or reported as dropped -- either through the log-and-drop branch
    # (counted here via _log_worker_dead_once, which logs the first drop
    # and warns that further drops are not logged individually) or through
    # close()'s post-join "still queued" backstop. Anything else vanished
    # silently, which is precisely the bug.
    class SlowFakeRouter(FakeRouter):
        def route_prompt(self, prompt, records):
            time.sleep(0.004)
            return super().route_prompt(prompt, records)

    iterations, producers, per_producer = 15, 3, 50
    for _ in range(iterations):
        caplog.clear()
        router = SlowFakeRouter()
        h = make_handler(llm_router=router, batch_size=5, flush_interval=0.002)
        started = threading.Event()

        dropped = []
        original_log_drop = h._log_worker_dead_once

        def counting_log_drop(count, _orig=original_log_drop):
            dropped.append(count)
            _orig(count)

        h._log_worker_dead_once = counting_log_drop

        def produce():
            for i in range(per_producer):
                h.emit(logging.LogRecord("t", logging.INFO, "f", 1, f"m{i}", None, None))
                if i >= 3:
                    started.set()
                time.sleep(0.0005)

        threads = [threading.Thread(target=produce) for _ in range(producers)]
        with caplog.at_level(logging.WARNING, logger="loglens.handlers.ai_handler"):
            for t in threads:
                t.start()
            started.wait(2)
            h.close()  # races the still-running producers
            for t in threads:
                t.join(5)
                assert not t.is_alive()

        received = sum(len(records) for _, records in router.calls)
        still_buffered = len(h._buffer)
        left_in_queue = 0
        while True:
            try:
                item = h._work_q.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                left_in_queue += len(item)

        total = producers * per_producer
        assert received + still_buffered + sum(dropped) + left_in_queue == total, (
            f"{total - received - still_buffered - sum(dropped) - left_in_queue} "
            "record(s) vanished unaccounted for"
        )
        if left_in_queue:
            assert "still queued" in caplog.text, (
                f"{left_in_queue} record(s) were left queued at close() with nothing logged"
            )


def test_emit_never_raises_and_delegates_to_handle_error(monkeypatch):
    h = make_handler(batch_size=100, flush_interval=60)

    def boom(*args, **kwargs):
        raise RuntimeError("metrics broke")

    monkeypatch.setattr(h.metrics.ai_handler_records_processed_total, "inc", boom)
    handled = []
    monkeypatch.setattr(h, "handleError", lambda record: handled.append(record))

    rec = logging.LogRecord("t", logging.INFO, "f", 1, "x", None, None)
    h.emit(rec)  # must not raise into the caller
    h.close()

    assert handled == [rec]


def test_close_is_idempotent_when_called_twice():
    h = make_handler(batch_size=1, flush_interval=60)
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "x", None, None))
    h.close()
    h.close()  # must not raise, hang, or re-process the batch
    assert len(h.llm_router.calls) == 1


def test_custom_jinja_template_dir_overrides_packaged_templates(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "custom_prompt.jinja2").write_text(
        "CUSTOM PROMPT ({{ logs|length }} logs)", encoding="utf-8"
    )
    settings = Settings(
        loglens_jinja_template_dir=str(template_dir),
        loglens_jinja_log_prompt_template_name="custom_prompt.jinja2",
    )
    h = AIHandler(settings=settings, llm_router=FakeRouter(), batch_size=1, flush_interval=60)
    try:
        assert h.jinja_template.name == "custom_prompt.jinja2"
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "hi", None, None))
    finally:
        h.close()
    prompt, _ = h.llm_router.calls[0]
    assert prompt == "CUSTOM PROMPT (1 logs)"


def test_default_ai_response_logger_writes_to_named_logger(caplog):
    h = make_handler(batch_size=1, flush_interval=60)  # uses the default callback
    logger_name = h.settings.loglens_ai_response_log_logger_name
    with caplog.at_level(logging.INFO, logger=logger_name):
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "hi", None, None))
        h.close()
    assert "ok" in caplog.text


def test_process_batch_is_a_noop_for_an_empty_batch():
    h = make_handler(batch_size=1, flush_interval=60)
    h._process_batch([])  # must not raise, must not touch the router
    h.close()
    assert h.llm_router.calls == []


def test_prepare_record_for_processing_falls_back_when_output_is_not_json():
    # If the configured formatter's output can't be parsed back as JSON,
    # prepare_record_for_processing() must still hand back a usable dict
    # instead of raising out of the worker thread.
    h = make_handler(batch_size=1, flush_interval=60)
    h.formatter = logging.Formatter("%(message)s")  # plain text, not JSON
    rec = logging.LogRecord("t", logging.WARNING, "f", 1, "plain text output", None, None)
    data = h.prepare_record_for_processing(rec)
    h.close()
    assert data["message"] == "plain text output"
    assert data["levelname"] == "WARNING"


def test_retry_backs_off_between_attempts_and_stops_at_max_retries():
    class AlwaysFailRouter:
        def __init__(self):
            self.calls = 0

        def route_prompt(self, p, r):
            self.calls += 1
            raise RuntimeError("down")

    router = AlwaysFailRouter()
    h = make_handler(
        llm_router=router,
        batch_size=1,
        flush_interval=60,
        max_retries=2,
        retry_backoff_factor=0.01,
    )
    start = time.time()
    h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "x", None, None))
    h.close()
    elapsed = time.time() - start
    assert router.calls == 3, "max_retries=2 must mean 3 total attempts"
    # backoff = 0.01 * (2**0 + 2**1) = 0.03s between the 3 attempts.
    assert elapsed >= 0.03, f"retries must back off between attempts (took {elapsed:.3f}s)"


def test_circuit_breaker_short_circuits_further_batches_once_open():
    class AlwaysFailRouter:
        def __init__(self):
            self.calls = 0

        def route_prompt(self, p, r):
            self.calls += 1
            raise RuntimeError("down")

    settings = Settings(loglens_cb_failure_threshold=1, loglens_cb_reset_timeout_seconds=60)
    router = AlwaysFailRouter()
    metrics = AILoggingMetrics()
    h = AIHandler(
        settings=settings,
        llm_router=router,
        batch_size=1,
        flush_interval=60,
        max_retries=0,
    )
    h.metrics = metrics
    h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "first", None, None))  # trips the breaker
    h.emit(logging.LogRecord("t", logging.ERROR, "f", 1, "second", None, None))  # short-circuited
    h.close()
    assert router.calls == 1, "an open circuit breaker must prevent further router calls"
    assert h.circuit_breaker.state == "OPEN"


def test_jinja_render_error_falls_back_to_a_summary_prompt():
    class ExplodingTemplate:
        name = "broken"

        def render(self, **kwargs):
            raise RuntimeError("template exploded")

    h = make_handler(batch_size=1, flush_interval=60)
    h.jinja_template = ExplodingTemplate()
    h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "hello world", None, None))
    h.close()
    prompt, records = h.llm_router.calls[0]
    assert "Log Summary: 1 entries" in prompt
    assert "hello world" in prompt
    assert "Template error" in prompt


def test_worker_loop_logs_and_survives_a_processing_exception(caplog):
    def bad_scrubber(data):
        raise RuntimeError("scrub explode")

    h = make_handler(pii_scrubber=bad_scrubber, batch_size=1, flush_interval=60)
    with caplog.at_level(logging.ERROR, logger="loglens.handlers.ai_handler"):
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "x", None, None))
    h.close()
    assert h.llm_router.calls == []
    assert "failed to process a batch" in caplog.text


def test_worker_loop_survives_a_non_exception_base_exception_and_keeps_going(caplog):
    # A BaseException that is not an Exception (e.g. a deliberate fatal
    # signal from misbehaving user code) must not kill the worker thread --
    # it must be logged and the worker must keep draining later batches.
    class Fatal(BaseException):
        pass

    calls = {"n": 0}

    def flaky_scrubber(data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Fatal("boom")
        return data

    router = FakeRouter()
    h = make_handler(
        llm_router=router, pii_scrubber=flaky_scrubber, batch_size=1, flush_interval=60
    )
    with caplog.at_level(logging.ERROR, logger="loglens.handlers.ai_handler"):
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "first", None, None))
        h.emit(logging.LogRecord("t", logging.INFO, "f", 1, "second", None, None))
    h.close()
    assert len(router.calls) == 1, "the batch after the Fatal error must still be processed"
    assert "unexpected error" in caplog.text
