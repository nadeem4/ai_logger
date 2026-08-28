import json, logging
from loglens.utils.json_formatter import JsonFormatter


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
