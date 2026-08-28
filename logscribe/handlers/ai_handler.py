import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import jinja2

from ..config.settings import get_settings
from ..metrics.prometheus import get_metrics_instance
from ..router.llm_router import LLMRouter
from ..utils.circuit_breaker import CircuitBreaker
from ..utils.json_formatter import JsonFormatter
from ..utils.pii_filter import scrub_pii_from_dict


class AIHandler(logging.Handler):
    """
    A logging handler that processes log records, batches them,
    formats them as JSON, scrubs PII, builds prompts using Jinja2,
    routes them to an AI model via LangChain's LLMRouter,
    and handles the AI's response.

    Supports micro-batching, circuit-breaking, retry logic,
    and Prometheus metrics.
    """

    def __init__(
        self,
        level: int = logging.NOTSET,
        batch_size: int | None = None,
        flush_interval: float | None = None,
        max_retries: int | None = None,
        retry_backoff_factor: float | None = None,
        settings=None,
        llm_router=None,
        pii_scrubber=None,
        ai_response_callback: Callable[[Any], None] | None = None,
    ) -> None:
        super().__init__(level)
        self.settings = settings or get_settings()
        self.batch_size = (
            batch_size if batch_size is not None else self.settings.logscribe_batch_size
        )
        self.flush_interval = (
            flush_interval
            if flush_interval is not None
            else self.settings.logscribe_flush_interval_seconds
        )
        self.max_retries = (
            max_retries if max_retries is not None else self.settings.logscribe_max_retries
        )
        self.retry_backoff_factor = (
            retry_backoff_factor
            if retry_backoff_factor is not None
            else self.settings.logscribe_retry_backoff_factor
        )

        self.llm_router = llm_router or LLMRouter(self.settings)
        self.pii_scrubber = pii_scrubber or (
            lambda data: scrub_pii_from_dict(
                data,
                custom_rules=self.settings.logscribe_pii_rules_json,
                use_default_rules=self.settings.logscribe_pii_use_default_rules,
            )
        )
        self.ai_response_callback = ai_response_callback or self._default_ai_response_logger

        self._buffer: list[logging.LogRecord] = []
        self._buffer_lock = threading.Lock()
        self._last_flush_time = time.time()

        self._flush_timer: threading.Timer | None = None
        self._closed = False
        self._closed_lock = threading.Lock()

        # Background worker: emit()/flush() only ever enqueue batches here.
        # A single daemon thread drains the queue and calls _process_batch,
        # so the AI call (and any retry backoff sleep) never runs on the
        # caller's thread. Exactly one worker -- the circuit breaker's
        # allow_request()/record_success()/record_failure() sequence in
        # _process_batch is only safe with batches processed serially.
        self._work_q: queue.Queue = queue.Queue()
        # Guards against silently dropping batches once the worker is gone
        # (it exited after a prior close(), or -- in principle -- died).
        # A dead worker is logged once, not once per dropped batch.
        self._worker_dead_logged = False
        self._worker_dead_lock = threading.Lock()

        # Circuit breaker: protects the router call from repeatedly hammering
        # a failing LLM provider. See logscribe/utils/circuit_breaker.py.
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.settings.logscribe_cb_failure_threshold,
            reset_timeout=self.settings.logscribe_cb_reset_timeout_seconds,
        )

        # Prometheus metrics
        self.metrics = get_metrics_instance()

        # Jinja2 environment and template
        loader: jinja2.BaseLoader
        if self.settings.logscribe_jinja_template_dir:
            loader = jinja2.FileSystemLoader(self.settings.logscribe_jinja_template_dir)
        else:
            # Default to loading templates from a 'templates' directory within the package
            loader = jinja2.PackageLoader("logscribe", "templates")

        self.jinja_env = jinja2.Environment(
            loader=loader,
            # The rendered output is a plaintext prompt for an LLM, not
            # HTML: escaping would mangle the JSON, SQL, XML and quoted
            # strings that are the most valuable part of a log line.
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        try:
            self.jinja_template = self.jinja_env.get_template(
                self.settings.logscribe_jinja_log_prompt_template_name
            )
        except jinja2.TemplateNotFound:
            logging.getLogger(__name__).warning(
                f"Jinja2 template '{self.settings.logscribe_jinja_log_prompt_template_name}' not found. "
                f"Using a basic fallback template. Searched in: {loader}"
            )
            # Fallback to a simple default template string
            self.jinja_template = jinja2.Template(
                "Log Batch Summary:\n"
                "Total Records: {{ logs|length }}\n\n"
                "{% for log in logs %}"
                "Level: {{ log.levelname }}\n"
                "Timestamp: {{ log.timestamp }}\n"
                "Message: {{ log.message }}\n"
                "{% if log.exception_info %}Exception: {{ log.exception_info }}{% endif %}\n"
                "---\n"
                "{% endfor %}"
            )

        # Start the worker thread and the periodic flush timer last, once
        # the instance is fully constructed, so a short flush_interval (or
        # an immediate batch-size flush) can never run against a
        # half-initialized object.
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        self._start_flush_timer()

    def _start_flush_timer(self) -> None:
        with self._closed_lock:
            if self._closed:
                # close() has already run (or is running concurrently and
                # owns this same lock). Never re-arm a timer on a closed
                # handler, even if a Timer thread is mid-flight here having
                # raced past close()'s own cancel().
                return
            if self._flush_timer:
                self._flush_timer.cancel()
            self._flush_timer = threading.Timer(self.flush_interval, self._timed_flush)
            self._flush_timer.daemon = True
            self._flush_timer.start()

    def _timed_flush(self) -> None:
        self.flush()  # flush() checks the buffer under the lock itself
        self._start_flush_timer()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            should_flush = False
            with self._buffer_lock:
                self._buffer.append(record)
                self.metrics.ai_handler_records_processed_total.inc()
                if len(self._buffer) >= self.batch_size:
                    should_flush = True
            if should_flush:
                self.flush()  # flush() checks the buffer under the lock itself
        except Exception:
            self.handleError(record)

    def prepare_record_for_processing(self, record: logging.LogRecord) -> dict[str, Any]:
        if not self.formatter:
            self.formatter = JsonFormatter()
        json_str = self.formatter.format(record)
        try:
            import json

            log_data = json.loads(json_str)
        except Exception:
            log_data = {
                "message": record.getMessage(),
                "levelname": record.levelname,
                "timestamp": self.formatter.formatTime(record, self.formatter.datefmt)
                if self.formatter
                else record.created,
            }
        return log_data

    def _process_batch(self, batch: list[logging.LogRecord]) -> None:
        if not batch:
            return

        self.metrics.ai_handler_batches_processed_total.inc()
        self.metrics.ai_handler_batch_size_records.observe(len(batch))

        processed_records: list[dict[str, Any]] = []
        highest_severity = 0
        for record in batch:
            formatted_record = self.prepare_record_for_processing(record)
            scrubbed_data = self.pii_scrubber(formatted_record)
            processed_records.append(scrubbed_data)
            if record.levelno > highest_severity:
                highest_severity = record.levelno

        prompt = self._build_prompt_with_jinja(processed_records)

        # allow_request() has a side effect: if the breaker is OPEN and its
        # reset timeout has elapsed, calling it transitions the breaker to
        # HALF_OPEN (allowing this one trial call through) and returns True.
        if not self.circuit_breaker.allow_request():
            self.metrics.ai_calls_total.labels(model="N/A", status="circuit_open").inc()
            return

        attempt = 0
        succeeded = False
        no_provider = False
        while attempt <= self.max_retries:
            try:
                start_time = time.time()
                ai_response = self.llm_router.route_prompt(prompt, processed_records)
                latency = time.time() - start_time
                if ai_response is None:
                    # The router returns None when no provider is
                    # configured: no AI call was made at all. Counting that
                    # as a success (with its sub-millisecond "latency", a
                    # breaker success and a callback invocation) would make
                    # a dashboard report 100% healthy AI calls for a
                    # deployment that is making none. Count it honestly and
                    # leave the breaker and the callback alone.
                    self.metrics.ai_calls_total.labels(model="llm", status="no_provider").inc()
                    no_provider = True
                    break
                self.metrics.ai_calls_total.labels(model="llm", status="success").inc()
                self.metrics.ai_call_latency_seconds.labels(model="llm").observe(latency)
                self._handle_ai_response(ai_response)
                succeeded = True
                break
            except Exception as e:
                self.metrics.ai_calls_total.labels(model="llm", status="error").inc()
                self.metrics.ai_call_errors_total.labels(
                    model="llm", error_type=type(e).__name__
                ).inc()
                # Only back off if another attempt is actually going to happen.
                if attempt < self.max_retries:
                    backoff = self.retry_backoff_factor * (2**attempt)
                    time.sleep(backoff)
                attempt += 1

        if no_provider:
            # No AI call was attempted, so there is no outcome to record
            # against the breaker in either direction.
            return

        # Record the batch's outcome against the breaker once, after the
        # retry loop is done -- not once per attempt. A batch that exhausts
        # its retries is one failure from the breaker's point of view, so a
        # single flaky batch can't trip a threshold-3 breaker by itself; the
        # breaker instead tracks failures across consecutive *batches*.
        state_before = self.circuit_breaker.state
        if succeeded:
            self.circuit_breaker.record_success()
        else:
            self.circuit_breaker.record_failure()
        state_after = self.circuit_breaker.state

        if state_after != state_before:
            self.metrics.ai_circuit_breaker_state_changes_total.labels(
                model="llm", new_state=state_after
            ).inc()
            self.metrics.ai_circuit_breaker_currently_open.labels(model="llm").set(
                1 if state_after == "OPEN" else 0
            )

    def _build_prompt_with_jinja(self, records: list[dict[str, Any]]) -> str:
        try:
            return self.jinja_template.render(logs=records)
        except Exception as e:
            return f"Log Summary: {len(records)} entries. First message: {records[0]['message'] if records else 'N/A'} (Template error: {e})"

    def _handle_ai_response(self, response: Any) -> None:
        # __init__ always sets ai_response_callback (to the caller's
        # callback, or to _default_ai_response_logger as a fallback), so it
        # is never falsy here; there is no "else" branch to fall back to.
        self.ai_response_callback(response)

    def _default_ai_response_logger(self, response: Any) -> None:
        ai_response_logger = logging.getLogger(self.settings.logscribe_ai_response_log_logger_name)
        if not ai_response_logger.handlers:
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter("%(asctime)s - AI_RESPONSE - %(message)s"))
            ai_response_logger.addHandler(ch)
            ai_response_logger.propagate = False
        ai_response_logger.info(str(response))

    def flush(self) -> None:
        """Public flush: drains the buffer to the worker unless close() has
        already begun.

        The _closed gate matters because close() enqueues a None sentinel
        that stops the worker. A flush() that only checked
        _worker.is_alive() would pass (the worker is still draining) and
        put() its batch *behind* that sentinel, where the worker never
        reaches it -- a silent loss, invisible even to the dead-worker
        warning. Once _closed is set, the enqueue path is refused and the
        batch takes the existing log-and-drop branch instead.

        _closed is read under _closed_lock and the lock released before
        anything else happens: no lock is ever held across put(), join()
        or _process_batch.
        """
        with self._closed_lock:
            closed = self._closed
        self._drain_buffer_to_worker(enqueue_allowed=not closed)

    def _drain_buffer_to_worker(self, enqueue_allowed: bool) -> None:
        """Shared drain used by flush() and by close()'s own final flush.

        close() sets _closed before it drains, so it calls this directly
        with enqueue_allowed=True to bypass the gate flush() applies --
        close() enqueues its last batch *before* the sentinel, so that
        batch is genuinely processed.
        """
        self._last_flush_time = time.time()
        records_to_process: list[logging.LogRecord] = []
        with self._buffer_lock:
            if not self._buffer:
                return
            records_to_process = self._buffer
            self._buffer = []
        # put() happens outside _buffer_lock: it never blocks in practice
        # (the queue is unbounded) but nothing that runs under
        # _buffer_lock may re-enter -- this file has already been bitten
        # twice by that class of deadlock.
        if records_to_process:
            # A put() onto a queue whose only consumer has already exited
            # (the worker returned after a prior close(), or -- in
            # principle -- died) would sit there forever with nothing to
            # observe it: a silent, permanent loss. Gate on liveness and
            # log instead, once, rather than swallowing the batch.
            if enqueue_allowed and self._worker.is_alive():
                self._work_q.put(records_to_process)
            else:
                self._log_worker_dead_once(len(records_to_process))

    def _log_worker_dead_once(self, dropped_count: int) -> None:
        with self._worker_dead_lock:
            if self._worker_dead_logged:
                return
            self._worker_dead_logged = True
        try:
            logging.getLogger(__name__).warning(
                "AIHandler is closed or its worker thread is no longer "
                "running; dropping a batch of %d record(s) instead of "
                "enqueuing it (further drops will not be logged "
                "individually)",
                dropped_count,
            )
        except Exception:
            pass

    def _worker_loop(self) -> None:
        """Runs on the single background worker thread. Pulls one batch at
        a time off the queue and processes it, so the AI call (and any
        retry backoff sleep) never blocks the caller's thread. A None
        sentinel, enqueued by close(), ends the loop.

        The whole loop body -- not just the _process_batch call -- is
        guarded so a surprise exception can never kill this thread; if it
        died, every batch enqueued afterward would be silently dropped
        (see flush()'s liveness check, which logs exactly that if it ever
        happens). SystemExit/KeyboardInterrupt are treated as genuinely
        fatal and re-raised rather than swallowed.
        """
        while True:
            try:
                batch = self._work_q.get()
                if batch is None:
                    return
                try:
                    self._process_batch(batch)
                except Exception:
                    # handleError(None) is unsafe: logging.Handler.handleError
                    # accesses record attributes and can itself raise when record
                    # is None. A router/processing failure must never escape the
                    # handler (nor kill the worker thread), so log it
                    # defensively instead.
                    try:
                        logging.getLogger(__name__).exception(
                            "AIHandler worker failed to process a batch of %d record(s)",
                            len(batch),
                        )
                    except Exception:
                        pass
            except (SystemExit, KeyboardInterrupt):
                raise
            except BaseException:
                try:
                    logging.getLogger(__name__).exception(
                        "AIHandler worker loop encountered an unexpected error; continuing"
                    )
                except Exception:
                    pass

    def close(self) -> None:
        with self._closed_lock:
            already_closed = self._closed
            self._closed = True
            if self._flush_timer:
                self._flush_timer.cancel()
                self._flush_timer = None
        if already_closed:
            # Second close() (logging.shutdown() calls close() on every
            # handler at interpreter exit, on top of any explicit call).
            # The worker was already stopped and joined by the first call;
            # enqueuing a second sentinel would leave an item sitting in
            # the queue that the drop backstop below would then report as
            # lost work.
            super().close()
            return
        # Bypass flush()'s _closed gate: _closed is already True, but
        # close()'s own drain runs before the sentinel is enqueued, so its
        # batch is still processed.
        self._drain_buffer_to_worker(enqueue_allowed=True)
        self._work_q.put(None)
        # Bounded join: an unbounded join on a wedged provider call would
        # hang interpreter shutdown. Capped at 60s regardless of
        # flush_interval -- flush_interval + 30 could otherwise be an hour
        # for a handler configured with a large flush_interval, which
        # would block logging.shutdown() for that long. Safe to call
        # close() twice -- a second call returns at the already_closed
        # check above without re-enqueuing or re-joining.
        self._worker.join(min(self.flush_interval + 30, 60))
        if self._worker.is_alive():
            # join() timed out: the worker is wedged (almost certainly in
            # the AI call or its retry backoff) and was not observed to
            # finish. qsize() undercounts by one if a batch is mid-flight
            # inside _process_batch right now, but it's the best estimate
            # available without new machinery.
            try:
                logging.getLogger(__name__).warning(
                    "AIHandler worker did not stop within the shutdown "
                    "timeout; approximately %d batch(es) (plus any batch "
                    "currently being processed) may be left unprocessed",
                    self._work_q.qsize(),
                )
            except Exception:
                pass
        # Backstop: anything still queued after the join was never
        # processed (a batch that raced the _closed gate, or work the
        # wedged worker never reached). Make that loss visible instead of
        # letting it disappear with the process.
        leftover = self._work_q.qsize()
        if leftover > 0:
            try:
                logging.getLogger(__name__).warning(
                    "AIHandler closed with %d item(s) still queued; those "
                    "record batches were dropped without being sent to the "
                    "AI provider",
                    leftover,
                )
            except Exception:
                pass
        super().close()
