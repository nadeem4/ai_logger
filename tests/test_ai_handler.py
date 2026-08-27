import logging, threading, time
from ai_logging.handlers.ai_handler import AIHandler

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
