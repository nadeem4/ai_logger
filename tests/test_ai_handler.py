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
