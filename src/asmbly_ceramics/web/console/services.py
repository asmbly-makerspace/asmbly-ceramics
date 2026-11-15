"""What the console's pages call: the use cases of #3 and #5, the staff sign-in and the
session key. Phase 9 adds its use cases here."""

from dataclasses import dataclass

from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.secrets import Secrets
from asmbly_ceramics.ports.staff import StaffTokens
from asmbly_ceramics.use_cases.emails import EmailsNeedingAttention, RetryEmail
from asmbly_ceramics.use_cases.photos import ViewPhoto
from asmbly_ceramics.use_cases.reject import PreviewRejection, RejectDropOff, UndoRejection
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
    retry_email: RetryEmail
    emails_needing_attention: EmailsNeedingAttention

    @property
    def callback_url(self) -> str:
        return self.site_url.rstrip("/") + "/console/auth/callback"

    @property
    def signed_out_url(self) -> str:
        return self.site_url.rstrip("/") + "/console/signed-out"
