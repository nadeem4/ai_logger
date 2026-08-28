import json
import logging

from logscribe.utils.json_formatter import JsonFormatter


def make_record(msg="hello", level=logging.INFO, exc_info=None):
    return logging.LogRecord("t", level, "f.py", 1, msg, None, exc_info)


def test_output_is_valid_json_with_core_fields():
    out = json.loads(JsonFormatter().format(make_record()))
    assert out["message"] == "hello"
    assert out["levelname"] == "INFO"
    assert "levelno" in out  # router severity selection depends on this


def test_exception_info_included():
    try:
        1 / 0
    except ZeroDivisionError:
        import sys

        rec = make_record("boom", logging.ERROR, sys.exc_info())
    out = json.loads(JsonFormatter().format(rec))
    assert "ZeroDivisionError" in json.dumps(out)


def test_preformatted_asctime_is_used_verbatim():
    # If another handler/filter already set record.asctime, JsonFormatter
    # must reuse it rather than recomputing the timestamp itself.
    rec = make_record()
    rec.asctime = "2020-01-01 00:00:00,000"
    out = json.loads(JsonFormatter().format(rec))
    assert out["timestamp"] == "2020-01-01 00:00:00,000"


def test_custom_fmt_maps_field_names():
    out = json.loads(
        JsonFormatter(fmt={"levelname": "severity", "message": "log_message"}).format(
            make_record("hi")
        )
    )
    assert out["severity"] == "INFO"
    assert out["log_message"] == "hi"
    assert "levelname" not in out
    assert "message" not in out


def test_custom_fmt_remaps_asctime_key():
    rec = make_record()
    out = json.loads(JsonFormatter(fmt={"asctime": "eventTimestamp"}).format(rec))
    assert "eventTimestamp" in out
    assert "timestamp" not in out


def test_stack_info_included_when_present():
    rec = logging.LogRecord(
        "t", logging.INFO, "f.py", 1, "hi", None, None, sinfo="Stack (most recent call last):\n"
    )
    out = json.loads(JsonFormatter().format(rec))
    assert "stack_info" in out
    assert "Stack (most recent call last)" in out["stack_info"]


def test_extra_fields_land_under_extras_key():
    logger = logging.getLogger("json_formatter_extras_test")
    record = logger.makeRecord(
        "json_formatter_extras_test",
        logging.INFO,
        "f.py",
        1,
        "hi",
        None,
        None,
        extra={"user_id": "u1"},
    )
    out = json.loads(JsonFormatter().format(record))
    assert out["extras"]["user_id"] == "u1"


def test_ensure_ascii_true_escapes_non_ascii():
    out_escaped = JsonFormatter(ensure_ascii=True).format(make_record("café"))
    assert "\\u00e9" in out_escaped
    out_raw = JsonFormatter(ensure_ascii=False).format(make_record("café"))
    assert "café" in out_raw


def test_non_json_serializable_extra_uses_default_serializer():
    class Point:
        def __str__(self):
            return "Point(1,2)"

    logger = logging.getLogger("json_formatter_serializer_test")
    record = logger.makeRecord(
        "json_formatter_serializer_test",
        logging.INFO,
        "f.py",
        1,
        "hi",
        None,
        None,
        extra={"where": Point()},
    )
    out = json.loads(JsonFormatter().format(record))
    assert out["extras"]["where"] == "Point(1,2)"


def test_total_serialization_failure_falls_back_to_error_record():
    class Unstringable:
        def __str__(self):
            raise RuntimeError("cannot stringify")

    def exploding_serializer(_obj):
        raise TypeError("cannot serialize")

    logger = logging.getLogger("json_formatter_total_failure_test")
    record = logger.makeRecord(
        "json_formatter_total_failure_test",
        logging.ERROR,
        "f.py",
        1,
        "boom",
        None,
        None,
        extra={"bad": Unstringable()},
    )
    out = json.loads(JsonFormatter(default_json_serializer=exploding_serializer).format(record))
    assert "formatter_error" in out
    assert out["original_message"] == "boom"
    assert out["logger_name"] == "json_formatter_total_failure_test"
    assert out["level"] == "ERROR"
