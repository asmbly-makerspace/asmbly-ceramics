"""Finding a drop-off by its number or part of the name."""

import re
from dataclasses import dataclass

from asmbly_ceramics.domain.dropoff import DropOff

_QUERY_MAX = 100
_NUMBER = re.compile(r"(?:ac[\s-]*)?([0-9]{1,9})")


@dataclass(frozen=True, slots=True)
class Query:
    number: int | None  # from "AC-12", "ac12", "ac 12", "12"
    text: str  # casefolded, stripped; "" when the query is a number


def parse_query(raw: str) -> Query:
    text = raw[:_QUERY_MAX].strip().casefold()
    found = _NUMBER.fullmatch(text)
    if found is not None:
        return Query(int(found.group(1)), "")
    return Query(None, text)


def matches(drop_off: DropOff, query: Query) -> bool:
    if query.number is not None:
        return drop_off.id.number == query.number
    if not query.text or drop_off.contact is None:
        return False
    return query.text in drop_off.contact.name.casefold()
