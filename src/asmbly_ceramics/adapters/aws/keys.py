"""The records table's key design and the item <-> entity conversions.

One table, string keys `PK` and `SK`, two global secondary indexes:

| Item | `PK` | `SK` | `GSI1PK` / `GSI1SK` | `GSI2PK` / `GSI2SK` | `ttl` |
| --- | --- | --- | --- | --- | --- |
| Drop-off | `DROPOFF#AC-12` | `META` | `DROPOFF#<state>` / `<created_at>#AC-12` | | |
| Load | `LOAD#L-4` | `META` | `LOAD#<status>` / `<date>#L-4` | | |
| Studio | `STUDIO` | `CURRENT` | | | |
| Settings history | `STUDIO` | `HISTORY#<at>#<16 hex>` | | | |
| Email (outbox) | `EMAIL#AC-12` | `<kind>[#<occasion>]` | | `EMAIL#<status>` / `<created>#AC-12#<kind>` | |
| ID counters | `COUNTER#dropoff`, `COUNTER#load` | `META` | | | |
| Rate-limit hits | `RATE#<keyed hash>` | `META` | | | a day after the window |
| Submission | `SUBMISSION#<keyed hash>` | `META` | | | `expires_at` |

Every item has a top-level `type` string; a drop-off, a load, an email and the studio
also have a `version` number. Times are UTC with
fixed microseconds and a `Z` (`2026-11-13T18:30:00.000000Z`), so they sort as strings;
a load's date is `YYYY-MM-DD`. A drop-off's personal details are their own top-level
attributes (`contact_name`, `contact_email`, `contact_phone`, `rejection_message`), and an
item is always written whole, so a closed drop-off's item holds none of them (#7). An
email's `type` and `status` are top-level strings, for phase 7's stream filter.

Lists sort in Python after a query, so an ID's number needs no padding in a sort key.
"""

import re
import secrets
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from asmbly_ceramics.domain.dropoff import Contact, DropOff, DropOffState, Rejection
from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.domain.load import Load, LoadStatus
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import CatalogItem, ItemStatus, SettingChange, Studio
from asmbly_ceramics.ports.records import Item, Submission

AttributeMap = dict[str, Any]  # a low-level item: attribute name -> {"S": ...}, {"N": ...}

DROP_OFF = "drop_off"
LOAD = "load"
STUDIO = "studio"
HISTORY = "history"
EMAIL = "email"
COUNTER = "counter"
RATE = "rate"
SUBMISSION = "submission"

META = "META"
STUDIO_PK = "STUDIO"
STUDIO_SK = "CURRENT"
HISTORY_PREFIX = "HISTORY#"
GSI1 = "GSI1"
GSI2 = "GSI2"

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_TIME = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z"
HISTORY_SUFFIX_HEX = 16
# A history cursor: a history item's sort key without `HISTORY#`.
_HISTORY_CURSOR = re.compile(rf"({_TIME})#[0-9a-f]{{{HISTORY_SUFFIX_HEX}}}", flags=re.ASCII)

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def iso(at: datetime) -> str:
    """An aware time as the table stores it: UTC, fixed microseconds, `Z`."""
    if at.utcoffset() is None:
        raise ValueError("a stored time is aware")
    return at.astimezone(UTC).strftime(_TIME_FORMAT)


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, _TIME_FORMAT).replace(tzinfo=UTC)


def is_history_cursor(text: object) -> bool:
    return isinstance(text, str) and _HISTORY_CURSOR.fullmatch(text) is not None


# Keys ---------------------------------------------------------------------------------


def key(pk: str, sk: str) -> AttributeMap:
    return {"PK": {"S": pk}, "SK": {"S": sk}}


def drop_off_key(id: DropOffId) -> AttributeMap:
    return key(f"DROPOFF#{id}", META)


def load_key(id: LoadId) -> AttributeMap:
    return key(f"LOAD#{id}", META)


def studio_key() -> AttributeMap:
    return key(STUDIO_PK, STUDIO_SK)


def email_pk(drop_off_id: DropOffId) -> str:
    return f"EMAIL#{drop_off_id}"


def email_key(drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> AttributeMap:
    return key(email_pk(drop_off_id), f"{kind}#{occasion}" if occasion else str(kind))


def submission_key(token_hash: str) -> AttributeMap:
    return key(f"SUBMISSION#{token_hash}", META)


def counter_key(which: str) -> AttributeMap:
    return key(f"COUNTER#{which}", META)


def rate_key(hashed: str) -> AttributeMap:
    return key(f"RATE#{hashed}", META)


def drop_off_partition(state: DropOffState) -> str:
    return f"DROPOFF#{state}"


def load_partition(status: LoadStatus) -> str:
    return f"LOAD#{status}"


def email_partition(status: EmailStatus) -> str:
    return f"EMAIL#{status}"


def new_history_sk(at: datetime) -> str:
    """A settings change's sort key: its time and a random suffix, so two changes at one
    instant both land and keep a fixed order."""
    return f"{HISTORY_PREFIX}{iso(at)}#{secrets.token_hex(HISTORY_SUFFIX_HEX // 2)}"


def item_key(item: Item) -> AttributeMap:
    """The key an entity is stored under. A `SettingChange` gets a new random one each
    call: call once per change."""
    match item:
        case DropOff():
            return drop_off_key(item.id)
        case Load():
            return load_key(item.id)
        case Studio():
            return studio_key()
        case Email():
            return email_key(item.drop_off_id, item.kind, item.occasion)
        case Submission():
            return submission_key(item.token_hash)
        case SettingChange():
            return key(STUDIO_PK, new_history_sk(item.at))


# Entity -> item -----------------------------------------------------------------------


def to_item(entity: Item, stored_key: AttributeMap, version: int | None) -> AttributeMap:
    """The whole item for `entity`, under `stored_key`, at `version` (`None` for an item
    that has none: a settings change, a submission). `None` attributes are left out,
    never stored as nulls."""
    attributes: dict[str, object] = {"version": version, **_attributes(entity)}
    item = dict(stored_key)
    item.update(
        {name: _serializer.serialize(value) for name, value in attributes.items() if value is not None}
    )
    return item


def _attributes(entity: Item) -> dict[str, object]:
    match entity:
        case DropOff():
            return _drop_off(entity)
        case Load():
            return {
                "type": LOAD,
                "GSI1PK": load_partition(entity.status),
                "GSI1SK": f"{entity.date.isoformat()}#{entity.id}",
                "id": str(entity.id),
                "kiln": entity.kiln,
                "firing_type": entity.firing_type,
                "date": entity.date.isoformat(),
                "status": entity.status.value,
                "members": [str(member) for member in entity.members],
                "started_by": entity.started_by,
                "started_at": iso(entity.started_at),
                "fired_at": _iso_or_none(entity.fired_at),
            }
        case Studio():
            return {
                "type": STUDIO,
                "sending_address": entity.sending_address,
                "pickup_window_days": entity.pickup_window_days,
                "pickup_hours_text": entity.pickup_hours_text,
                "kilns": [_catalog_item(i) for i in entity.kilns],
                "firing_types": [_catalog_item(i) for i in entity.firing_types],
                "glaze_types": [_catalog_item(i) for i in entity.glaze_types],
                "reasons": [_catalog_item(i) for i in entity.reasons],
            }
        case SettingChange():
            return {"type": HISTORY, "at": iso(entity.at), "by": entity.by, "what": entity.what}
        case Email():
            return {
                "type": EMAIL,
                "GSI2PK": email_partition(entity.status),
                "GSI2SK": f"{iso(entity.created_at)}#{entity.drop_off_id}#{entity.kind}",
                "drop_off_id": str(entity.drop_off_id),
                "kind": entity.kind.value,
                "occasion": entity.occasion,
                "status": entity.status.value,
                "created_at": iso(entity.created_at),
                "attempts": entity.attempts,
                "claimed_at": _iso_or_none(entity.claimed_at),
                "sent_at": _iso_or_none(entity.sent_at),
                "error_code": entity.error_code,
                "pickup_window_days": entity.pickup_window_days,
                "retried_at": _iso_or_none(entity.retried_at),
            }
        case Submission():
            return {
                "type": SUBMISSION,
                "drop_off_id": str(entity.drop_off_id),
                "pieces": entity.pieces,
                "firing_type": entity.firing_type,
                "glaze_type": entity.glaze_type,
                "created_at": iso(entity.created_at),
                "expires_at": iso(entity.expires_at),
                # DynamoDB deletes it some time after this (typically within days), so a
                # reader checks `expires_at` itself (`use_cases.received.is_live`).
                "ttl": int(entity.expires_at.timestamp()),
            }


def _drop_off(d: DropOff) -> dict[str, object]:
    attributes: dict[str, object] = {
        "type": DROP_OFF,
        "GSI1PK": drop_off_partition(d.state),
        "GSI1SK": f"{iso(d.created_at)}#{d.id}",
        "id": str(d.id),
        "pieces": d.pieces,
        "firing_type": d.firing_type,
        "glaze_type": d.glaze_type,
        "photos": [ref.index for ref in d.photos],
        "created_at": iso(d.created_at),
        "state": d.state.value,
        "load_id": None if d.load_id is None else str(d.load_id),
        "fired_at": _iso_or_none(d.fired_at),
        "closed_at": _iso_or_none(d.closed_at),
    }
    if any(ref.drop_off_id != d.id for ref in d.photos):
        raise ValueError(f"{d.id}'s photos must be its own")
    if d.contact is not None:
        attributes |= {
            "contact_name": d.contact.name,
            "contact_email": d.contact.email,
            "contact_phone": d.contact.phone,
        }
    if d.rejection is not None:
        attributes |= {
            "rejection_reason": d.rejection.reason,
            "rejection_message": d.rejection.message,
            "rejection_by": d.rejection.by,
            "rejection_at": iso(d.rejection.at),
        }
    return attributes


def _catalog_item(item: CatalogItem) -> dict[str, object]:
    return {
        "id": item.id,
        "name": item.name,
        "status": item.status.value,
        "needs_glaze_type": item.needs_glaze_type,
        "needs_message": item.needs_message,
    }


def _iso_or_none(at: datetime | None) -> str | None:
    return None if at is None else iso(at)


# Item -> entity -----------------------------------------------------------------------


def item_type(item: Mapping[str, Any]) -> str | None:
    value = item.get("type", {}).get("S")
    return value if isinstance(value, str) else None


def from_item(item: Mapping[str, Any]) -> Item:
    """The entity an item holds, at its stored version. `ValueError` for an item of no
    entity type (a counter, a rate-limit item) or one that doesn't parse."""
    values = {name: _plain(_deserializer.deserialize(value)) for name, value in item.items()}
    match values.get("type"):
        case "drop_off":
            return _to_drop_off(values)
        case "load":
            return Load(
                id=LoadId.parse(values["id"]),
                kiln=ItemId(values["kiln"]),
                firing_type=ItemId(values["firing_type"]),
                date=date.fromisoformat(values["date"]),
                status=LoadStatus(values["status"]),
                members=tuple(DropOffId.parse(m) for m in values["members"]),
                started_by=values["started_by"],
                started_at=parse_iso(values["started_at"]),
                fired_at=_time_or_none(values.get("fired_at")),
                version=values["version"],
            )
        case "studio":
            return Studio(
                sending_address=values["sending_address"],
                pickup_window_days=values["pickup_window_days"],
                pickup_hours_text=values["pickup_hours_text"],
                kilns=_catalog(values["kilns"]),
                firing_types=_catalog(values["firing_types"]),
                glaze_types=_catalog(values["glaze_types"]),
                reasons=_catalog(values["reasons"]),
                version=values["version"],
            )
        case "history":
            return SettingChange(at=parse_iso(values["at"]), by=values["by"], what=values["what"])
        case "email":
            return Email(
                drop_off_id=DropOffId.parse(values["drop_off_id"]),
                kind=EmailKind(values["kind"]),
                occasion=values["occasion"],
                status=EmailStatus(values["status"]),
                created_at=parse_iso(values["created_at"]),
                attempts=values["attempts"],
                claimed_at=_time_or_none(values.get("claimed_at")),
                sent_at=_time_or_none(values.get("sent_at")),
                error_code=values.get("error_code"),
                pickup_window_days=values.get("pickup_window_days"),
                retried_at=_time_or_none(values.get("retried_at")),
                version=values["version"],
            )
        case "submission":
            return Submission(
                token_hash=values["PK"].removeprefix("SUBMISSION#"),
                drop_off_id=DropOffId.parse(values["drop_off_id"]),
                pieces=values["pieces"],
                firing_type=values["firing_type"],
                glaze_type=values.get("glaze_type"),
                created_at=parse_iso(values["created_at"]),
                expires_at=parse_iso(values["expires_at"]),
            )
        case _:
            raise ValueError("not an entity's item")


def _to_drop_off(values: dict[str, Any]) -> DropOff:
    id = DropOffId.parse(values["id"])
    contact = None
    if "contact_name" in values:
        contact = Contact(
            name=values["contact_name"], email=values["contact_email"], phone=values["contact_phone"]
        )
    rejection = None
    if "rejection_reason" in values:
        rejection = Rejection(
            reason=ItemId(values["rejection_reason"]),
            message=values.get("rejection_message"),
            by=values["rejection_by"],
            at=parse_iso(values["rejection_at"]),
        )
    load_id = values.get("load_id")
    glaze_type = values.get("glaze_type")
    return DropOff(
        id=id,
        contact=contact,
        pieces=values["pieces"],
        firing_type=ItemId(values["firing_type"]),
        glaze_type=None if glaze_type is None else ItemId(glaze_type),
        photos=tuple(PhotoRef(id, index) for index in values["photos"]),
        created_at=parse_iso(values["created_at"]),
        state=DropOffState(values["state"]),
        load_id=None if load_id is None else LoadId.parse(load_id),
        rejection=rejection,
        fired_at=_time_or_none(values.get("fired_at")),
        closed_at=_time_or_none(values.get("closed_at")),
        version=values["version"],
    )


def _catalog(items: list[dict[str, Any]]) -> tuple[CatalogItem, ...]:
    return tuple(
        CatalogItem(
            id=ItemId(i["id"]),
            name=i["name"],
            status=ItemStatus(i["status"]),
            needs_glaze_type=i["needs_glaze_type"],
            needs_message=i["needs_message"],
        )
        for i in items
    )


def _time_or_none(text: str | None) -> datetime | None:
    return None if text is None else parse_iso(text)


def _plain(value: Any) -> Any:
    """A deserialized value with DynamoDB's `Decimal`s as `int`s, inside lists and maps."""
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError("the table holds whole numbers only")
        return int(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value
