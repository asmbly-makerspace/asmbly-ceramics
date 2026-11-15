"""The daily close's handler (#7): one `CloseFinished` run, its count, and a failed run raising."""

import logging
from types import SimpleNamespace

import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.entry import close as entry
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.settings import SettingsError
from tests.domain.builders import TEST_EMAIL, TEST_NAME, TEST_PHONE
from tests.use_cases.conftest import World
from tests.use_cases.conftest import world as world  # the fakes and use cases
from tests.use_cases.test_close import WINDOW_ENDS, at, fired_and_emailed, stored

AC_1, AC_2 = DropOffId(1), DropOffId(2)


@pytest.fixture(autouse=True)
def closer(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entry, "_closer", world.close)


def test_the_handler_closes_what_is_due_and_logs_ids_only(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    fired_and_emailed(world, 1, 2)
    at(world, WINDOW_ENDS)
    caplog.clear()

    assert entry.handler({}, None) == {"closed": 2}

    assert stored(world, AC_1).state is DropOffState.CLOSED
    assert stored(world, AC_2).state is DropOffState.CLOSED
    lines = [r for r in caplog.records if r.name == "asmbly_ceramics"]
    assert [r.getMessage() for r in lines] == ["drop_off_closed", "drop_off_closed", "close_run"]
    for record in lines:
        text = repr(vars(record))
        for detail in (TEST_NAME, TEST_EMAIL, TEST_PHONE):
            assert detail not in text


def test_a_run_with_nothing_to_close_does_nothing_and_succeeds(world: World) -> None:
    fired_and_emailed(world, 1)
    commits = len(world.records.commits)
    assert entry.handler({}, None) == {"closed": 0}
    assert len(world.records.commits) == commits
    assert world.photos.kept_count(AC_1) > 0


def test_running_twice_is_harmless(world: World) -> None:
    fired_and_emailed(world, 1)
    at(world, WINDOW_ENDS)
    assert entry.handler({}, None) == {"closed": 1}
    commits = len(world.records.commits)

    assert entry.handler({}, None) == {"closed": 0}
    assert len(world.records.commits) == commits


def test_a_failure_on_one_drop_off_does_not_stop_the_others_and_the_run_fails_at_the_end(
    world: World,
) -> None:
    fired_and_emailed(world, 1, 2)
    at(world, WINDOW_ENDS)
    world.records.fail_next_commit_with = RecordsUnavailable("InternalServerError")

    with pytest.raises(entry.CloseRunError) as raised:
        entry.handler({}, None)

    assert raised.value.failed == 1
    states = {stored(world, AC_1).state, stored(world, AC_2).state}
    assert states == {DropOffState.FIRED, DropOffState.CLOSED}  # the other one closed
    assert entry.handler({}, None) == {"closed": 1}  # the retry closes the one left


def test_the_event_content_is_ignored(world: World) -> None:
    fired_and_emailed(world, 1)
    at(world, WINDOW_ENDS)
    assert entry.handler({"closeEverything": True, "drop_off_id": "AC-2"}, object()) == {"closed": 1}


def test_the_closer_is_built_once_per_container(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[object] = []

    def build_closer(settings: object) -> object:
        built.append(settings)
        return lambda: None

    monkeypatch.setattr(entry, "_closer", None)
    monkeypatch.setattr("asmbly_ceramics.composition.build_closer", build_closer)
    monkeypatch.setattr("asmbly_ceramics.logs.configure_logging", lambda *args: None)
    settings = SimpleNamespace(log_level="INFO", version="test")
    monkeypatch.setattr("asmbly_ceramics.settings.Settings.from_environment", staticmethod(lambda: settings))

    first = entry.closer()
    assert entry.closer() is first
    assert built == [settings]


class _Broken:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def __call__(self) -> object:
        raise self.error


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            RecordsUnavailable("ProvisionedThroughputExceededException"),
            "ProvisionedThroughputExceededException",
        ),
        (ValueError(f"bad item for {TEST_NAME} <{TEST_EMAIL}>"), "ValueError"),
        (SettingsError("TABLE_NAME is not set"), "SettingsError.TABLE_NAME"),
    ],
)
def test_a_run_that_stops_before_any_drop_off_raises_and_logs_a_code_only(
    error: Exception, code: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The studio's read or the list failing: Lambda's traceback gets the code or the
    class name, never the error's own text."""
    monkeypatch.setattr(entry, "_closer", _Broken(error))
    caplog.set_level(logging.INFO)

    with pytest.raises(entry.CloseAborted) as raised:
        entry.handler({}, None)

    assert raised.value.code == code
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    for text in (str(raised.value), repr(vars(raised.value))):
        assert TEST_NAME not in text
        assert TEST_EMAIL not in text
    [record] = [r for r in caplog.records if r.getMessage() == "close_aborted"]
    assert record.levelno == logging.ERROR
    assert vars(record)["error_code"] == code
