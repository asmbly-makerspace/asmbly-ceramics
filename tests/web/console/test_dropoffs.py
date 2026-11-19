"""One drop-off's page, its photos, the rejection preview, reject, undo and retry (#3, #4,
#5), through the console's pages on the fakes. The person is made up."""

import html
import re
from datetime import timedelta

import httpx2
import pytest

from asmbly_ceramics.domain.dropoff import DropOffState
from asmbly_ceramics.domain.email import EmailKind, EmailStatus, rejection_occasion
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.photos import PhotoRef, PhotoSize
from asmbly_ceramics.domain.studio import CatalogList
from asmbly_ceramics.ports.composer import cid
from asmbly_ceramics.ports.errors import PhotosUnavailable
from asmbly_ceramics.ports.records import CommitOutcomeUnknown
from asmbly_ceramics.web.console.dropoffs import Panel
from tests.domain.builders import STAFF, TEST_EMAIL, TEST_MESSAGE, TEST_NAME, TEST_PHONE_DIGITS
from tests.use_cases.flows import STAFF_MEMBER, email_of, fired, loaded, pending, send_all
from tests.web.console.conftest import Console

AC_1 = DropOffId(1)
PAGE = "/console/drop-offs/AC-1"
OTHER = "other"
GLAZE_ISSUES = "has-glaze-issues"
D = TEST_PHONE_DIGITS
FORMATTED_PHONE = f"({D[:3]}) {D[3:6]}-{D[6:]}"  # built in code: no number in the file


@pytest.fixture
def ready(console: Console) -> Console:
    console.drop_off(1)
    console.sign_in()
    return console


def fields(console: Console, reason: str = OTHER, message: str = TEST_MESSAGE) -> dict[str, str]:
    return {"reason": reason, "message": message, "version": console.version(AC_1)}


def state(console: Console) -> DropOffState:
    drop_off = console.world.records.drop_off(AC_1)
    assert drop_off is not None
    return drop_off.state


def rejected_emails(console: Console) -> list[EmailStatus]:
    return [e.status for e in console.world.records.emails_for(AC_1) if e.kind is EmailKind.REJECTED]


def srcdoc_of(page: str) -> str:
    """The preview frame's email, as the browser reads the attribute."""
    match = re.search(r'srcdoc="([^"]*)"', page)
    assert match is not None
    return html.unescape(match.group(1))


def reject(console: Console, reason: str = OTHER, message: str = TEST_MESSAGE) -> None:
    answer = console.post(f"{PAGE}/reject", fields(console, reason, message))
    assert answer.status_code == 303, answer.text


# --- the page and its photos -----------------------------------------------------------------


def test_the_drop_off_page_shows_every_photo_and_the_contact_details(ready: Console) -> None:
    page = ready.get(PAGE)
    assert page.status_code == 200
    for text in (
        TEST_NAME,
        TEST_EMAIL,
        FORMATTED_PHONE,
        "Waiting since today",
        "Bisque",
        "Add to a load",
        "Reject…",
    ):
        assert text in page.text, text
    assert f'href="tel:{TEST_PHONE_DIGITS}"' in page.text
    for k in (1, 2):
        assert f'<img src="/console/drop-offs/AC-1/photos/{k}" alt="Photo {k} of 2">' in page.text
    assert "Received</strong>: Waiting to send" in page.text


@pytest.mark.parametrize("path", ["AC-999", "AC-0", "ac-12", "AC-12x", "AC-01", "12"])
def test_an_unknown_or_malformed_id_is_404(ready: Console, path: str) -> None:
    answer = ready.get(f"/console/drop-offs/{path}")
    assert answer.status_code == 404
    if path == "AC-999":
        assert "There&#39;s no drop-off AC-999." in answer.text
    assert 'href="/console"' in answer.text


def test_photos_are_served_to_staff_with_private_caching_and_nosniff(ready: Console) -> None:
    for suffix, size in (("", PhotoSize.FULL), ("/thumb", PhotoSize.THUMB)):
        answer = ready.get(f"{PAGE}/photos/2{suffix}")
        assert answer.status_code == 200
        assert answer.content == ready.world.photos.read(PhotoRef(AC_1, 2), size)
        assert answer.headers["content-type"] == "image/jpeg"
        assert answer.headers["x-content-type-options"] == "nosniff"
        assert answer.headers["cache-control"] == "no-store"
        expected = f'inline; filename="AC-1-2{"-thumb" if suffix else ""}.jpg"'
        assert answer.headers["content-disposition"] == expected


@pytest.mark.parametrize("k", ["0", "3", "7", "01", "x", "-1"])
def test_a_photo_the_drop_off_doesn_t_have_is_404(ready: Console, k: str) -> None:
    assert ready.get(f"{PAGE}/photos/{k}").status_code == 404


def test_photos_without_a_session_never_read_the_store(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    console.drop_off(1)
    reads: list[PhotoRef] = []
    original = console.world.photos.read

    def counted(ref: PhotoRef, size: PhotoSize) -> bytes:
        reads.append(ref)
        return original(ref, size)

    monkeypatch.setattr(console.world.photos, "read", counted)
    for path in (f"{PAGE}/photos/1", f"{PAGE}/photos/1/thumb"):
        answer = console.get(path)
        assert answer.status_code == 401
        assert b"\xff\xd8" not in answer.content
    console.sign_in(groups=("front-desk",), username="front.desk")
    assert console.get(f"{PAGE}/photos/1").status_code == 403
    assert reads == []


def test_photos_are_served_with_no_store(ready: Console) -> None:
    assert ready.get(f"{PAGE}/photos/1").headers["cache-control"] == "no-store"


def test_a_photo_store_that_can_t_be_reached_is_503(ready: Console) -> None:
    ready.world.photos.fail_with = PhotosUnavailable("made-up-outage")
    assert ready.get(f"{PAGE}/photos/1").status_code == 503


def test_a_closed_drop_off_shows_no_details_and_no_photos(ready: Console) -> None:
    fired(ready.world, AC_1)
    send_all(ready.world)
    ready.world.clock.advance(timedelta(days=60))
    ready.world.close()
    page = ready.get(PAGE)
    assert page.status_code == 200
    assert "its contact details and photos were deleted." in page.text
    for text in (TEST_NAME, TEST_EMAIL, TEST_PHONE_DIGITS[-4:], "/photos/1"):
        assert text not in page.text, text
    assert ready.get(f"{PAGE}/photos/1").status_code == 404


# --- the reject panel and the preview -----------------------------------------------------------


def test_the_reject_panel_opens_without_a_script(ready: Console) -> None:
    page = ready.get(f"{PAGE}?reject=1")
    assert 'action="/console/drop-offs/AC-1/reject/preview"' in page.text
    assert '<option value="other">Other (needs a message)</option>' in page.text
    assert 'maxlength="1000"' in page.text
    assert 'autocomplete="off"' in page.text


def test_other_without_a_message_is_refused_next_to_the_field_and_stores_nothing(ready: Console) -> None:
    for path in ("reject/preview", "reject"):
        answer = ready.post(f"{PAGE}/{path}", fields(ready, OTHER, ""))
        assert answer.status_code == 400
        assert '<p class="field-error" id="message-error">This reason needs a message.</p>' in answer.text
        assert '<option value="other" selected>' in answer.text
    assert state(ready) is DropOffState.WAITING
    assert rejected_emails(ready) == []


def test_a_message_of_1001_characters_is_refused(ready: Console) -> None:
    answer = ready.post(f"{PAGE}/reject", fields(ready, GLAZE_ISSUES, "m" * 1001))
    assert answer.status_code == 400
    assert "The message is longer than 1,000 characters." in answer.text
    assert "m" * 1001 in answer.text  # the typed message is kept
    assert state(ready) is DropOffState.WAITING


def test_a_retired_reason_is_refused(ready: Console) -> None:
    studio = ready.world.studio()
    ready.world.retire_item(CatalogList.REASONS, ItemId(GLAZE_ISSUES), studio.version, STAFF_MEMBER)
    answer = ready.post(f"{PAGE}/reject/preview", fields(ready, GLAZE_ISSUES, ""))
    assert answer.status_code == 400
    assert (
        '<p class="field-error" id="reason-error">Has glaze issues is retired and can&#39;t be picked.</p>'
        in answer.text
    )


def test_an_unknown_reason_is_refused(ready: Console) -> None:
    for reason in ("made-up-reason", "<b>", ""):
        answer = ready.post(f"{PAGE}/reject/preview", fields(ready, reason, ""))
        assert answer.status_code == 400
        assert "That reason doesn&#39;t exist." in answer.text


def test_a_version_that_isn_t_a_number_is_400(ready: Console) -> None:
    answer = ready.post(f"{PAGE}/reject", {**fields(ready), "version": "1e9"})
    assert answer.status_code == 400


def test_the_preview_is_a_post_and_its_message_never_appears_in_a_url(ready: Console) -> None:
    assert ready.get(f"{PAGE}/reject/preview").status_code == 405
    answer = ready.post(f"{PAGE}/reject/preview", fields(ready))
    assert answer.status_code == 200
    assert "location" not in answer.headers
    assert not re.search(r'(href|action)="[^"]*Leave', answer.text)
    sent = ready.post(f"{PAGE}/reject", fields(ready))
    assert "Leave" not in sent.headers["location"]


def test_the_preview_shows_who_it_goes_to_and_only_it_allows_the_email_s_styles(ready: Console) -> None:
    answer = ready.post(f"{PAGE}/reject/preview", fields(ready))
    assert f"<dd>{TEST_EMAIL}</dd>" in answer.text
    assert "Asmbly Ceramics &lt;ceramics@" in answer.text
    assert "<dd>Your drop-off needs attention (AC-1)</dd>" in answer.text
    assert (
        '<iframe class="email-preview" title="The rejection email" sandbox="allow-same-origin" srcdoc="'
        in answer.text
    )
    policy = answer.headers["content-security-policy"]
    assert "style-src-attr 'unsafe-inline'" in policy
    assert "frame-src 'self'" in policy
    assert "script-src 'self'" in policy
    assert "unsafe-inline" not in ready.get(PAGE).headers["content-security-policy"]


def test_the_preview_escapes_the_message(ready: Console) -> None:
    answer = ready.post(f"{PAGE}/reject/preview", fields(ready, OTHER, "<script>alert(1)</script>"))
    assert "<script>alert" not in answer.text
    srcdoc = srcdoc_of(answer.text)
    assert "<script>alert" not in srcdoc
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in srcdoc


def test_the_preview_is_the_email_that_is_sent(ready: Console) -> None:
    send_all(ready.world)  # the received email goes first
    preview = ready.post(f"{PAGE}/reject/preview", fields(ready))
    srcdoc = srcdoc_of(preview.text)
    hidden = dict(re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)">', preview.text))
    assert html.unescape(hidden["message"]) == TEST_MESSAGE
    sent = ready.post(f"{PAGE}/reject", {k: html.unescape(v) for k, v in hidden.items()})
    assert sent.status_code == 303
    send_all(ready.world)
    email = ready.world.mailer.sent[-1]
    assert email.subject == "Your drop-off needs attention (AC-1)"
    expected = srcdoc
    for k in (1, 2):
        expected = expected.replace(f"/console/drop-offs/AC-1/photos/{k}/thumb", cid(PhotoRef(AC_1, k)))
    assert email.html == expected


# --- reject -----------------------------------------------------------------------------------


def test_a_rejection_records_the_username_and_queues_one_email(ready: Console) -> None:
    answer = ready.post(f"{PAGE}/reject", fields(ready))
    assert answer.headers["location"] == f"{PAGE}?done=rejected"
    drop_off = ready.world.records.drop_off(AC_1)
    assert drop_off is not None
    assert drop_off.rejection is not None
    assert (drop_off.state, drop_off.rejection.by, drop_off.rejection.message) == (
        DropOffState.REJECTED,
        STAFF,
        TEST_MESSAGE,
    )
    assert rejected_emails(ready) == [EmailStatus.PENDING]
    page = ready.get(answer.headers["location"])
    assert "AC-1 was rejected. The email is on its way." in page.text
    assert "Rejected today: Other" in page.text
    assert "Undo rejection" in page.text
    assert "AC-1" not in ready.get("/console").text.split("</nav>")[-1]  # it left the waiting list


def test_rejecting_twice_is_refused_and_queues_no_second_email(ready: Console) -> None:
    reject(ready)
    answer = ready.post(f"{PAGE}/reject", fields(ready))
    assert answer.status_code == 400
    assert "AC-1 isn&#39;t waiting: it is rejected." in answer.text
    assert rejected_emails(ready) == [EmailStatus.PENDING]


def test_rejecting_a_drop_off_in_a_load_is_refused(ready: Console) -> None:
    load_id = loaded(ready.world, AC_1)
    answer = ready.post(f"{PAGE}/reject", fields(ready))
    assert answer.status_code == 400
    assert f"AC-1 isn&#39;t waiting: it is in load. It is in load {load_id}." in answer.text
    assert state(ready) is DropOffState.IN_LOAD


def test_a_conflicting_change_is_reported_and_nothing_is_stored(ready: Console) -> None:
    stale = fields(ready)
    loaded(ready.world, AC_1)
    ready.world.remove_from_load(loaded_load(ready), AC_1, STAFF_MEMBER)  # back to waiting, a new version
    answer = ready.post(f"{PAGE}/reject", stale)
    assert answer.status_code == 409
    assert "AC-1 changed while you were looking. Check it and try again." in answer.text
    assert TEST_MESSAGE in answer.text  # the typed message is kept
    assert state(ready) is DropOffState.WAITING
    assert rejected_emails(ready) == []


def loaded_load(console: Console) -> LoadId:
    [load] = console.world.list_loads()[0]
    return load.id


def test_a_rejection_whose_outcome_is_unknown_says_to_check(
    ready: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unknown(changes: object) -> None:
        raise CommitOutcomeUnknown("made-up-timeout")

    monkeypatch.setattr(ready.world.records, "commit", unknown)
    answer = ready.post(f"{PAGE}/reject", fields(ready))
    assert answer.status_code == 503
    assert "That may or may not have been saved." in answer.text


# --- undo -------------------------------------------------------------------------------------


def test_undo_on_the_same_austin_day_puts_it_back_and_sends_nothing(ready: Console) -> None:
    send_all(ready.world)
    reject(ready)
    answer = ready.post(f"{PAGE}/undo-reject", {"version": ready.version(AC_1)})
    assert answer.headers["location"] == f"{PAGE}?done=undone"
    assert state(ready) is DropOffState.WAITING
    sent_before = len(ready.world.mailer.sent)
    send_all(ready.world)
    assert len(ready.world.mailer.sent) == sent_before
    assert rejected_emails(ready) == [EmailStatus.CANCELLED]
    assert "AC-1 is waiting again. No email was sent." in ready.get(answer.headers["location"]).text


def test_undo_after_the_email_went_says_to_contact_the_person(ready: Console) -> None:
    reject(ready)
    send_all(ready.world)
    answer = ready.post(f"{PAGE}/undo-reject", {"version": ready.version(AC_1)})
    assert answer.headers["location"] == f"{PAGE}?done=undone-contact"
    text = ready.get(answer.headers["location"]).text
    assert "The rejection email went, or may have: contact the person directly." in text


def test_undo_the_next_day_is_refused(ready: Console) -> None:
    ready.world.clock.advance(timedelta(hours=11))  # 11:30 PM in Austin, 5:30 AM UTC
    reject(ready)
    ready.world.clock.advance(timedelta(hours=1))  # past Austin's midnight, the same UTC day
    page = ready.get(PAGE)
    assert "Undo rejection" not in page.text
    answer = ready.post(f"{PAGE}/undo-reject", {"version": ready.version(AC_1)})
    assert answer.status_code == 400
    assert "AC-1 was rejected on an earlier day; undo works only the same day." in answer.text
    assert state(ready) is DropOffState.REJECTED


def test_undo_with_a_stale_version_is_a_conflict(ready: Console) -> None:
    reject(ready)
    answer = ready.post(f"{PAGE}/undo-reject", {"version": "1"})
    assert answer.status_code == 409


def test_undo_of_a_waiting_drop_off_is_refused(ready: Console) -> None:
    answer = ready.post(f"{PAGE}/undo-reject", {"version": ready.version(AC_1)})
    assert answer.status_code == 400
    assert "AC-1 isn&#39;t rejected." in answer.text


# --- retry ------------------------------------------------------------------------------------


def test_retry_requeues_a_failed_email_only(ready: Console) -> None:
    ready.world.mailer.fail_with = "MessageRejected"
    send_all(ready.world)
    ready.world.mailer.fail_with = None
    page = ready.get(PAGE)
    assert "Sending failed (MessageRejected)" in page.text
    assert 'action="/console/drop-offs/AC-1/emails/received/retry"' in page.text
    answer = ready.post(f"{PAGE}/emails/received/retry", {"occasion": ""})
    assert answer.headers["location"] == f"{PAGE}?done=retried"
    assert email_of(ready.world, AC_1, EmailKind.RECEIVED).status is EmailStatus.PENDING
    assert "The email to AC-1 will be sent again." in ready.get(answer.headers["location"]).text
    send_all(ready.world)
    assert "Try sending again" not in ready.get(PAGE).text  # sent: nothing to retry
    again = ready.post(f"{PAGE}/emails/received/retry", {"occasion": ""})
    assert again.status_code == 400
    assert "That email isn&#39;t failed." in again.text


def test_retry_of_a_rejected_email_takes_its_occasion_as_stored(ready: Console) -> None:
    reject(ready)
    ready.world.mailer.fail_with = "MessageRejected"
    send_all(ready.world)
    drop_off = ready.world.records.drop_off(AC_1)
    assert drop_off is not None
    assert drop_off.rejection is not None
    occasion = rejection_occasion(drop_off.rejection.at)
    assert f'name="occasion" value="{occasion}"' in ready.get(PAGE).text
    answer = ready.post(f"{PAGE}/emails/rejected/retry", {"occasion": occasion})
    assert answer.status_code == 303
    assert [e.status for e in pending(ready.world)] == [EmailStatus.PENDING]


@pytest.mark.parametrize(
    ("kind", "occasion", "status"), [("made-up", "", 404), ("rejected", "", 400), ("received", "x", 400)]
)
def test_retry_of_a_malformed_email_key_is_refused(
    ready: Console, kind: str, occasion: str, status: int
) -> None:
    assert ready.post(f"{PAGE}/emails/{kind}/retry", {"occasion": occasion}).status_code == status


def test_a_notice_shows_only_when_the_state_agrees(ready: Console) -> None:
    assert "was rejected" not in ready.get(f"{PAGE}?done=rejected").text  # it is waiting
    assert "is waiting again" in ready.get(f"{PAGE}?done=undone").text
    reject(ready)
    assert "is waiting again" not in ready.get(f"{PAGE}?done=undone").text
    assert "was rejected" in ready.get(f"{PAGE}?done=rejected").text
    assert "made-up" not in ready.get(f"{PAGE}?done=made-up").text


def test_a_reason_without_an_item_s_shape_names_no_item(ready: Console) -> None:
    studio = ready.world.studio()
    ready.world.add_item(
        CatalogList.REASONS,
        "Unknown reason",
        needs_glaze_type=False,
        needs_message=False,
        version=studio.version,
        staff=STAFF_MEMBER,
    )
    for reason in ("Unknown Reason", "unknown reason", ""):
        answer = ready.post(f"{PAGE}/reject", fields(ready, reason, ""))
        assert answer.status_code == 400
        assert state(ready) is DropOffState.WAITING


def test_an_address_with_query_characters_can_t_shape_the_mailto_link(console: Console) -> None:
    from tests.use_cases.test_submit import a_device, a_request, a_token

    hostile = "a?cc=x%40example.org&subject=hi" + "@" + "example.org"
    request = a_request(console.world, token=a_token(1), device=a_device(1), email=hostile)
    console.world.submit(request)
    console.sign_in()
    page = console.get(PAGE).text
    escaped = "a%3Fcc%3Dx%2540example.org%26subject%3Dhi" + "@" + "example.org"
    assert f'href="mailto:{escaped}"' in page
    assert "mailto:a?cc" not in page


def test_a_photo_index_far_too_long_is_404_not_a_crash(ready: Console) -> None:
    assert ready.get(f"{PAGE}/photos/{'1' * 5000}").status_code == 404


def test_the_reject_panel_s_repr_holds_no_message() -> None:
    panel = Panel(open=True, reason=OTHER, message=TEST_MESSAGE)
    assert TEST_MESSAGE not in repr(panel)
    assert TEST_MESSAGE not in str(panel)


# --- deleting a drop-off made by mistake or as a test ----------------------------------------


def delete(console: Console, typed: str | None = None, *, version: str | None = None) -> httpx2.Response:
    data = {"version": version or console.version(AC_1)}
    if typed is not None:
        data |= {"confirm": "1", "typed_id": typed}
    return console.post(f"{PAGE}/delete", data)


def test_a_waiting_drop_off_offers_delete_behind_a_closed_panel(ready: Console) -> None:
    page = html.unescape(ready.get(PAGE).text)
    assert "<summary>Delete this drop-off</summary>" in page
    assert f'action="{PAGE}/delete"' in page
    assert "Delete AC-1…" in page
    assert 'name="typed_id"' not in page  # the confirmation comes only after asking


def test_delete_asks_first_and_says_what_goes(ready: Console) -> None:
    asked = delete(ready)

    assert asked.status_code == 200
    page = html.unescape(asked.text)
    assert "Delete AC-1?" in page
    assert "This can't be undone." in page
    assert "no one is emailed about it" in page
    assert 'name="typed_id"' in page
    assert "Delete AC-1 for good" in page
    assert "<summary>Delete this drop-off</summary>" not in page
    assert state(ready) is DropOffState.WAITING
    assert ready.world.photos.kept_count(AC_1) == 4


@pytest.mark.parametrize("typed", ["", "AC-2", "1", "yes", "L-1", "AC-11"])
def test_delete_refuses_unless_the_id_is_typed_exactly(ready: Console, typed: str) -> None:
    refused = delete(ready, typed)

    assert refused.status_code == 400
    page = html.unescape(refused.text)
    assert "Type AC-1 exactly to delete this drop-off." in page
    assert "Delete AC-1?" in page  # still asking
    assert state(ready) is DropOffState.WAITING
    assert ready.world.photos.kept_count(AC_1) == 4


@pytest.mark.parametrize("typed", ["AC-1", " ac-1 "])
def test_delete_with_the_id_typed_erases_the_person_and_their_photos(
    ready: Console, typed: str, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.INFO)

    done = delete(ready, typed)

    assert done.status_code == 303
    assert done.headers["location"] == f"{PAGE}?done=deleted"
    assert state(ready) is DropOffState.DELETED
    assert ready.world.photos.kept_count(AC_1) == 0
    assert email_of(ready.world, AC_1, EmailKind.RECEIVED).status is EmailStatus.CANCELLED
    page = html.unescape(ready.get(done.headers["location"]).text)
    assert "AC-1 was deleted: its contact details and photos are gone. No one was emailed about it." in page
    assert f"Deleted by {STAFF}" in page
    assert TEST_NAME not in page
    assert TEST_EMAIL not in page
    assert TEST_PHONE_DIGITS not in page
    assert FORMATTED_PHONE not in page
    assert "/photos/1" not in page
    assert "Delete this drop-off" not in page
    assert "Reject…" not in page
    assert ready.get(f"{PAGE}/photos/1").status_code == 404
    assert ("drop_off_deleted", STAFF) in [(r.message, getattr(r, "user", None)) for r in caplog.records]
    again = delete(ready, "AC-1")
    assert again.status_code == 400
    assert "AC-1 is deleted: only a waiting drop-off can be deleted." in html.unescape(again.text)


def test_a_deleted_notice_shows_only_for_a_deleted_drop_off(ready: Console) -> None:
    assert "was deleted" not in ready.get(f"{PAGE}?done=deleted").text


def test_a_drop_off_in_a_load_says_to_remove_it_first(ready: Console) -> None:
    loaded(ready.world, AC_1)
    assert "Delete this drop-off" not in ready.get(PAGE).text

    for answer in (delete(ready), delete(ready, "AC-1")):
        assert answer.status_code == 400
        page = html.unescape(answer.text)
        assert (
            "AC-1 is in load: only a waiting drop-off can be deleted. Remove it from load L-1 first." in page
        )
    assert state(ready) is DropOffState.IN_LOAD
    assert ready.world.photos.kept_count(AC_1) == 4


def test_a_rejected_drop_off_cannot_be_deleted(ready: Console) -> None:
    reject(ready)
    assert "Delete this drop-off" not in ready.get(PAGE).text
    answer = delete(ready, "AC-1")
    assert answer.status_code == 400
    assert "AC-1 is rejected: only a waiting drop-off can be deleted." in html.unescape(answer.text)
    assert state(ready) is DropOffState.REJECTED


def test_a_fired_drop_off_isnt_told_to_leave_its_load(ready: Console) -> None:
    fired(ready.world, AC_1)

    answer = delete(ready, "AC-1")

    assert answer.status_code == 400
    page = html.unescape(answer.text)
    assert "AC-1 is fired: only a waiting drop-off can be deleted." in page
    assert "Remove it from load" not in page


def test_delete_from_a_stale_page_is_a_conflict(ready: Console) -> None:
    shown = ready.version(AC_1)
    load_id = loaded(ready.world, AC_1)
    ready.world.remove_from_load(load_id, AC_1, STAFF_MEMBER)

    answer = delete(ready, "AC-1", version=shown)

    assert answer.status_code == 409
    assert "AC-1 changed while you were looking." in html.unescape(answer.text)
    assert ready.world.photos.kept_count(AC_1) == 4


def test_photos_that_cant_be_deleted_delete_nothing(ready: Console) -> None:
    ready.world.photos.fail_with = PhotosUnavailable("ServiceUnavailable")

    answer = delete(ready, "AC-1")

    ready.world.photos.fail_with = None
    assert answer.status_code == 503
    assert "Its photos couldn't be deleted, so nothing was." in html.unescape(answer.text)
    assert state(ready) is DropOffState.WAITING


def test_a_delete_that_may_not_have_landed_says_so(ready: Console) -> None:
    ready.world.records.fail_next_commit_with = CommitOutcomeUnknown("RequestTimeout")

    answer = delete(ready, "AC-1")

    assert answer.status_code == 503
    assert "That may or may not have been saved." in html.unescape(answer.text)


def test_a_drop_off_in_a_load_links_to_it(ready: Console) -> None:
    load_id = loaded(ready.world, AC_1)

    page = ready.get(PAGE).text

    assert f'href="/console/loads/{load_id}"' in page


def test_a_fired_drop_off_still_links_to_its_load(ready: Console) -> None:
    load_id = fired(ready.world, AC_1)

    page = ready.get(PAGE).text

    assert f'href="/console/loads/{load_id}"' in page


def test_a_waiting_drop_off_has_no_load_link(ready: Console) -> None:
    assert "drop-off-load" not in ready.get(PAGE).text
