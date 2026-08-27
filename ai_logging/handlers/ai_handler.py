import logging
import time
import threading
from typing import List, Dict, Any, Optional, Callable
import jinja2
import traceback

from ..config.settings import get_settings
from ..router.llm_router import LLMRouter
from ..utils.json_formatter import JsonFormatter
from ..utils.pii_filter import scrub_pii_from_dict
from ..metrics.prometheus import get_metrics_instance

class AIHandler(logging.Handler):
    """
    A logging handler that processes log records, batches them,
    formats them as JSON, scrubs PII, builds prompts using Jinja2,
    routes them to an AI model via LangChain's LLMRouter,
    and handles the AI's response.

    Supports micro-batching, circuit-breaking, retry logic,
    and Prometheus metrics.
    """

    def __init__(self,
                 level: int = logging.NOTSET,
                 batch_size: Optional[int] = None,
                 flush_interval: Optional[float] = None,
                 max_retries: Optional[int] = None,
                 retry_backoff_factor: Optional[float] = None,
                 settings=None,
                 llm_router=None,
                 pii_scrubber=None,
                 ai_response_callback: Optional[Callable[[Any], None]] = None
                 ) -> None:
        super().__init__(level)
        self.settings = settings or get_settings()
        self.batch_size = batch_size if batch_size is not None else self.settings.ai_logging_batch_size
        self.flush_interval = flush_interval if flush_interval is not None else self.settings.ai_logging_flush_interval_seconds
        self.max_retries = max_retries if max_retries is not None else self.settings.ai_logging_max_retries
        self.retry_backoff_factor = retry_backoff_factor if retry_backoff_factor is not None else self.settings.ai_logging_retry_backoff_factor

        self.llm_router = llm_router or LLMRouter(self.settings)
        self.pii_scrubber = pii_scrubber or (lambda data: scrub_pii_from_dict(
            data,
            custom_rules=self.settings.ai_logging_pii_rules_json,
            use_default_rules=self.settings.ai_logging_pii_use_default_rules
        ))
        self.ai_response_callback = ai_response_callback or self._default_ai_response_logger

        self._buffer: List[logging.LogRecord] = []
        self._buffer_lock = threading.Lock()
        self._last_flush_time = time.time()

        self._flush_timer: Optional[threading.Timer] = None

        # Circuit breaker state
        self.circuit_breaker_state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.circuit_breaker_fail_count = 0
        self.circuit_breaker_open_until = 0

        # Prometheus metrics
        self.metrics = get_metrics_instance()

        # Jinja2 environment and template
        if self.settings.ai_logging_jinja_template_dir:
            loader = jinja2.FileSystemLoader(self.settings.ai_logging_jinja_template_dir)
        else:
            # Default to loading templates from a 'templates' directory within the package
            loader = jinja2.PackageLoader('ai_logging', 'templates')

        self.jinja_env = jinja2.Environment(
            loader=loader,
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True
        )
        try:
            self.jinja_template = self.jinja_env.get_template(self.settings.ai_logging_jinja_log_prompt_template_name)
        except jinja2.TemplateNotFound:
            logging.getLogger(__name__).warning(
                f"Jinja2 template '{self.settings.ai_logging_jinja_log_prompt_template_name}' not found. "
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
                "{% if log.exception %}Exception: {{ log.exception }}{% endif %}\n"
                "---\n"
                "{% endfor %}"
            )

        # Start the periodic flush timer last, once the instance is fully
        # constructed, so a short flush_interval can never fire the timer
        # into a half-initialized object.
        self._start_flush_timer()

    def _start_flush_timer(self) -> None:
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

    def prepare_record_for_processing(self, record: logging.LogRecord) -> Dict[str, Any]:
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
                "timestamp": self.formatter.formatTime(record, self.formatter.datefmt) if self.formatter else record.created
            }
        return log_data

    def _process_batch(self, batch: List[logging.LogRecord]) -> None:
        if not batch:
            return

        self.metrics.ai_handler_batches_processed_total.inc()
        self.metrics.ai_handler_batch_size_bytes.observe(len(batch))

        processed_records: List[Dict[str, Any]] = []
        highest_severity = 0
        for record in batch:
            formatted_record = self.prepare_record_for_processing(record)
            scrubbed_data = self.pii_scrubber(formatted_record)
            processed_records.append(scrubbed_data)
            if record.levelno > highest_severity:
                highest_severity = record.levelno

        prompt = self._build_prompt_with_jinja(processed_records)

        if self.circuit_breaker_state == "OPEN" and time.time() < self.circuit_breaker_open_until:
            self.metrics.ai_calls_total.inc(model_name="N/A", status="circuit_open")
            return

        attempt = 0
        succeeded = False
        while attempt <= self.max_retries:
            try:
                start_time = time.time()
                ai_response = self.llm_router.route_prompt(prompt, processed_records)
                latency = time.time() - start_time
                self.metrics.ai_calls_total.inc(model_name="llm", status="success")
                self.metrics.ai_call_latency_seconds.observe(latency, model_name="llm")
                if self.circuit_breaker_state == "HALF_OPEN":
                    self.circuit_breaker_state = "CLOSED"
                    self.circuit_breaker_fail_count = 0
                self._handle_ai_response(ai_response)
                succeeded = True
                break
            except Exception as e:
                self.metrics.ai_calls_total.inc(model_name="llm", status="error")
                self.metrics.ai_call_errors_total.inc(model_name="llm", error_type=type(e).__name__)
                self.circuit_breaker_fail_count += 1
                if self.circuit_breaker_fail_count >= 3:
                    self.circuit_breaker_state = "OPEN"
                    self.circuit_breaker_open_until = time.time() + 60  # Open for 60 seconds
                    self.metrics.ai_circuit_breaker_state_changes_total.inc(model_name="llm", new_state="OPEN")
                    self.metrics.ai_circuit_breaker_currently_open.set(1, model_name="llm")
                # Only back off if another attempt is actually going to happen.
                if attempt < self.max_retries:
                    backoff = self.retry_backoff_factor * (2 ** attempt)
                    time.sleep(backoff)
                attempt += 1

        if not succeeded:
            # All retries failed (or max_retries == 0 and the single attempt failed).
            self.metrics.ai_circuit_breaker_state_changes_total.inc(model_name="llm", new_state="OPEN")
            self.metrics.ai_circuit_breaker_currently_open.set(1, model_name="llm")

    def _build_prompt_with_jinja(self, records: List[Dict[str, Any]]) -> str:
        try:
            return self.jinja_template.render(logs=records)
        except Exception as e:
            return f"Log Summary: {len(records)} entries. First message: {records[0]['message'] if records else 'N/A'} (Template error: {e})"

    def _handle_ai_response(self, response: Any) -> None:
        if self.ai_response_callback:
            self.ai_response_callback(response)
        else:
            self._default_ai_response_logger(response)

    def _default_ai_response_logger(self, response: Any) -> None:
        ai_response_logger = logging.getLogger(self.settings.ai_logging_ai_response_log_logger_name)
        if not ai_response_logger.handlers:
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter('%(asctime)s - AI_RESPONSE - %(message)s'))
            ai_response_logger.addHandler(ch)
            ai_response_logger.propagate = False
        ai_response_logger.info(str(response))

    def flush(self) -> None:
        self._last_flush_time = time.time()
        records_to_process: List[logging.LogRecord] = []
        with self._buffer_lock:
            if not self._buffer:
                return
            records_to_process = self._buffer
            self._buffer = []
        if records_to_process:
            try:
                self._process_batch(records_to_process)
            except Exception:
                # handleError(None) is unsafe: logging.Handler.handleError
                # accesses record attributes and can itself raise when record
                # is None. A router/processing failure must never escape the
                # handler, so log it defensively instead.
                try:
                    logging.getLogger(__name__).exception(
                        "AIHandler failed to process a batch of %d record(s)",
                        len(records_to_process),
                    )
                except Exception:
                    pass

    def close(self) -> None:
        if self._flush_timer:
            self._flush_timer.cancel()
            self._flush_timer = None
        self.flush()
        super().close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    ai_handler = AIHandler(batch_size=3, flush_interval=5.0)
    ai_handler.setLevel(logging.INFO)

    demo_logger = logging.getLogger("ai_logging.demo_ai_handler")
    demo_logger.setLevel(logging.DEBUG)
    demo_logger.addHandler(ai_handler)
    demo_logger.propagate = False

    print(f"AIHandler demo: Batch size = {ai_handler.batch_size}, Flush interval = {ai_handler.flush_interval}s")

    demo_logger.debug("This is a DEBUG message (should be ignored by AIHandler).")
    demo_logger.info("User 'john.doe@example.com' logged in.")
    time.sleep(0.1)
    demo_logger.warning("API key 'sk-12345secretkey' might be exposed.")
    time.sleep(0.1)
    demo_logger.info("Processing payment for order #98765.")

    demo_logger.error("Failed to connect to database 'prod_db' at '10.0.0.1'.")

    print(f"AIHandler demo: Waiting for timed flush ({ai_handler.flush_interval}s)...")
    try:
        time.sleep(ai_handler.flush_interval + 1)
    except KeyboardInterrupt:
        print("AIHandler demo: Interrupted.")

    demo_logger.info("Final message before closing.")

    print("AIHandler demo: Closing AIHandler...")
    ai_handler.close()

    demo_logger.removeHandler(ai_handler)
    print("AIHandler demo complete.")
