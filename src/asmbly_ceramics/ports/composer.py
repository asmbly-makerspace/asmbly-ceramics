"""Composing the studio's emails: what the use cases import.

The three emails to the person who dropped off (received, ready, rejected) and the staff
test email are composed from templates by `mail.compose.JinjaComposer`, the one
`Composer`; the use cases depend on this Protocol, never on Jinja2. `outgoing` turns a
composed email into the `Mailer`'s `OutgoingEmail`, with the photos inline under the
`cid:` references the HTML uses, and only from the studio's address at `asmbly.org`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from asmbly_ceramics.domain.dropoff import DropOff
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import Studio, is_valid_email
from asmbly_ceramics.ports.mailer import InlineImage, OutgoingEmail, is_sending_address

FROM_NAME = "Asmbly Ceramics"


@dataclass(frozen=True, slots=True)
class ComposedEmail:
    subject: str  # the drop-off's ID only, never a name
    html: str = field(repr=False)  # holds the person's name
    text: str = field(repr=False)
    # Whose drop-off the email is about; `None` for the staff test email, which has no
    # photos. `outgoing` attaches only this drop-off's photos.
    drop_off_id: DropOffId | None = None


class Composer(Protocol):
    """Each method raises `ValueError`, naming only the drop-off's ID, for a drop-off that
    can't be emailed: closed, without what the email needs, or naming a firing type, glaze
    type or reason the studio doesn't have (a retired one still has its name)."""

    def received(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail: ...

    def ready(
        self, drop_off: DropOff, studio: Studio, sent_at: datetime, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail:
        """`sent_at` (aware) starts the pickup window the email gives."""
        ...

    def rejected(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail: ...

    def test(self, studio: Studio) -> ComposedEmail: ...


def content_id(ref: PhotoRef) -> str:
    return f"photo-{ref.index}"


def cid(ref: PhotoRef) -> str:
    """The `src` of a photo sent inline with `outgoing`: `cid:photo-<index>`."""
    return f"cid:{content_id(ref)}"


def outgoing(
    composed: ComposedEmail, *, to: str, sending_address: str, photos: Sequence[tuple[PhotoRef, bytes]]
) -> OutgoingEmail:
    """The message the `Mailer` sends: from the studio's `asmbly.org` address, which
    replies go to as well, with each photo inline as `photo-<index>`.

    `ValueError` for a `sending_address` outside `asmbly.org`, a `to` that isn't an
    address, a photo of any drop-off but the email's own (`composed.drop_off_id`; the test
    email takes none) or the same photo twice, before anything is built; the message
    names neither address. The caller reads `to` and the photos by the same drop-off key.
    """
    if not is_sending_address(sending_address):
        raise ValueError("the sending address must be at asmbly.org")
    if not is_valid_email(to):
        raise ValueError("the recipient is not an email address")
    if any(ref.drop_off_id != composed.drop_off_id for ref, _ in photos):
        raise ValueError("an email carries only its own drop-off's photos")
    indexes = [ref.index for ref, _ in photos]
    if len(set(indexes)) != len(indexes):
        raise ValueError("an email carries each photo once")
    return OutgoingEmail(
        from_address=sending_address,
        from_name=FROM_NAME,
        reply_to=sending_address,
        to=to,
        subject=composed.subject,
        html=composed.html,
        text=composed.text,
        inline=tuple(
            InlineImage(content_id=content_id(ref), filename=f"{ref.drop_off_id}-{ref.index}.jpg", data=data)
            for ref, data in photos
        ),
    )
