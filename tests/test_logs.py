"""`logs.configure_logging`: JSON lines with the fixed fields, and nothing else."""

import io
import json
import logging
from collections.abc import Iterator

import pytest

from asmbly_ceramics.logs import BASE_FIELDS, FIELDS, LIBRARY_LOGGERS, configure_logging
from asmbly_ceramics.use_cases.log import LOG_FIELDS, log_event
from tests.domain.builders import TEST_EMAIL, TEST_NAME, TEST_PHONE


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    levels = {name: logging.getLogger(name).level for name in LIBRARY_LOGGERS}
    out = io.StringIO()
    configure_logging("INFO", "abc1234", out)
    yield out
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved[0]:
        root.addHandler(handler)
    root.setLevel(saved[1])
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)


def lines(out: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_the_field_list_is_the_contract() -> None:
    assert BASE_FIELDS == ("level", "logger", "message", "version")
    assert {*BASE_FIELDS, *LOG_FIELDS} == FIELDS
    assert {"event", "drop_off_id", "error_code", "user"} <= LOG_FIELDS


def test_lines_are_json_with_the_fixed_fields(stream: io.StringIO) -> None:
    log_event(
        "email_failed", level=logging.ERROR, drop_off_id="AC-12", error_code="photo_missing", kind="received"
    )
    [line] = lines(stream)
    assert line == {
        "level": "ERROR",
        "logger": "asmbly_ceramics",
        "message": "email_failed",
        "version": "abc1234",
        "event": "email_failed",
        "drop_off_id": "AC-12",
        "error_code": "photo_missing",
        "kind": "received",
    }


def test_unknown_extra_fields_are_dropped(stream: io.StringIO) -> None:
    logging.getLogger("asmbly_ceramics").info("submitted", extra={"email": TEST_EMAIL, "drop_off_id": "AC-3"})
    [line] = lines(stream)
    assert set(line) <= FIELDS
    assert line["drop_off_id"] == "AC-3"
    assert TEST_EMAIL not in stream.getvalue()


def test_a_message_s_arguments_and_traceback_are_never_written(stream: io.StringIO) -> None:
    other = logging.getLogger("some.library")
    other.warning("sending %s %s", TEST_NAME, TEST_PHONE)
    try:
        raise ValueError(TEST_EMAIL)
    except ValueError:
        other.exception("failed for %s", TEST_EMAIL)
    first, second = lines(stream)
    assert first["message"] == "sending %s %s"
    assert first["event"] == "unstructured"  # so the logged-errors filter sees it
    assert second["error_code"] == "ValueError"
    text = stream.getvalue()
    for detail in (TEST_NAME, TEST_PHONE, TEST_EMAIL, "Traceback"):
        assert detail not in text


def test_a_message_that_isn_t_a_string_is_written_by_its_type(stream: io.StringIO) -> None:
    logging.getLogger("some.library").warning({"email": TEST_EMAIL})
    [line] = lines(stream)
    assert line["message"] == "dict"
    assert TEST_EMAIL not in stream.getvalue()


def test_library_loggers_are_floored_at_info() -> None:
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    try:
        configure_logging("DEBUG", "abc1234", io.StringIO())
        for name in LIBRARY_LOGGERS:
            assert logging.getLogger(name).getEffectiveLevel() >= logging.INFO
        assert len(root.handlers) == 1
        for name in ("uvicorn", "uvicorn.error"):
            assert logging.getLogger(name).handlers == []
            assert logging.getLogger(name).propagate
        assert not logging.getLogger("uvicorn.access").hasHandlers()  # no access log
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved[0]:
            root.addHandler(handler)
        root.setLevel(saved[1])
        for name in LIBRARY_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)


def test_a_library_s_pre_formatted_message_is_withheld(stream: io.StringIO) -> None:
    logging.getLogger("some.library").warning(f"sending to {TEST_EMAIL}")
    [line] = lines(stream)
    assert line["message"] == "(a library's message, withheld)"
    assert TEST_EMAIL not in stream.getvalue()


def test_a_photo_s_exif_never_reaches_the_log_even_at_debug() -> None:
    from PIL import Image

    from asmbly_ceramics.adapters.images import PillowPhotoInspector

    marker = "Made Up Photographer"
    exif = Image.Exif()
    exif[0x013B] = marker  # Artist
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buffer, "JPEG", exif=exif)
    out = io.StringIO()
    root = logging.getLogger()
    saved = list(root.handlers), root.level
    try:
        configure_logging("DEBUG", "abc1234", out)
        PillowPhotoInspector().inspect(buffer.getvalue())
        logging.getLogger("asmbly_ceramics").debug("app debug kept")
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved[0]:
            root.addHandler(handler)
        root.setLevel(saved[1])
        for name in LIBRARY_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)
    assert marker not in out.getvalue()
    assert "app debug kept" in out.getvalue()
