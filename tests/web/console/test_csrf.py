"""Forged requests: a console POST needs this session's CSRF token and this site's origin."""

import logging

import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.ids import DropOffId
from tests.web.conftest import SITE
from tests.web.console.conftest import Console, events

REJECT = "/console/drop-offs/AC-1/reject"


def reject_fields(console: Console) -> dict[str, str]:
    return {"reason": "has-glaze-issues", "message": "", "version": console.version(DropOffId(1))}


def state(console: Console) -> DropOffState:
    drop_off = console.world.records.drop_off(DropOffId(1))
    assert drop_off is not None
    return drop_off.state


@pytest.fixture
def ready(console: Console) -> Console:
    console.drop_off(1)
    console.sign_in()
    return console


def test_a_post_without_the_csrf_field_is_refused_and_changes_nothing(
    ready: Console, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    answer = ready.post(REJECT, reject_fields(ready), csrf=False)
    assert answer.status_code == 403
    assert "This form has expired. Go back, reload the page and try again." in answer.text
    assert state(ready) is DropOffState.WAITING
    assert ("csrf_refused", None) in events(caplog)


def test_a_post_with_another_sessions_csrf_token_is_refused(ready: Console) -> None:
    other = ready.csrf()
    ready.sign_in()  # a new session: a new token
    assert ready.csrf() != other
    answer = ready.post(REJECT, {**reject_fields(ready), "csrf": other})
    assert answer.status_code == 403
    assert state(ready) is DropOffState.WAITING


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://testserver", "https://testserver.evil.example"]
)
def test_a_post_from_another_origin_is_refused(ready: Console, origin: str) -> None:
    answer = ready.post(REJECT, reject_fields(ready), headers={"origin": origin})
    assert answer.status_code == 403
    assert state(ready) is DropOffState.WAITING


@pytest.mark.parametrize(
    "headers",
    [{}, {"origin": "null"}, {"referer": "https://evil.example/console"}, {"referer": f"{SITE}/drop-off"}],
)
def test_a_post_with_no_origin_and_no_console_referer_is_refused(
    ready: Console, headers: dict[str, str]
) -> None:
    assert ready.post(REJECT, reject_fields(ready), headers=headers).status_code == 403
    assert state(ready) is DropOffState.WAITING


def test_a_post_with_no_origin_and_a_console_referer_is_accepted(ready: Console) -> None:
    answer = ready.post(REJECT, reject_fields(ready), headers={"referer": f"{SITE}/console/drop-offs/AC-1"})
    assert answer.status_code == 303
    assert state(ready) is DropOffState.REJECTED


def test_a_post_with_no_origin_from_the_same_origin_is_accepted(ready: Console) -> None:
    answer = ready.post(REJECT, reject_fields(ready), headers={"sec-fetch-site": "same-origin"})
    assert answer.status_code == 303


def test_a_post_that_isn_t_a_form_is_refused(ready: Console) -> None:
    answer = ready.client.post(
        REJECT, content=b'{"reason": "other"}', headers={"origin": SITE, "content-type": "application/json"}
    )
    assert answer.status_code == 400
    assert state(ready) is DropOffState.WAITING


def test_a_post_far_too_large_is_refused(ready: Console) -> None:
    answer = ready.post(REJECT, {**reject_fields(ready), "message": "x" * 40_000})
    assert answer.status_code == 413
    assert state(ready) is DropOffState.WAITING


def test_a_refused_token_is_logged_once_with_its_outcome(
    ready: Console, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ready.post(REJECT, {**reject_fields(ready), "csrf": "made-up-wrong"})
    assert [e for e in events(caplog) if e[0] in ("csrf_refused", "page_refused")] == [("csrf_refused", None)]
    [record] = [r for r in caplog.records if r.message == "csrf_refused"]
    assert record.outcome == "wrong_token"  # type: ignore[attr-defined]  # a log_event field


def test_a_console_400_says_to_reload_not_to_go_to_the_form(ready: Console) -> None:
    answer = ready.post(REJECT, {**reject_fields(ready), "version": "x"})
    assert answer.status_code == 400
    assert "Go back, reload the page and try again." in answer.text
    assert "drop-off form" not in answer.text


def test_a_trailing_slash_is_not_redirected_to_plain_http(ready: Console) -> None:
    answer = ready.get("/console/")
    assert answer.status_code == 404
    assert "location" not in answer.headers


def test_a_malformed_referer_is_refused_not_a_crash(ready: Console) -> None:
    answer = ready.post(REJECT, reject_fields(ready), headers={"referer": "https://[unclosed/console"})
    assert answer.status_code == 403
