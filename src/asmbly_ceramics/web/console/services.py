"""What the console's pages call: the use cases of #3 to #7, #17 and #42, the staff sign-in and the
session key."""

from dataclasses import dataclass

from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.secrets import Secrets
from asmbly_ceramics.ports.staff import StaffTokens
from asmbly_ceramics.use_cases.counts import WeeklyCounts
from asmbly_ceramics.use_cases.delete_drop_off import DeleteDropOff
from asmbly_ceramics.use_cases.emails import EmailsNeedingAttention, RetryEmail
from asmbly_ceramics.use_cases.firing_log import FiringLog
from asmbly_ceramics.use_cases.loads import (
    AddManyToLoad,
    AddToLoad,
    ChangeLoad,
    CorrectStepTime,
    DeleteLoad,
    ListLoads,
    MarkFired,
    RemoveFromLoad,
    SaveFiringRecord,
    StartFiring,
    StartLoad,
    ViewLoad,
)
from asmbly_ceramics.use_cases.notes import (
    EditNote,
    LoadNotes,
    NoteCounts,
    RemoveNote,
    SearchNotes,
    WriteNote,
)
from asmbly_ceramics.use_cases.photos import ViewPhoto
from asmbly_ceramics.use_cases.reject import PreviewRejection, RejectDropOff, UndoRejection
from asmbly_ceramics.use_cases.settings import (
    AddCatalogItem,
    ChangeEmailSettings,
    DeleteCatalogItem,
    RecordNewElements,
    RestoreCatalogItem,
    RetireCatalogItem,
    SendTestEmail,
    SetDefaultProgram,
    SetKilnCounts,
    ViewStudio,
)
from asmbly_ceramics.use_cases.studio import CurrentStudio
from asmbly_ceramics.use_cases.view_drop_off import ViewDropOff
from asmbly_ceramics.use_cases.waiting import FindDropOffs, WaitingList


@dataclass(frozen=True)
class ConsoleServices:
    staff_tokens: StaffTokens
    secrets: Secrets  # the session key (`SecretName.SESSION_KEY`): sign-in state and CSRF tokens
    clock: Clock
    studio: CurrentStudio  # the rejection preview's From address
    # "https://ceramics.asmbly.org": the only allowed Origin, and the base of the two
    # fixed addresses the staff sign-in returns to. Never taken from a request.
    site_url: str
    waiting_list: WaitingList
    find_drop_offs: FindDropOffs
    view_drop_off: ViewDropOff
    view_photo: ViewPhoto
    preview_rejection: PreviewRejection
    reject_drop_off: RejectDropOff
    undo_rejection: UndoRejection
    delete_drop_off: DeleteDropOff
    retry_email: RetryEmail
    emails_needing_attention: EmailsNeedingAttention
    # Loads (#4)
    list_loads: ListLoads
    start_load: StartLoad
    view_load: ViewLoad
    change_load: ChangeLoad
    add_to_load: AddToLoad
    add_many_to_load: AddManyToLoad
    remove_from_load: RemoveFromLoad
    start_firing: StartFiring
    mark_fired: MarkFired
    delete_load: DeleteLoad
    # The firing record (the load page) and the firing log (#42)
    save_firing_record: SaveFiringRecord
    correct_step_time: CorrectStepTime
    firing_log: FiringLog
    # Firing notes (#17): on the load page, the notes search, and the firing log's counts
    write_note: WriteNote
    edit_note: EditNote
    remove_note: RemoveNote
    load_notes: LoadNotes
    search_notes: SearchNotes
    note_counts: NoteCounts
    # Settings (#6)
    view_studio: ViewStudio
    change_email_settings: ChangeEmailSettings
    send_test_email: SendTestEmail  # the console's only send: to the signed-in member
    add_item: AddCatalogItem
    retire_item: RetireCatalogItem
    restore_item: RestoreCatalogItem
    delete_item: DeleteCatalogItem
    set_default_program: SetDefaultProgram  # the settings page's programs, counts and new elements (#42)
    set_kiln_counts: SetKilnCounts
    record_new_elements: RecordNewElements
    # Weekly counts (#7)
    weekly_counts: WeeklyCounts

    @property
    def callback_url(self) -> str:
        return self.site_url.rstrip("/") + "/console/auth/callback"

    @property
    def signed_out_url(self) -> str:
        return self.site_url.rstrip("/") + "/console/signed-out"
