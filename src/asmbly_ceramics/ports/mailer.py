"""Sending one email.

The sender is the studio's address at `asmbly.org` (#6), and the recipient is the person
who made the drop-off, or the signed-in staff member for a test email. An adapter
refuses a `from_address` outside `SENDING_DOMAIN` with `ValueError`, as the fake does.
"""

# The errors are named for what happened (`Conflict`, `SendFailed`), as the plan's
# contract names them, not with an `Error` suffix.
# ruff: noqa: N818

from dataclasses import dataclass, field
from typing import Protocol

from asmbly_ceramics.domain.errors import SendingAddressOutsideAsmbly
from asmbly_ceramics.domain.studio import check_sending_address
from asmbly_ceramics.ports.errors import PortError, error_code


@dataclass(frozen=True, slots=True)
class InlineImage:
    content_id: str  # "photo-1"
    filename: str  # "AC-12-1.jpg"
    data: bytes = field(repr=False)
    content_type: str = "image/jpeg"


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """Every field stays out of the `repr`: they hold the person's address and name."""

    from_address: str = field(repr=False)
    from_name: str = field(repr=False)  # "Asmbly Ceramics"
    reply_to: str = field(repr=False)
    to: str = field(repr=False)
    subject: str = field(repr=False)
    html: str = field(repr=False)
    text: str = field(repr=False)
    inline: tuple[InlineImage, ...] = field(default=(), repr=False)


def is_sending_address(address: str) -> bool:
    """Whether `address` is exactly as the studio stores its sending address: at
    `SENDING_DOMAIN`, by the domain's own check (`check_sending_address`)."""
    try:
        return check_sending_address(address) == address
    except SendingAddressOutsideAsmbly:
        return False


class SendFailed(PortError):
    def __init__(self, code: str) -> None:
        self.code = error_code(code)  # the provider's error code, never its message
        super().__init__(f"send failed: {self.code}")


class Mailer(Protocol):
    def send(self, message: OutgoingEmail) -> None:
        """`SendFailed`; `ValueError` for a `from_address` outside `SENDING_DOMAIN`."""
        ...
