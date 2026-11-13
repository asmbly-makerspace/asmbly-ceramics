"""The ID page after Submit (#2): the drop-off's ID and what was dropped off, nothing else.

It reads only the `Submission` item, which carries this summary, so the public form never
reads a drop-off item, and `ReceivedView` has no field a name, email, phone or photo
could go in.
"""

from dataclasses import dataclass
from datetime import datetime

from asmbly_ceramics.domain.errors import SubmissionNotFound
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.records import Records, Submission
from asmbly_ceramics.use_cases.keys import is_submission_hash


@dataclass(frozen=True, slots=True)
class ReceivedView:
    id: DropOffId
    pieces: int
    firing_type: str  # the item's name when submitted
    glaze_type: str | None
    created_at: datetime  # the page shows it in Austin time


def received_view(submission: Submission) -> ReceivedView:
    return ReceivedView(
        id=submission.drop_off_id,
        pieces=submission.pieces,
        firing_type=submission.firing_type,
        glaze_type=submission.glaze_type,
        created_at=submission.created_at,
    )


def is_live(submission: Submission, now: datetime) -> bool:
    """The one expiry rule: a submission is live until `expires_at`, not at it. The
    table's TTL deletes late, so every reader of a submission checks it, here."""
    return now < submission.expires_at


def live_submission(records: Records, token_hash: str, now: datetime) -> Submission | None:
    """The submission stored under `token_hash`, or `None` when there is none or it has
    expired (`is_live`)."""
    submission = records.submission(token_hash)
    if submission is None or not is_live(submission, now):
        return None
    return submission


class ReceivedSummary:
    def __init__(self, records: Records, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def __call__(self, token_hash: str) -> ReceivedView:
        """`token_hash` is `KeyHasher.submission`'s, from the page's own signed cookie."""
        # Only `KeyHasher.submission`'s shape is looked up, so no raw token reaches `Records`.
        if not is_submission_hash(token_hash):
            raise SubmissionNotFound()
        submission = live_submission(self._records, token_hash, self._clock.now())
        if submission is None:
            raise SubmissionNotFound()
        return received_view(submission)
