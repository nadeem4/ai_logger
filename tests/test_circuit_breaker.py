from ai_logging.utils.circuit_breaker import CircuitBreaker


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=60, clock=lambda: 100.0)
    cb.record_failure(); assert cb.allow_request()
    cb.record_failure(); assert not cb.allow_request()
    assert cb.state == "OPEN"


def test_half_open_after_timeout_then_success_closes():
    now = [100.0]
    cb = CircuitBreaker(2, 60, clock=lambda: now[0])
    cb.record_failure(); cb.record_failure()
    now[0] = 161.0
    assert cb.allow_request()          # transitions to HALF_OPEN
    assert cb.state == "HALF_OPEN"
    cb.record_success()
    assert cb.state == "CLOSED" and cb.allow_request()


def test_half_open_failure_reopens():
    now = [100.0]
    cb = CircuitBreaker(2, 60, clock=lambda: now[0])
    cb.record_failure(); cb.record_failure()
    now[0] = 161.0
    cb.allow_request()
    cb.record_failure()
    assert cb.state == "OPEN" and not cb.allow_request()
