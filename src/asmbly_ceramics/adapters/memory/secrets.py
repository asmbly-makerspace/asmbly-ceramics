"""`Secrets` in memory: fixed, made-up bytes per name, 32 by default."""

import hashlib

from asmbly_ceramics.ports.errors import SecretMissing
from asmbly_ceramics.ports.secrets import SecretName


class MemorySecrets:
    def __init__(self) -> None:
        # Distinct per name, so a test can tell which key signed what.
        self._values = {name: hashlib.sha256(b"memory-" + name.encode()).digest() for name in SecretName}
        self.fail_with: Exception | None = None

    def get(self, name: SecretName) -> bytes:
        if self.fail_with is not None:
            raise self.fail_with
        if name not in self._values:
            raise SecretMissing(name)
        return self._values[name]

    def remove(self, name: SecretName) -> None:
        self._values.pop(name, None)
