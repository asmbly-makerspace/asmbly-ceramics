"""`StaffTokens` in memory: tokens and codes are dictionary keys."""

import base64
import hashlib
from dataclasses import dataclass
from urllib.parse import urlencode

from asmbly_ceramics.ports.staff import NotAllowed, NotSignedIn, StaffMember

SIGN_IN_ORIGIN = "https://sign-in.example.org"


def s256(code_verifier: str) -> str:
    """The PKCE S256 challenge of a verifier: unpadded base64url of its SHA-256."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class _Grant:
    token: str
    code_challenge: str
    redirect_uri: str


class MemoryStaffTokens:
    def __init__(self) -> None:
        self.members: dict[str, StaffMember] = {}  # token -> a member of ceramics
        self.outsiders: dict[str, str] = {}  # token -> username: signed in, not in the group
        self._started: tuple[str, str] | None = None  # the last sign-in's challenge, redirect
        self._codes: dict[str, _Grant] = {}  # sign-in code -> what it was issued for
        self.fail_with: Exception | None = None

    def verify(self, id_token: str) -> StaffMember:
        self._fail()
        if id_token in self.members:
            return self.members[id_token]
        if id_token in self.outsiders:
            raise NotAllowed(self.outsiders[id_token])
        raise NotSignedIn()

    def sign_in_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        self._fail()
        self._started = (code_challenge, redirect_uri)
        query = urlencode({"state": state, "code_challenge": code_challenge, "redirect_uri": redirect_uri})
        return f"{SIGN_IN_ORIGIN}/oauth2/authorize?{query}"

    def approve(self, code: str, token: str) -> None:
        """What signing in at the hosted page does: issues `code` for `token`, tied to the
        challenge and redirect URI of the last `sign_in_url`."""
        if self._started is None:
            raise ValueError("no sign-in was started")
        challenge, redirect_uri = self._started
        self._codes[code] = _Grant(token, challenge, redirect_uri)

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        self._fail()
        grant = self._codes.pop(code, None)  # one try per code, whatever its outcome
        if grant is None or grant.redirect_uri != redirect_uri:
            raise NotSignedIn()
        if s256(code_verifier) != grant.code_challenge:
            raise NotSignedIn()
        return grant.token

    def sign_out_url(self, *, redirect_uri: str) -> str:
        self._fail()
        return f"{SIGN_IN_ORIGIN}/logout?{urlencode({'redirect_uri': redirect_uri})}"

    def _fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with
