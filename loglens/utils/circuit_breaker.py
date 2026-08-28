"""A small, dependency-free circuit breaker state machine.

Knows nothing about logging, metrics, or LLMs -- it only tracks
CLOSED / OPEN / HALF_OPEN state based on recorded successes and
failures. Callers are responsible for wiring it up to whatever
they're protecting (an HTTP call, an LLM router, etc.) and for
emitting their own metrics/logs on state changes.
"""

import threading
import time
from typing import Callable


class CircuitBreaker:
    """
    Tracks CLOSED / OPEN / HALF_OPEN state for a protected operation.

    - CLOSED: requests are allowed. Failures accumulate; once
      `failure_threshold` consecutive failures are recorded, the
      breaker trips to OPEN.
    - OPEN: requests are refused until `reset_timeout` seconds have
      elapsed since the breaker opened.
    - HALF_OPEN: a single trial request is allowed through. Success
      closes the breaker (and resets the failure count); failure
      reopens it.

    Thread-safe: all state reads/writes happen under an internal lock.
    """

    def __init__(
        self,
        failure_threshold: int,
        reset_timeout: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._clock = clock

        self._lock = threading.Lock()
        self._state = "CLOSED"
        self._fail_count = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def allow_request(self) -> bool:
        """
        Returns whether a request may proceed right now.

        Side effect: if the breaker is OPEN and `reset_timeout` seconds
        have elapsed since it opened, this call transitions it to
        HALF_OPEN (a single trial request) and returns True. Checking
        "may I go?" is what triggers the OPEN -> HALF_OPEN recovery
        attempt -- there is no separate background timer.
        """
        with self._lock:
            if self._state == "OPEN":
                if self._clock() - self._opened_at >= self.reset_timeout:
                    self._state = "HALF_OPEN"
                    return True
                return False
            return True

    def record_success(self) -> None:
        """A protected call succeeded: close the breaker and clear failures."""
        with self._lock:
            self._state = "CLOSED"
            self._fail_count = 0

    def record_failure(self) -> None:
        """
        A protected call failed.

        From CLOSED, failures accumulate until `failure_threshold` is
        reached, then the breaker trips OPEN. From HALF_OPEN, a single
        failure immediately reopens the breaker.
        """
        with self._lock:
            if self._state == "HALF_OPEN":
                self._state = "OPEN"
                self._fail_count = self.failure_threshold
                self._opened_at = self._clock()
                return

            self._fail_count += 1
            if self._fail_count >= self.failure_threshold:
                self._state = "OPEN"
                self._opened_at = self._clock()
