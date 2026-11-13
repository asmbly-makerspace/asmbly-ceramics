"""The errors every port shares.

They say something outside the app failed, not that a rule refused: they are not
`DomainError`s. Their text is fixed and safe to log: a provider's error code, never its
message, which can quote what was sent.
"""

# The errors are named for what happened (`Conflict`, `SendFailed`), as the plan's
# contract names them, not with an `Error` suffix.
# ruff: noqa: N818

from asmbly_ceramics.domain.email import is_error_code

UNKNOWN_CODE = "unknown"


def error_code(code: str) -> str:
    """`code` if it has an error code's shape, else `unknown`, so text never gets through."""
    return code if isinstance(code, str) and is_error_code(code) else UNKNOWN_CODE


class PortError(Exception):
    """Something outside the app failed; the base of every port's error."""


class Unavailable(PortError):
    """AWS or the network failed. Safe to show as "try again"; holds the provider's
    error code only, never its message."""

    def __init__(self, code: str) -> None:
        self.code = error_code(code)
        super().__init__(f"unavailable: {self.code}")


class RecordsUnavailable(Unavailable):
    """`Records`, and `RateLimiter`, whose counts are in the table."""


class IdsUnavailable(Unavailable):
    """`IdNumbers`."""


class PhotosUnavailable(Unavailable):
    """`PhotoStore`."""


class SignInUnavailable(Unavailable):
    """`StaffTokens`: the pool's keys or its token endpoint can't be reached."""


class SecretsUnavailable(Unavailable):
    """`Secrets`."""


class SecretMissing(PortError):
    """`Secrets`: the parameter doesn't exist, a setup error found at start."""

    def __init__(self, name: str) -> None:
        self.name = error_code(name)  # a parameter's name; any other text is `unknown`
        super().__init__(f"secret {self.name} is not set")
