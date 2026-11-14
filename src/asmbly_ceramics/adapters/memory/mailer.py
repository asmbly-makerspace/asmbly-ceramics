"""`Mailer` in memory: keeps what was sent, for assertions. Logs nothing."""

from asmbly_ceramics.ports.mailer import OutgoingEmail, SendFailed, check_outgoing


class MemoryMailer:
    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []
        self.fail_with: str | None = None  # an error code: send raises SendFailed(code)

    def send(self, message: OutgoingEmail) -> None:
        check_outgoing(message)
        if self.fail_with is not None:
            raise SendFailed(self.fail_with)
        self.sent.append(message)
