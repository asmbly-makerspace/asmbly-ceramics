from urllib.parse import urlencode

from asmbly_ceramics.ports.staff import NotAllowed, NotSignedIn, StaffMember


class MemoryStaffTokens:
    def __init__(self) -> None:
        # A token mapped to None is valid but lacks the ceramics group.
        self.tokens: dict[str, StaffMember | None] = {}
        self.codes: dict[str, str] = {}  # sign-in code -> ID token

    def verify(self, id_token: str) -> StaffMember:
        if id_token not in self.tokens:
            raise NotSignedIn
        member = self.tokens[id_token]
        if member is None:
            raise NotAllowed("unknown")
        return member

    def sign_in_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        query = urlencode({"state": state, "code_challenge": code_challenge, "redirect_uri": redirect_uri})
        return f"https://sign-in.example.org/login?{query}"

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        if code not in self.codes:
            raise NotSignedIn
        return self.codes[code]

    def sign_out_url(self, *, redirect_uri: str) -> str:
        return f"https://sign-in.example.org/logout?{urlencode({'redirect_uri': redirect_uri})}"
