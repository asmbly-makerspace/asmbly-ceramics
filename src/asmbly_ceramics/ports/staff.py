"""Staff sign-in, through asmbly-staff-login's pool (#3).

Only the `ceramics` group may open the console: a valid token without it is
`NotAllowed`.
"""

# The errors are named for what happened (`Conflict`, `SendFailed`), as the plan's
# contract names them, not with an `Error` suffix.
# ruff: noqa: N818

import re
from dataclasses import dataclass, field
from typing import Protocol

from asmbly_ceramics.ports.errors import PortError

STAFF_GROUP = "ceramics"  # asmbly-staff-login's group (asmbly-staff-login#4); not a setting
STAFF_USERNAME_MAX = 40
# A staff username is logged and stored (a rejection's `by`, a load's `started_by`), so
# it is a handle, never an address: 1 to 40 of `[A-Za-z0-9_.-]` with a letter, which a
# Cognito username or its `sub` (a UUID) fits and an email address or a phone number
# doesn't. The same shape `use_cases.log` logs as `user`.
_STAFF_USERNAME = re.compile(
    rf"(?=[A-Za-z0-9_.-]*[A-Za-z])[A-Za-z0-9_.-]{{1,{STAFF_USERNAME_MAX}}}", flags=re.ASCII
)


def is_staff_username(text: object) -> bool:
    """`text` has a staff username's shape (see `_STAFF_USERNAME`)."""
    return isinstance(text, str) and _STAFF_USERNAME.fullmatch(text) is not None


@dataclass(frozen=True, slots=True)
class StaffMember:
    username: str  # `is_staff_username`'s shape: an adapter refuses any other as `NotSignedIn`
    # The token's `email` claim only when its `email_verified` claim is the boolean true,
    # else `None`: `SendTestEmail` sends to it as given. For the test email only; never
    # logged.
    email: str | None = field(repr=False)


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
        """The signed-in staff member; `email` is set only from a verified email claim
        (`email_verified` is `True`), never from an unverified one. A token whose username
        hasn't `is_staff_username`'s shape is `NotSignedIn`; one without `STAFF_GROUP` is
        `NotAllowed`. `SignInUnavailable`."""
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
