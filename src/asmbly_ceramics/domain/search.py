"""The console's one search box (story #3): by ID (`AC-12`, `ac12`, `ac 12`, `12`) or by
any part of a name.

Text is compared folded on both sides (`fold`), so the stored name's case, Unicode form
and invisible format characters don't matter. What staff type may be a person's name: it
never appears in a `repr`.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from asmbly_ceramics.domain.dropoff import DropOff
from asmbly_ceramics.domain.ids import ID_DIGITS_MAX, DropOffId

QUERY_MAX = 100
_NUMBER = re.compile(r"(?:ac)?[ -]?([0-9]+)", flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class Query:
    id: DropOffId | None  # from "AC-12", "ac12", "ac 12", "12"; None for text or no valid ID
    text: str = field(repr=False)  # folded; "" when the query has an ID form


def fold(text: str) -> str:
    """Format characters (Unicode category `Cf`, such as a zero-width space) dropped as
    `DropOffDetails.create` drops them from a name, then NFC, casefolded, NFC again
    (casefolding can undo NFC), and whitespace runs as one space. `Cf` goes first so that
    a letter, a zero-width joiner and a combining accent still compose into one letter."""
    visible = "".join(c for c in text if unicodedata.category(c) != "Cf")
    folded = unicodedata.normalize("NFC", unicodedata.normalize("NFC", visible).casefold())
    return " ".join(folded.split())


def parse_query(raw: str) -> Query:
    """At most `QUERY_MAX` characters are read. An ID form gives a `DropOffId`; one that
    can't be an ID (`0`, `AC-000`, more than `ID_DIGITS_MAX` digits) matches nothing.
    Anything else is text."""
    text = fold(raw[:QUERY_MAX])
    match = _NUMBER.fullmatch(text)
    if match is None:
        return Query(id=None, text=text)
    digits = match.group(1).lstrip("0")
    if not digits or len(digits) > ID_DIGITS_MAX:
        return Query(id=None, text="")
    return Query(id=DropOffId(int(digits)), text="")


def matches(drop_off: DropOff, query: Query) -> bool:
    """By ID, or the name contains the text. Only the name is searched, never the email
    or phone. A closed drop-off has no name; an empty query matches nothing."""
    if query.id is not None:
        return drop_off.id == query.id
    if not query.text or drop_off.contact is None:
        return False
    return query.text in fold(drop_off.contact.name)
