"""Small text checks shared by the drop-off form and the settings."""

import re
import unicodedata

from asmbly_ceramics.domain.limits import EMAIL_MAX

_LABEL = re.compile(r"[A-Za-z0-9-]+")


def strip_controls(text: str) -> str:
    """Remove control characters (category C*), then strip."""
    return "".join(c for c in text if not unicodedata.category(c).startswith("C")).strip()


def is_valid_email(address: str) -> bool:
    """One `@`, a non-empty local part without spaces or controls, a dotted domain of
    `[A-Za-z0-9-]` labels. No DNS lookup. `address` is already stripped."""
    if not address or len(address) > EMAIL_MAX:
        return False
    local, at, domain = address.partition("@")
    if not at or "@" in domain or not local:
        return False
    if any(c.isspace() or unicodedata.category(c).startswith("C") for c in local):
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(_LABEL.fullmatch(label) for label in labels)
