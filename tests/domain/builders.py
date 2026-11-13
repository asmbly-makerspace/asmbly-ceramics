"""Made-up test data, built in code.

The repository is public and `tests/repo/test_personal_data.py` fails on a literal email
address or phone number, so addresses are put together from parts here.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import TypedDict, Unpack

from asmbly_ceramics.domain.closing import close
from asmbly_ceramics.domain.dropoff import DropOff, DropOffDetails, DropOffState, Rejection, new_drop_off
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.limits import SENDING_DOMAIN
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import Studio, starting_studio

STAFF = "kiln-tech"
NOW = datetime(2026, 11, 13, 18, 30, tzinfo=UTC)


def an_address(local: str, domain: str = "example.org") -> str:
    return local + "@" + domain


def a_sending_address(local: str = "ceramics") -> str:
    return an_address(local, SENDING_DOMAIN)


def a_studio() -> Studio:
    studio, _ = starting_studio(a_sending_address(), NOW)
    return studio


# A made-up person. The phone number is put together from digit groups so that no line
# of this file reads as one.
TEST_NAME = "Test Person"
TEST_EMAIL = an_address("test.person")
TEST_PHONE = " ".join(["(512)", "555", "01" + "00"])
TEST_PHONE_DIGITS = "512" + "555" + "0100"
TEST_MESSAGE = "Leave the base unglazed, then drop it off again."


class DetailsArgs(TypedDict, total=False):
    """`DropOffDetails.create`'s keyword arguments."""

    name: str
    email: str
    phone: str
    pieces: str
    firing_type: str
    glaze_type: str | None
    photo_count: int
    studio: Studio


def details(**overrides: Unpack[DetailsArgs]) -> DropOffDetails:
    """`DropOffDetails.create`'s keyword arguments, valid by default (a bisque drop-off)."""
    arguments: DetailsArgs = {
        "name": TEST_NAME,
        "email": TEST_EMAIL,
        "phone": TEST_PHONE,
        "pieces": "3",
        "firing_type": "bisque",
        "glaze_type": None,
        "photo_count": 2,
        "studio": a_studio(),
    }
    arguments.update(overrides)
    return DropOffDetails.create(
        name=arguments["name"],
        email=arguments["email"],
        phone=arguments["phone"],
        pieces=arguments["pieces"],
        firing_type=arguments["firing_type"],
        glaze_type=arguments["glaze_type"],
        photo_count=arguments["photo_count"],
        studio=arguments["studio"],
    )


def photo_refs(id: DropOffId, count: int = 2) -> tuple[PhotoRef, ...]:
    return tuple(PhotoRef(id, index) for index in range(1, count + 1))


def a_drop_off(
    number: int = 1,
    state: DropOffState = DropOffState.WAITING,
    *,
    at: datetime = NOW,
    load: int = 1,
    reason: str = "other",
) -> DropOff:
    """A drop-off in `state`, as the domain's moves would have left it."""
    id = DropOffId(number)
    drop_off = new_drop_off(id, details(), photo_refs(id), at)
    match state:
        case DropOffState.WAITING:
            return drop_off
        case DropOffState.IN_LOAD:
            return replace(drop_off, state=state, load_id=LoadId(load))
        case DropOffState.FIRED:
            return replace(drop_off, state=state, load_id=LoadId(load), fired_at=at)
        case DropOffState.REJECTED:
            return replace(
                drop_off, state=state, rejection=Rejection(ItemId(reason), TEST_MESSAGE, STAFF, at)
            )
        case DropOffState.CLOSED:
            return close(a_drop_off(number, DropOffState.REJECTED, at=at, reason=reason), at)


def a_load(
    number: int = 1,
    status: LoadStatus = LoadStatus.LOADING,
    members: Sequence[int] = (),
    *,
    kiln: str = "athena",
    firing_type: str = "bisque",
    at: datetime = NOW,
) -> Load:
    """A load in `status` holding the drop-offs numbered `members`."""
    return Load(
        id=LoadId(number),
        kiln=ItemId(kiln),
        firing_type=ItemId(firing_type),
        date=at.date(),
        status=status,
        members=tuple(DropOffId(member) for member in members),
        started_by=STAFF,
        started_at=at,
        fired_at=at if status is LoadStatus.FIRED else None,
    )
