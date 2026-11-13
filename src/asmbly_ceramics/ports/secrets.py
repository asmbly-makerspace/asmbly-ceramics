from enum import StrEnum
from typing import Protocol


class SecretName(StrEnum):
    HASH_KEY = "hash-key"  # keyed hashes for rate limits and submission tokens (form)
    FORM_KEY = "form-key"  # signs the public form's __Host-received cookie (form only)
    SESSION_KEY = "session-key"  # signs the console's sign-in state and CSRF tokens (console only)


class Secrets(Protocol):
    def get(self, name: SecretName) -> bytes: ...
