import json
import logging
from typing import Any, Optional


class JsonFormatter(logging.Formatter):
    """
    Formats log records as JSON strings.
    Includes standard LogRecord attributes as well as any 'extra' attributes.
    """

    def __init__(
        self,
        fmt: Optional[dict[str, str]] = None,
        datefmt: Optional[str] = None,
        style: str = "%",
        ensure_ascii: bool = False,
        default_json_serializer: Any = str,  # Handles non-serializable objects
        **kwargs: Any,
    ):
        r"""
        Initialize the JsonFormatter.

        Args:
            fmt (Optional[Dict[str, str]]): A dictionary mapping LogRecord attribute names
                to the desired keys in the JSON output. If None, uses default keys.
                Example: {"levelname": "level", "message": "msg"}
            datefmt (Optional[str]): Date format string, as used by time.strftime.
            style (str): '%' or '{' or '$'.
            ensure_ascii (bool): If True, all non-ASCII characters in the output are
                escaped with \uXXXX sequences.
            default_json_serializer (Any): A function to apply to objects that are not
                JSON serializable by default (e.g., datetime objects not handled by datefmt).
                Defaults to str().
            **kwargs: Additional keyword arguments for logging.Formatter.
        """
        super().__init__(datefmt=datefmt, style=style, **kwargs)  # type: ignore # validate=True for py3.10+
        self.fmt_dict = fmt if fmt is not None else {}
        self.ensure_ascii = ensure_ascii
        self.default_json_serializer = default_json_serializer

        # Default fields to include if not specified in fmt_dict
        # These are common LogRecord attributes.
        self.default_fields = {
            "timestamp": "asctime",
            "levelno": "levelno",
            "levelname": "levelname",
            "pathname": "pathname",
            "filename": "filename",
            "module": "module",
            "lineno": "lineno",
            "funcName": "funcName",
            "message": "message",  # This will be record.getMessage()
            "name": "name",
            "thread": "thread",
            "threadName": "threadName",
            "process": "process",
            "processName": "processName",
        }

    def format(self, record: logging.LogRecord) -> str:
        """
        Formats the LogRecord instance into a JSON string.
        """
        log_object: dict[str, Any] = {}

        # Use asctime from record if available (e.g., if pre-formatted by another handler)
        # Otherwise, format it ourselves.
        if hasattr(record, "asctime"):
            asctime = record.asctime
        else:
            asctime = self.formatTime(record, self.datefmt)

        # Ensure standard LogRecord attributes are available for mapping
        # record.message is the result of record.getMessage()
        # This ensures that if args were passed to the logger, they are formatted into the message.
        record.message = record.getMessage()

        # Handle standard fields based on fmt_dict or defaults
        for key, record_attr_name in self.default_fields.items():
            json_key = self.fmt_dict.get(record_attr_name, key)
            if hasattr(record, record_attr_name):
                value = getattr(record, record_attr_name)
                log_object[json_key] = value
            elif record_attr_name == "asctime":  # Special case for timestamp
                log_object[json_key] = asctime

        # Override timestamp specifically if 'asctime' was used
        if "asctime" in self.fmt_dict:
            log_object[self.fmt_dict["asctime"]] = asctime
        elif "timestamp" not in self.fmt_dict:  # if user didn't map 'timestamp' to something else
            log_object["timestamp"] = asctime

        # Include exception information if present
        if record.exc_info:
            if not record.exc_text:  # exc_text is cached by Formatter.formatException
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            json_key = self.fmt_dict.get("exc_info", "exception_info")
            log_object[json_key] = record.exc_text

        # Include stack information if present
        if record.stack_info:
            json_key = self.fmt_dict.get("stack_info", "stack_info")
            log_object[json_key] = self.formatStack(record.stack_info)

        # Include 'extra' attributes
        # These are attributes passed in the `extra` kwarg to logging calls
        # or added to the LogRecord by Filters.
        standard_attrs = list(self.default_fields.values()) + [
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "msecs",
            "msg",
            "relativeCreated",
            "stack_info",
            # Attributes used by the formatter itself
            "message",  # already handled
        ]

        extra_data: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                extra_data[key] = value

        if extra_data:
            extras_key = self.fmt_dict.get("extras", "extras")
            log_object[extras_key] = extra_data

        try:
            return json.dumps(
                log_object, ensure_ascii=self.ensure_ascii, default=self.default_json_serializer
            )
        except TypeError:
            # Fallback for very complex objects that default_json_serializer can't handle
            try:
                return json.dumps(log_object, ensure_ascii=self.ensure_ascii, default=str)
            except Exception as e:
                # If all else fails, log the error and a simplified record
                error_log = {
                    "formatter_error": f"Failed to serialize log record: {e}",
                    "original_message": record.getMessage(),
                    "logger_name": record.name,
                    "level": record.levelname,
                }
                return json.dumps(error_log)
