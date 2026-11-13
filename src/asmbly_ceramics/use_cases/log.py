"""The one way use cases log: an event name and fixed field names, IDs only.

Phase 7 formats each record as a JSON line from its `extra`, and its metric filters and
alarms match these field names, so they are a contract. Each field has its own shape,
and a value without it is logged as `invalid` instead (the request doesn't fail, as
`ports.errors.error_code` does for codes):

- `drop_off_id`: a drop-off's ID (`AC-12`), as `str(drop_off.id)`; `load_id`: `L-4`.
- `user`: a staff username: a handle of at most 40 characters with at least one letter,
  no `@`, `:` or `#`.
- `kind`, `outcome`, `list`: a lowercase snake_case word (an email kind, a fixed
  outcome, a catalog list).
- `reason`: such a word, or a catalog item's ID (`domain.ids.is_item_id`: a slug that
  always holds a letter).
- `item`: a catalog item's ID (`domain.ids.is_item_id`).
- `error_code`: a code `domain.email.is_error_code` accepts (what an email stores) that
  is also either 1 to 3 digits (an HTTP status, `404`) or holds a letter, has no `-`, and
  is under 64 characters (`ThrottlingException`, `EC2ThrottledException`,
  `photo_missing`, `unknown`, or an exception's class name such as `KeyError`).
- `fields`: refused fields' names (`firing_type`, `photo.2`), comma-joined, never their
  values.
- `count`: an `int`, never a `str`.

So a phone number, an IP address, an email address, a sentence, a `device#` or
`submission#` hash, or a 64-character digest never fits a field. A shape can't tell a
short lowercase word from a name, a token from a username, or a token that happens to be
letters only from an error code,
so callers still pass only the values listed above: never a name, email, phone, message,
photo, token, cookie or address.
"""

import logging
import re
from collections.abc import Callable

from asmbly_ceramics.domain.email import is_error_code
from asmbly_ceramics.domain.ids import is_drop_off_id, is_item_id, is_load_id

_EVENT = re.compile(r"[a-z][a-z0-9_]{0,63}", flags=re.ASCII)
_WORD_MAX = 40  # far beyond any fixed word; refuses a 64-character hex digest
_WORD = re.compile(rf"[a-z][a-z0-9_]{{0,{_WORD_MAX - 1}}}", flags=re.ASCII)
# A staff username can be a UUID (36), so 40 at most; a handle can look like a token.
_USER = re.compile(rf"(?=[A-Za-z0-9_.-]*[A-Za-z])[A-Za-z0-9_.-]{{1,{_WORD_MAX}}}", flags=re.ASCII)
# Narrower than `is_error_code`: no `-` (a phone number, a token), no digits-only value
# longer than a status (a phone number), something with a letter unless it's a status (an
# IPv4 address), and under 64 characters (a SHA-256 hex digest).
_CODE = re.compile(r"[0-9]{1,3}|(?=[0-9_.]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9_.]{0,62}", flags=re.ASCII)
_FIELD_NAME = rf"[a-z][a-z0-9_]{{0,{_WORD_MAX - 1}}}(?:\.[1-9][0-9]?)?"
_FIELDS = re.compile(rf"{_FIELD_NAME}(?:,{_FIELD_NAME}){{0,19}}", flags=re.ASCII)
INVALID_VALUE = "invalid"


def _matches(pattern: re.Pattern[str]) -> Callable[[object], bool]:
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_reason(value: object) -> bool:
    return isinstance(value, str) and (_WORD.fullmatch(value) is not None or is_item_id(value))


def _is_code(value: object) -> bool:
    return isinstance(value, str) and is_error_code(value) and _CODE.fullmatch(value) is not None


_SHAPES: dict[str, Callable[[object], bool]] = {
    "drop_off_id": is_drop_off_id,
    "load_id": is_load_id,
    "user": _matches(_USER),
    "kind": _matches(_WORD),
    "outcome": _matches(_WORD),
    "reason": _is_reason,
    "error_code": _is_code,
    "count": _is_count,
    "fields": _matches(_FIELDS),
    "list": _matches(_WORD),
    "item": is_item_id,
}

LOG_FIELDS = frozenset({"event", *_SHAPES})

logger = logging.getLogger("asmbly_ceramics")


def log_event(event: str, *, level: int = logging.INFO, **fields: str | int) -> None:
    """Log one event with fixed field names. Unknown names raise ValueError (a bug).

    The record's message is the event name alone, never a formatted value; the fields go
    in `extra`, with `event` among them.
    """
    if not isinstance(event, str) or _EVENT.fullmatch(event) is None:
        raise ValueError("an event is a fixed snake_case word")
    unknown = sorted(set(fields) - LOG_FIELDS)
    if unknown:
        raise ValueError("unknown log fields: " + ", ".join(unknown))
    # A value of another type (a bool, None, a float, an object) fails every shape, so it
    # is logged as `invalid` too, never as its repr.
    safe = {name: value if _SHAPES[name](value) else INVALID_VALUE for name, value in fields.items()}
    logger.log(level, event, extra={**safe, "event": event})
