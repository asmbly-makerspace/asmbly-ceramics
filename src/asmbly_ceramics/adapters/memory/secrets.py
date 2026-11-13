from asmbly_ceramics.ports.secrets import SecretName


class MemorySecrets:
    """A fixed, different key per name."""

    def get(self, name: SecretName) -> bytes:
        return f"test-key-for-{name.value}".encode().ljust(32, b"-")
