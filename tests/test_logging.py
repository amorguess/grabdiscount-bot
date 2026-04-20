"""Tests de app.core.logging."""

from __future__ import annotations

import io
import json
import logging

from app.core.logging import JsonFormatter, configure_logging, get_logger


def _capture(level="INFO", format="json"):
    buf = io.StringIO()
    configure_logging(level=level, format=format, stream=buf)
    return buf


def test_json_format_basic():
    buf = _capture()
    log = get_logger("test.basic")
    log.info("hello world")
    line = buf.getvalue().strip()
    obj = json.loads(line)
    assert obj["level"] == "INFO"
    assert obj["logger"] == "test.basic"
    assert obj["msg"] == "hello world"
    assert "ts" in obj


def test_json_format_extra_fields():
    buf = _capture()
    log = get_logger("test.extra")
    log.info("compte_assigné", extra={"account_id": "abc", "user_id": 42})
    obj = json.loads(buf.getvalue().strip())
    assert obj["account_id"] == "abc"
    assert obj["user_id"] == 42


def test_json_format_exception():
    buf = _capture()
    log = get_logger("test.exc")
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("caught")
    obj = json.loads(buf.getvalue().strip())
    assert obj["level"] == "ERROR"
    assert "ValueError: boom" in obj["exc"]


def test_level_filtering():
    buf = _capture(level="WARNING")
    log = get_logger("test.level")
    log.info("masqué")
    log.warning("visible")
    lines = [line for line in buf.getvalue().strip().split("\n") if line]
    assert len(lines) == 1
    assert json.loads(lines[0])["msg"] == "visible"


def test_text_format_colorize_off_when_not_tty():
    buf = _capture(format="text")
    log = get_logger("test.text")
    log.info("plain")
    out = buf.getvalue()
    assert "plain" in out
    # buf n'est pas un TTY → pas de codes ANSI
    assert "\033[" not in out


def test_configure_logging_is_idempotent():
    buf1 = _capture()
    buf2 = _capture()
    log = get_logger("test.idem")
    log.info("unique")
    assert buf1.getvalue() == ""
    assert "unique" in buf2.getvalue()


def test_noisy_libs_set_to_warning():
    _capture()
    for name in ("httpx", "httpcore", "urllib3", "telegram", "werkzeug"):
        assert logging.getLogger(name).level == logging.WARNING


def test_json_formatter_direct():
    fmt = JsonFormatter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="f.py",
        lineno=1,
        msg="msg %s",
        args=("arg",),
        exc_info=None,
    )
    record.custom_field = "yes"
    obj = json.loads(fmt.format(record))
    assert obj["msg"] == "msg arg"
    assert obj["custom_field"] == "yes"


def test_auto_format_picks_text_on_tty():
    class FakeTTY:
        def isatty(self):
            return True

        def write(self, *_a, **_k):
            return 0

        def flush(self):
            pass

    tty = FakeTTY()
    configure_logging(format="auto", stream=tty)
    root = logging.getLogger()
    handler = root.handlers[0]
    from app.core.logging import TextFormatter

    assert isinstance(handler.formatter, TextFormatter)
