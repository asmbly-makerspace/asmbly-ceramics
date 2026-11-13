"""`Mailer` in memory: keeps what was sent, for assertions. Logs nothing."""

from asmbly_ceramics.ports.mailer import OutgoingEmail, SendFailed, is_sending_address


class MemoryMailer:
    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []
        self.fail_with: str | None = None  # an error code: send raises SendFailed(code)

    def send(self, message: OutgoingEmail) -> None:
        if not is_sending_address(message.from_address):
            raise ValueError("mail is sent only from an address at asmbly.org")
        if self.fail_with is not None:
            raise SendFailed(self.fail_with)
        self.sent.append(message)
