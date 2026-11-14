"""Steps phase 3's tests share: drop-offs made through the form, loads fired, the queue sent.

Everything is made up (`tests/domain/builders.py`); each drop-off comes from its own
made-up device so the form's rate limit never interferes.
"""

from asmbly_ceramics.domain.email import Email, EmailKind, EmailStatus
from asmbly_ceramics.domain.ids import DropOffId, ItemId, LoadId
from asmbly_ceramics.ports.staff import StaffMember
from tests.domain.builders import STAFF, an_address
from tests.use_cases.conftest import World
from tests.use_cases.test_submit import a_device, a_request, a_token

STAFF_EMAIL = an_address("kiln.tech")
STAFF_MEMBER = StaffMember(STAFF, STAFF_EMAIL)
ATHENA = ItemId("athena")
HELIOS = ItemId("helios")
BISQUE = ItemId("bisque")
GLAZE = ItemId("glaze")


def dropped_off(
    world: World, number: int, *, firing_type: str = "bisque", glaze_type: str | None = None
) -> DropOffId:
    """A drop-off made through the form (its photos kept, its received email queued)."""
    request = a_request(
        world, token=a_token(number), device=a_device(number), firing_type=firing_type, glaze_type=glaze_type
    )
    return world.submit(request).view.id


def pending(world: World) -> list[Email]:
    return world.records.emails_in({EmailStatus.PENDING})


def send_all(world: World) -> list[EmailStatus | None]:
    """What the mailer function does for each pending email the stream delivers."""
    return [world.send_email(email.drop_off_id, email.kind, email.occasion) for email in pending(world)]


def loaded(
    world: World, *drop_offs: DropOffId, kiln: ItemId = ATHENA, firing_type: ItemId = BISQUE
) -> LoadId:
    """A loading load holding these drop-offs."""
    load = world.start_load(kiln, firing_type, None, STAFF_MEMBER)
    for drop_off in drop_offs:
        world.add_to_load(load.id, drop_off, confirmed=True, staff=STAFF_MEMBER)
    return load.id


def fired(world: World, *drop_offs: DropOffId) -> LoadId:
    """A fired load holding these drop-offs, their ready emails queued."""
    load_id = loaded(world, *drop_offs)
    load = world.start_firing(load_id, version(world, load_id), STAFF_MEMBER)
    world.mark_fired(load_id, load.version, STAFF_MEMBER)
    return load_id


def version(world: World, load_id: LoadId) -> int:
    load = world.records.load(load_id)
    assert load is not None
    return load.version


def email_of(world: World, drop_off_id: DropOffId, kind: EmailKind, occasion: str = "") -> Email:
    email = world.records.email(drop_off_id, kind, occasion)
    assert email is not None, f"no {kind} email for {drop_off_id}"
    return email
