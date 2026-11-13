from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class InlineImage:
    content_id: str  # "photo-1"
    filename: str  # "AC-12-1.jpg"
    data: bytes
    content_type: str = "image/jpeg"


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    from_address: str
    from_name: str  # "Asmbly Ceramics"
    reply_to: str
    to: str
    subject: str
    html: str
    text: str
    inline: tuple[InlineImage, ...] = ()


class SendFailed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code  # the provider's error code, never its message


class Mailer(Protocol):
    def send(self, message: OutgoingEmail) -> None: ...
