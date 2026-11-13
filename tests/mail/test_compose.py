"""The composer (#2, #5): every email names the ID in its subject, escapes what people
typed, and carries the photos under the references `outgoing` sends them by."""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from jinja2 import Environment, PackageLoader

from asmbly_ceramics.domain.closing import is_closable
from asmbly_ceramics.domain.dropoff import Contact, DropOff, DropOffState, Rejection
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import ItemStatus, Studio
from asmbly_ceramics.mail.compose import FOOTER, JinjaComposer, austin_time, pickup_by
from asmbly_ceramics.ports.composer import ComposedEmail, Composer, cid, outgoing
from tests.domain.builders import (
    NOW,
    STAFF,
    TEST_EMAIL,
    TEST_MESSAGE,
    TEST_NAME,
    TEST_PHONE,
    a_drop_off,
    a_sending_address,
    a_studio,
    an_address,
)

COMPOSER = JinjaComposer()
SCRIPT = "<script>alert(1)</script>"
IMG = '<img src=x onerror="alert(2)">'
TEMPLATES = (
    "_layout.html",
    *(f"{name}.{ext}" for name in ("received", "ready", "rejected", "test") for ext in ("html", "txt")),
)


def a_glaze_drop_off() -> DropOff:
    return replace(a_drop_off(12), firing_type=ItemId("glaze"), glaze_type=ItemId("house-dip-glaze"))


def rejected(message: str | None = TEST_MESSAGE, reason: str = "other") -> DropOff:
    drop_off = a_drop_off(12, DropOffState.REJECTED)
    return replace(drop_off, rejection=Rejection(ItemId(reason), message, STAFF, NOW))


def all_emails(drop_off: DropOff | None = None, studio: Studio | None = None) -> dict[str, ComposedEmail]:
    drop_off = drop_off or a_drop_off(12)
    studio = studio or a_studio()
    with_rejection = replace(drop_off, rejection=drop_off.rejection or rejected().rejection)
    return {
        "received": COMPOSER.received(drop_off, studio, cid),
        "ready": COMPOSER.ready(drop_off, studio, NOW, cid),
        "rejected": COMPOSER.rejected(with_rejection, studio, cid),
        "test": COMPOSER.test(studio),
    }


def test_jinja_composer_is_a_composer() -> None:
    composer: Composer = COMPOSER
    assert composer is COMPOSER


def test_each_email_has_its_subject_with_the_id() -> None:
    subjects = {kind: email.subject for kind, email in all_emails().items()}
    assert subjects == {
        "received": "We received your drop-off (AC-12)",
        "ready": "Ready for pickup (AC-12)",
        "rejected": "Your drop-off needs attention (AC-12)",
        "test": "Test email from Asmbly Ceramics",
    }


def test_the_subject_never_holds_the_name() -> None:
    drop_off = a_drop_off(12)
    for email in all_emails(drop_off).values():
        assert TEST_NAME not in email.subject


def test_markup_in_the_name_message_and_hours_is_escaped() -> None:
    hostile = f"{SCRIPT} {IMG}"
    drop_off = rejected(message=f"Line one {SCRIPT}\n{IMG}")
    assert drop_off.contact is not None
    drop_off = replace(drop_off, contact=replace(drop_off.contact, name=hostile))
    studio = replace(a_studio(), pickup_hours_text=f"Open {SCRIPT}\nAlso {IMG}")
    studio = replace(
        studio,
        reasons=tuple(
            replace(item, name=f"Other {IMG}") if item.id == "other" else item for item in studio.reasons
        ),
        firing_types=tuple(replace(item, name=f"Bisque {SCRIPT}") for item in studio.firing_types),
        glaze_types=tuple(replace(item, name=f"Dip {IMG}") for item in studio.glaze_types),
    )
    for email in all_emails(drop_off, studio).values():
        assert "<script" not in email.html
        assert "<img src=x" not in email.html
        assert 'onerror="alert' not in email.html
    received = COMPOSER.received(drop_off, studio, cid)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in received.html
    assert "Bisque &lt;script&gt;" in received.html
    glazed = COMPOSER.received(replace(a_glaze_drop_off(), contact=drop_off.contact), studio, cid)
    assert "<img src=x" not in glazed.html
    assert "(Dip &lt;img src=x onerror=&#34;alert(2)&#34;&gt;)" in glazed.html
    rejection = COMPOSER.rejected(drop_off, studio, cid)
    assert "Line one &lt;script&gt;" in rejection.html
    assert "Other &lt;img src=x onerror=&#34;alert(2)&#34;&gt;" in rejection.html
    assert "Open &lt;script&gt;" in rejection.html


def test_a_hostile_image_source_is_escaped() -> None:
    email = COMPOSER.received(a_drop_off(12), a_studio(), lambda ref: f'x" onerror="alert({ref.index})')
    assert 'onerror="alert' not in email.html
    assert 'src="x&#34; onerror=&#34;alert(1)"' in email.html


def test_line_breaks_in_the_hours_and_message_become_paragraphs() -> None:
    studio = replace(a_studio(), pickup_hours_text="Hours line one\n\nHours line two\n")
    email = COMPOSER.rejected(rejected(message="Message line one\nMessage line two"), studio, cid)
    for line in ("Hours line one", "Hours line two", "Message line one", "Message line two"):
        assert re.search(rf"<p [^>]*>{line}</p>", email.html), line
        assert f"\n{line}\n" in email.text
    assert '<p style="margin:0 0 8px 0;"></p>' not in email.html


def test_the_text_part_has_no_markup() -> None:
    for email in all_emails().values():
        assert not re.search(r"<[a-zA-Z/!]", email.text)
        assert "cid:" not in email.text
        assert FOOTER in email.text
        assert FOOTER in email.html


def test_the_text_part_keeps_what_was_typed_as_text() -> None:
    drop_off = a_drop_off(12)
    assert drop_off.contact is not None
    drop_off = replace(drop_off, contact=replace(drop_off.contact, name="Test & <Person>"))
    email = COMPOSER.received(drop_off, a_studio(), cid)
    assert "Hi Test & <Person>, thanks" in email.text
    assert "Hi Test &amp; &lt;Person&gt;, thanks" in email.html


def test_inline_images_match_the_cid_references() -> None:
    drop_off = a_drop_off(12)
    for kind in ("received", "ready", "rejected"):
        email = all_emails(drop_off)[kind]
        sources = re.findall(r'<img src="([^"]*)" alt="([^"]*)"', email.html)
        assert sources == [("cid:photo-1", "Photo 1 of AC-12"), ("cid:photo-2", "Photo 2 of AC-12")], kind
        message = outgoing(
            email,
            to=TEST_EMAIL,
            sending_address=a_sending_address(),
            photos=[(ref, b"jpeg") for ref in drop_off.photos],
        )
        assert [f"cid:{image.content_id}" for image in message.inline] == [src for src, _ in sources]
    assert "<img" not in all_emails(drop_off)["test"].html


def test_each_email_names_its_drop_off_for_outgoing() -> None:
    emails = all_emails(a_drop_off(12))
    assert {kind: email.drop_off_id for kind, email in emails.items()} == {
        "received": DropOffId(12),
        "ready": DropOffId(12),
        "rejected": DropOffId(12),
        "test": None,
    }


def test_the_photos_fit_a_phone_screen() -> None:
    email = COMPOSER.received(a_drop_off(12), a_studio(), cid)
    for tag in re.findall(r"<img [^>]*>", email.html):
        assert "max-width:" in tag
        assert "height:auto" in tag


def test_a_preview_passes_its_own_image_source() -> None:
    def preview(ref: PhotoRef) -> str:
        return f"/console/drop-offs/{ref.drop_off_id}/photos/{ref.index}"

    email = COMPOSER.rejected(rejected(), a_studio(), preview)
    assert 'src="/console/drop-offs/AC-12/photos/1"' in email.html
    assert "cid:" not in email.html


def test_received_shows_the_drop_off_time_in_austin() -> None:
    # NOW is 18:30 UTC on 13 November 2026, 12:30 PM in Austin (CST, UTC-6).
    email = COMPOSER.received(a_drop_off(12), a_studio(), cid)
    assert "Fri Nov 13, 12:30 PM" in email.html
    assert "Dropped off: Fri Nov 13, 12:30 PM" in email.text


@pytest.mark.parametrize(
    ("at", "shown"),
    [
        (datetime(2026, 11, 13, 16, 42, tzinfo=UTC), "Fri Nov 13, 10:42 AM"),
        (datetime(2026, 11, 14, 5, 59, tzinfo=UTC), "Fri Nov 13, 11:59 PM"),
        (datetime(2026, 11, 14, 6, 5, tzinfo=UTC), "Sat Nov 14, 12:05 AM"),
        (datetime(2026, 7, 4, 17, 0, tzinfo=UTC), "Sat Jul 4, 12:00 PM"),  # CDT, UTC-5
    ],
)
def test_austin_time_is_formatted_by_hand(at: datetime, shown: str) -> None:
    assert austin_time(at) == shown


def test_received_holds_the_id_pieces_firing_and_glaze_type() -> None:
    email = COMPOSER.received(a_glaze_drop_off(), a_studio(), cid)
    assert "Hi Test Person, thanks for dropping off. Here's your ID:" in email.html
    assert ">AC-12</p>" in email.html
    assert "Make sure each piece has a slip with this ID and your name." in email.html
    assert "3 pieces" in email.html
    assert "Glaze (House dip glaze)" in email.html
    assert "Firing: Glaze (House dip glaze)" in email.text
    assert "We'll email you again when it's fired and ready for pickup." in email.html


def test_one_piece_is_singular() -> None:
    email = COMPOSER.received(replace(a_drop_off(12), pieces=1), a_studio(), cid)
    assert "Pieces: 1 piece\n" in email.text


def test_ready_gives_the_pickup_date_from_when_it_is_sent() -> None:
    studio = replace(a_studio(), pickup_hours_text="Hours line one\nHours & line two")  # a 14-day window
    email = COMPOSER.ready(a_drop_off(12, DropOffState.FIRED), studio, NOW, cid)
    for part, hours in ((email.text, "Hours & line two"), (email.html, "Hours &amp; line two")):
        assert "Pick up by Fri Nov 27." in part
        assert "You have 14 days to collect them; after that, they may be subject to disposal." in part
        assert "Pickup hours" in part
        assert "Hours line one" in part
        assert hours in part
    assert "have exited the kiln and are ready for pickup!" in email.html
    assert f"reach out to our Kiln Ops team at {studio.sending_address}." in email.text
    assert "~ Kiln Ops" in email.text
    later = COMPOSER.ready(
        a_drop_off(12), replace(studio, pickup_window_days=1), NOW + timedelta(days=3), cid
    )
    for part in (later.text, later.html):
        assert "Pick up by Tue Nov 17." in part
        assert "You have 1 day to collect" in part


@pytest.mark.parametrize(
    ("sent_at", "shown", "window_ends"),
    [
        # Fall back (1 Nov 2026): 00:30 CDT on 25 October. Counted in UTC, 14 days would
        # end at 23:30 CST on 7 November, the 13th day.
        (datetime(2026, 10, 25, 5, 30, tzinfo=UTC), "Sun Nov 8", datetime(2026, 11, 9, 6, 0, tzinfo=UTC)),
        # Spring forward (14 Mar 2027): 23:30 CST on 6 March. Counted in UTC, the 15th day.
        (datetime(2027, 3, 7, 5, 30, tzinfo=UTC), "Sat Mar 20", datetime(2027, 3, 21, 5, 0, tzinfo=UTC)),
    ],
)
def test_the_pickup_date_is_the_austin_day_the_close_waits_out(
    sent_at: datetime, shown: str, window_ends: datetime
) -> None:
    email = COMPOSER.ready(a_drop_off(12, DropOffState.FIRED), a_studio(), sent_at, cid)
    for part in (email.text, email.html):
        assert f"Pick up by {shown}." in part
        assert "You have 14 days" in part
    assert pickup_by(sent_at.astimezone(STUDIO_TZ), 14) == pickup_by(sent_at, 14)
    fired = a_drop_off(12, DropOffState.FIRED)
    assert not is_closable(fired, sent_at, 14, window_ends - timedelta(seconds=1))
    assert is_closable(fired, sent_at, 14, window_ends)


def test_ready_needs_an_aware_time() -> None:
    with pytest.raises(ValueError, match="AC-12"):
        COMPOSER.ready(a_drop_off(12), a_studio(), NOW.replace(tzinfo=None), cid)


def test_rejected_includes_the_reason_and_the_message_and_omits_an_empty_message() -> None:
    studio = a_studio()
    email = COMPOSER.rejected(rejected(), studio, cid)
    assert "has been rejected from kiln firing due to:" in email.html
    assert ">Other</p>" in email.html
    assert "From Kiln Ops" in email.html
    assert TEST_MESSAGE in email.html
    assert f"\nFrom Kiln Ops\n{TEST_MESSAGE}\n" in email.text
    assert "you'll get a new ID" in email.html
    assert f"reach out to the kiln lead at {studio.sending_address}." in email.text
    assert "Pickup hours" in email.text
    without = COMPOSER.rejected(rejected(message=None, reason="has-glaze-issues"), studio, cid)
    assert ">Has glaze issues</p>" in without.html
    assert "From Kiln Ops" not in without.html
    assert "From Kiln Ops" not in without.text
    blank = COMPOSER.rejected(rejected(message="  \n "), studio, cid)
    assert "From Kiln Ops" not in blank.html


def test_rejected_needs_a_rejection() -> None:
    with pytest.raises(ValueError, match="AC-12"):
        COMPOSER.rejected(a_drop_off(12), a_studio(), cid)


def test_a_retired_item_still_shows_its_name() -> None:
    studio = a_studio()
    studio = replace(
        studio,
        firing_types=tuple(replace(item, status=ItemStatus.RETIRED) for item in studio.firing_types),
        glaze_types=tuple(replace(item, status=ItemStatus.RETIRED) for item in studio.glaze_types),
        reasons=tuple(replace(item, status=ItemStatus.RETIRED) for item in studio.reasons),
    )
    assert "Glaze (House dip glaze)" in COMPOSER.received(a_glaze_drop_off(), studio, cid).text
    assert "\nOther\n" in COMPOSER.rejected(rejected(), studio, cid).text


def test_an_item_the_studio_does_not_have_is_a_value_error_naming_the_id() -> None:
    studio = a_studio()
    without = replace(studio, glaze_types=(), reasons=())
    with pytest.raises(ValueError, match="AC-12") as raised:
        COMPOSER.received(a_glaze_drop_off(), without, cid)
    assert str(raised.value) == "AC-12 names an item missing from the studio's glaze_types"
    with pytest.raises(ValueError, match="AC-12"):
        COMPOSER.rejected(rejected(), without, cid)
    with pytest.raises(ValueError, match="firing_types"):
        COMPOSER.received(a_drop_off(12), replace(studio, firing_types=()), cid)


def test_a_closed_drop_off_cannot_be_composed() -> None:
    closed = a_drop_off(12, DropOffState.CLOSED)
    composers: list[Callable[[], ComposedEmail]] = [
        lambda: COMPOSER.received(closed, a_studio(), cid),
        lambda: COMPOSER.ready(closed, a_studio(), NOW, cid),
        lambda: COMPOSER.rejected(closed, a_studio(), cid),
    ]
    for compose in composers:
        with pytest.raises(ValueError, match="AC-12 is closed") as raised:
            compose()
        assert str(raised.value) == "AC-12 is closed: a closed drop-off is never emailed"


def test_there_is_no_link_to_a_kiln_schedule() -> None:
    for email in all_emails().values():
        assert "href" not in email.html
        assert "schedule" not in email.html.lower()
        assert "schedule" not in email.text.lower()


def test_the_test_email_names_the_sending_address() -> None:
    studio = replace(a_studio(), sending_address=a_sending_address("kiln-ops"))
    email = COMPOSER.test(studio)
    sentence = f"Emails to people who drop off are sent from {an_address('kiln-ops', 'asmbly.org')}."
    assert sentence in email.html
    assert sentence in email.text
    assert "This is a test email from the ceramics studio's console." in email.html
    assert "Members: during Asmbly&#39;s open hours" in email.html


def test_no_email_holds_the_phone_or_the_address_typed() -> None:
    for email in all_emails().values():
        for part in (email.subject, email.html, email.text):
            assert TEST_PHONE not in part
            assert TEST_EMAIL not in part


def test_the_templates_ship_with_the_package() -> None:
    env = Environment(loader=PackageLoader("asmbly_ceramics.mail"), autoescape=True)
    assert set(TEMPLATES) <= set(env.list_templates())
    for name in TEMPLATES:
        assert env.get_template(name).filename is not None


def test_composed_email_repr_holds_no_body() -> None:
    for email in all_emails().values():
        assert TEST_NAME not in repr(email)
        assert TEST_MESSAGE not in repr(email)


def test_a_drop_off_of_another_number_names_its_own_id() -> None:
    drop_off = a_drop_off(7)
    email = COMPOSER.received(drop_off, a_studio(), cid)
    assert email.subject.endswith("(AC-7)")
    assert str(DropOffId(7)) in email.text
    assert isinstance(drop_off.contact, Contact)
