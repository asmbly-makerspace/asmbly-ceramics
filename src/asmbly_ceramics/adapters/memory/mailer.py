from asmbly_ceramics.ports.mailer import OutgoingEmail, SendFailed


class MemoryMailer:
    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []
        self.fail_with: str | None = None

    def send(self, message: OutgoingEmail) -> None:
        if self.fail_with is not None:
            raise SendFailed(self.fail_with)
        self.sent.append(message)
