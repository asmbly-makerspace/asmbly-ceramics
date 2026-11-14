"""The `world` fixture: every in-memory fake, and the use cases built on them.

Phases 2b, 2d and 3 add their use cases here; `tests/use_cases/flows.py` drives them.
Test data is made up and built in code (`tests/domain/builders.py`), so no line reads as
a real address.
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
from asmbly_ceramics.mail.compose import JinjaComposer
from asmbly_ceramics.use_cases.close import CloseFinished
from asmbly_ceramics.use_cases.counts import WeeklyCounts
from asmbly_ceramics.use_cases.emails import EmailsNeedingAttention, RetryEmail, SendPendingEmail
from asmbly_ceramics.use_cases.keys import KeyHasher
from asmbly_ceramics.use_cases.loads import (
    AddToLoad,
    ChangeLoad,
    ListLoads,
    MarkFired,
    RemoveFromLoad,
    StartFiring,
    StartLoad,
    ViewLoad,
)
from asmbly_ceramics.use_cases.received import ReceivedSummary
from asmbly_ceramics.use_cases.reject import PreviewRejection, RejectDropOff, UndoRejection
from asmbly_ceramics.use_cases.settings import (
    AddCatalogItem,
    ChangeEmailSettings,
    DeleteCatalogItem,
    RestoreCatalogItem,
    RetireCatalogItem,
    SendTestEmail,
    ViewStudio,
)
from asmbly_ceramics.use_cases.studio import CurrentStudio, ViewStudioChoices
from asmbly_ceramics.use_cases.submit import SubmitDropOff
from asmbly_ceramics.use_cases.uploads import RequestUploadSlots
from asmbly_ceramics.use_cases.view_drop_off import ViewDropOff
from asmbly_ceramics.use_cases.waiting import FindDropOffs, WaitingList
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
    composer: JinjaComposer
    waiting: WaitingList
    find: FindDropOffs
    view: ViewDropOff
    preview: PreviewRejection
    reject: RejectDropOff
    undo: UndoRejection
    start_load: StartLoad
    change_load: ChangeLoad
    add_to_load: AddToLoad
    remove_from_load: RemoveFromLoad
    start_firing: StartFiring
    mark_fired: MarkFired
    view_load: ViewLoad
    list_loads: ListLoads
    send_email: SendPendingEmail
    retry_email: RetryEmail
    emails_needing_attention: EmailsNeedingAttention
    view_studio: ViewStudio
    change_email_settings: ChangeEmailSettings
    send_test_email: SendTestEmail
    add_item: AddCatalogItem
    retire_item: RetireCatalogItem
    restore_item: RestoreCatalogItem
    delete_item: DeleteCatalogItem
    close: CloseFinished
    counts: WeeklyCounts

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
    composer = JinjaComposer()
    mailer = MemoryMailer()
    return World(
        records=records,
        ids=ids,
        photos=photos,
        inspector=inspector,
        mailer=mailer,
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
        composer=composer,
        waiting=WaitingList(records, clock, studio),
        find=FindDropOffs(records, clock, studio),
        view=ViewDropOff(records, clock, studio),
        preview=PreviewRejection(records, clock, studio, composer),
        reject=RejectDropOff(records, clock, studio),
        undo=UndoRejection(records, clock),
        start_load=StartLoad(records, ids, clock, studio),
        change_load=ChangeLoad(records, studio),
        add_to_load=AddToLoad(records),
        remove_from_load=RemoveFromLoad(records),
        start_firing=StartFiring(records),
        mark_fired=MarkFired(records, clock),
        view_load=ViewLoad(records, clock, studio),
        list_loads=ListLoads(records, clock),
        send_email=SendPendingEmail(records, photos, mailer, clock, studio, composer),
        retry_email=RetryEmail(records, clock),
        emails_needing_attention=EmailsNeedingAttention(records, clock),
        view_studio=ViewStudio(records, studio),
        change_email_settings=ChangeEmailSettings(records, clock, studio),
        send_test_email=SendTestEmail(mailer, studio, composer),
        add_item=AddCatalogItem(records, clock, studio),
        retire_item=RetireCatalogItem(records, clock, studio),
        restore_item=RestoreCatalogItem(records, clock, studio),
        delete_item=DeleteCatalogItem(records, clock, studio),
        close=CloseFinished(records, photos, clock, studio),
        counts=WeeklyCounts(records, clock, studio),
    )
