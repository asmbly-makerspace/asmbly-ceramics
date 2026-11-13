"""Staff sign-in, through asmbly-staff-login's pool (#3).

Only the `ceramics` group may open the console: a valid token without it is
`NotAllowed`.
"""

# The errors are named for what happened (`Conflict`, `SendFailed`), as the plan's
# contract names them, not with an `Error` suffix.
# ruff: noqa: N818

from dataclasses import dataclass, field
from typing import Protocol

from asmbly_ceramics.ports.errors import PortError


@dataclass(frozen=True, slots=True)
class StaffMember:
    username: str
    email: str | None = field(repr=False)  # from the verified token, for the test email only; never logged


class NotSignedIn(PortError):
    """No token, a bad signature, the wrong issuer, client or use, or expired."""

    def __init__(self) -> None:
        super().__init__("not signed in")


class NotAllowed(PortError):
    """A valid token without the `ceramics` group."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"{username} is not in the ceramics group")


class StaffTokens(Protocol):
    def verify(self, id_token: str) -> StaffMember:
        """`NotSignedIn`, `NotAllowed`, `SignInUnavailable`."""
        ...

    def sign_in_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        """The hosted sign-in's address; `code_challenge` is the S256 challenge of the
        verifier `exchange` will be given. `SignInUnavailable`."""
        ...

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        """The ID token for a sign-in code.

        `NotSignedIn` for an unknown, expired or already used code, a `code_verifier`
        whose S256 challenge isn't the one the sign-in was started with, or a
        `redirect_uri` other than the one it was started with. A code is good for one
        exchange: the caller never retries one. `SignInUnavailable` when the token
        endpoint can't be reached."""
        ...

    def sign_out_url(self, *, redirect_uri: str) -> str:
        """`SignInUnavailable`."""
        ...
