from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StaffMember:
    username: str
    email: str | None  # from the verified token, for the test email only; never logged


class NotSignedIn(Exception):
    """No token, bad signature, wrong issuer/client/use, expired."""


class NotAllowed(Exception):
    """A valid token without the ceramics group."""

    def __init__(self, username: str) -> None:
        super().__init__("Not allowed.")
        self.username = username


class StaffTokens(Protocol):
    def verify(self, id_token: str) -> StaffMember: ...
    def sign_in_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str: ...
    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        """The ID token. Raises NotSignedIn."""
        ...

    def sign_out_url(self, *, redirect_uri: str) -> str: ...
