"""`outgoing` and `cid`: the composed email becomes the `Mailer`'s message, only from
`asmbly.org`, with the photos inline under the references the HTML uses."""

from dataclasses import replace

import pytest

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.ports.composer import FROM_NAME, ComposedEmail, cid, outgoing
from tests.domain.builders import TEST_EMAIL, TEST_NAME, a_sending_address, an_address, photo_refs

COMPOSED = ComposedEmail(
    subject="We received your drop-off (AC-12)", html="<p>Hi</p>", text="Hi", drop_off_id=DropOffId(12)
)
REFS = photo_refs(DropOffId(12), 2)
PHOTOS = [(ref, f"jpeg {ref.index}".encode()) for ref in REFS]


def test_cid_names_the_photo_by_its_index() -> None:
    assert [cid(ref) for ref in REFS] == ["cid:photo-1", "cid:photo-2"]


def test_from_name_and_reply_to_are_set_by_outgoing() -> None:
    sender = a_sending_address()
    message = outgoing(COMPOSED, to=TEST_EMAIL, sending_address=sender, photos=PHOTOS)
    assert message.from_name == FROM_NAME == "Asmbly Ceramics"
    assert message.from_address == sender
    assert message.reply_to == sender
    assert message.to == TEST_EMAIL
    assert (message.subject, message.html, message.text) == (COMPOSED.subject, COMPOSED.html, COMPOSED.text)


def test_outgoing_sends_each_photo_inline_under_its_cid() -> None:
    message = outgoing(COMPOSED, to=TEST_EMAIL, sending_address=a_sending_address(), photos=PHOTOS)
    assert [(image.content_id, image.filename, image.data) for image in message.inline] == [
        ("photo-1", "AC-12-1.jpg", b"jpeg 1"),
        ("photo-2", "AC-12-2.jpg", b"jpeg 2"),
    ]
    assert all(image.content_type == "image/jpeg" for image in message.inline)
    assert [f"cid:{image.content_id}" for image in message.inline] == [cid(ref) for ref in REFS]


def test_outgoing_without_photos_has_nothing_inline() -> None:
    message = outgoing(COMPOSED, to=TEST_EMAIL, sending_address=a_sending_address(), photos=[])
    assert message.inline == ()


@pytest.mark.parametrize(
    "sender",
    [
        an_address("ceramics"),
        an_address("ceramics", "asmbly.org.example.org"),
        an_address("ceramics", "notasmbly.org"),
        " " + a_sending_address(),
        a_sending_address() + "\r\nBcc: x",
        "",
    ],
)
def test_outgoing_refuses_a_sending_address_outside_asmbly(sender: str) -> None:
    with pytest.raises(ValueError, match=r"asmbly\.org") as raised:
        outgoing(COMPOSED, to=TEST_EMAIL, sending_address=sender, photos=PHOTOS)
    if sender:
        assert sender not in str(raised.value)


@pytest.mark.parametrize("to", ["", TEST_NAME, TEST_EMAIL + "\r\nBcc: " + TEST_EMAIL, "@example.org"])
def test_outgoing_refuses_a_recipient_that_is_not_an_address(to: str) -> None:
    with pytest.raises(ValueError, match="recipient") as raised:
        outgoing(COMPOSED, to=to, sending_address=a_sending_address(), photos=PHOTOS)
    assert TEST_EMAIL not in str(raised.value)


@pytest.mark.parametrize(
    "photos",
    [
        [*PHOTOS, (photo_refs(DropOffId(13), 1)[0], b"jpeg")],  # another drop-off's photo
        [PHOTOS[0], PHOTOS[0]],  # the same photo twice
        [PHOTOS[0], (REFS[0], b"other")],  # the same index twice
    ],
)
def test_outgoing_refuses_another_drop_offs_photo_or_a_repeated_one(
    photos: list[tuple[PhotoRef, bytes]],
) -> None:
    with pytest.raises(ValueError, match="photo"):
        outgoing(COMPOSED, to=TEST_EMAIL, sending_address=a_sending_address(), photos=photos)


def test_the_test_email_carries_no_photo() -> None:
    test_email = replace(COMPOSED, drop_off_id=None)
    assert outgoing(test_email, to=TEST_EMAIL, sending_address=a_sending_address(), photos=[]).inline == ()
    with pytest.raises(ValueError, match="own drop-off"):
        outgoing(test_email, to=TEST_EMAIL, sending_address=a_sending_address(), photos=PHOTOS)


def test_composed_email_repr_holds_no_body() -> None:
    composed = ComposedEmail(subject="Ready for pickup (AC-12)", html=f"<p>{TEST_NAME}</p>", text=TEST_NAME)
    assert TEST_NAME not in repr(composed)
    assert "AC-12" in repr(composed)
