"""The `world` fixture: every in-memory fake, and the use cases built on them.

Phases 2b, 2d and 3 add their use cases here. Test data is made up and built in code
(`tests/domain/builders.py`), so no line reads as a real address.
"""

from dataclasses import dataclass

import pytest

from asmbly_ceramics.adapters.memory.clock import FixedClock
from asmbly_ceramics.adapters.memory.ids import MemoryIdNumbers
from asmbly_ceramics.adapters.memory.images import MemoryPhotoInspector
from asmbly_ceramics.adapters.memory.mailer import MemoryMailer
from asmbly_ceramics.adapters.memory.photos import MemoryPhotoStore
from asmbly_ceramics.adapters.memory.rate_limit import MemoryRateLimiter
from asmbly_ceramics.adapters.memory.records import MemoryRecords
from asmbly_ceramics.adapters.memory.secrets import MemorySecrets
from asmbly_ceramics.adapters.memory.staff_tokens import MemoryStaffTokens
from asmbly_ceramics.use_cases.keys import KeyHasher
from asmbly_ceramics.use_cases.received import ReceivedSummary
from asmbly_ceramics.use_cases.studio import CurrentStudio, ViewStudioChoices
from asmbly_ceramics.use_cases.submit import SubmitDropOff
from asmbly_ceramics.use_cases.uploads import RequestUploadSlots
from tests.domain.builders import NOW, a_sending_address

DEVICE = "made-up-device-cookie-0123456789"  # `is_form_token`'s shape
SOURCE_ADDRESS = "203.0.113.7"  # TEST-NET-3, a documentation address


@dataclass
class World:
    records: MemoryRecords
    ids: MemoryIdNumbers
    photos: MemoryPhotoStore
    inspector: MemoryPhotoInspector
    mailer: MemoryMailer
    staff_tokens: MemoryStaffTokens
    limiter: MemoryRateLimiter
    clock: FixedClock
    secrets: MemorySecrets
    hasher: KeyHasher
    studio: CurrentStudio
    choices: ViewStudioChoices
    received: ReceivedSummary
    upload_slots: RequestUploadSlots
    submit: SubmitDropOff

    def uploaded(self, *photos: bytes) -> tuple[str, ...]:
        """Fresh slots holding these made-up photo bytes, as the browser's posts leave them."""
        slots = self.photos.upload_slots(len(photos), self.clock.now())
        for slot, data in zip(slots, photos, strict=True):
            self.photos.put_upload(slot.slot_id, data)
        return tuple(slot.slot_id for slot in slots)


@pytest.fixture
def world() -> World:
    records = MemoryRecords()
    photos = MemoryPhotoStore()
    limiter = MemoryRateLimiter()
    clock = FixedClock(NOW)
    secrets = MemorySecrets()
    hasher = KeyHasher(secrets)
    studio = CurrentStudio(records, clock, a_sending_address())
    ids = MemoryIdNumbers()
    inspector = MemoryPhotoInspector()
    return World(
        records=records,
        ids=ids,
        photos=photos,
        inspector=inspector,
        mailer=MemoryMailer(),
        staff_tokens=MemoryStaffTokens(),
        limiter=limiter,
        clock=clock,
        secrets=secrets,
        hasher=hasher,
        studio=studio,
        choices=ViewStudioChoices(studio),
        received=ReceivedSummary(records, clock),
        upload_slots=RequestUploadSlots(photos, limiter, hasher, clock),
        submit=SubmitDropOff(records, ids, photos, inspector, limiter, hasher, clock, studio),
    )
