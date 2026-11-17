"""Submitting a drop-off from the public form (#2).

Everything in a `SubmitRequest` is hostile until checked here: the token and the device
cookie by shape, then the rate limit, then every field and photo at once, then the limit
per recipient address (#18) and the daily cap on received emails (#30, decision 0008),
counted only for a drop-off that would otherwise be stored. The raw token, cookie,
source address and recipient address are hashed (`KeyHasher`) before anything is read,
counted, stored or logged. A repeated token answers with the drop-off it already made.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from asmbly_ceramics.domain.dropoff import DropOffDetails, new_drop_off
from asmbly_ceramics.domain.email import EmailKind, new_email
from asmbly_ceramics.domain.errors import FORM_EXPIRED_KEY, DropOffNotTaken, InvalidDetails
from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import ADDRESS_LIMIT, DEVICE_LIMIT, SUBMISSION_LIFETIME
from asmbly_ceramics.domain.photos import PHOTO_COUNT_KEY, CheckedPhoto, PhotoRefusal, distinct_slots
from asmbly_ceramics.domain.studio import CatalogList, Studio
from asmbly_ceramics.ports.clock import Clock
from asmbly_ceramics.ports.errors import Unavailable, error_code
from asmbly_ceramics.ports.ids import IdNumbers
from asmbly_ceramics.ports.images import PhotoInspector, PhotoRefused
from asmbly_ceramics.ports.photos import PhotosAlreadyKept, PhotoStore, UploadMissing
from asmbly_ceramics.ports.rate_limit import RateLimiter
from asmbly_ceramics.ports.records import CommitOutcomeUnknown, Conflict, Put, Records, Submission
from asmbly_ceramics.use_cases.keys import KeyHasher, is_form_token
from asmbly_ceramics.use_cases.limits import check_limits, check_received_cap, check_recipient
from asmbly_ceramics.use_cases.log import log_event
from asmbly_ceramics.use_cases.received import ReceivedView, is_live, live_submission, received_view
from asmbly_ceramics.use_cases.studio import CurrentStudio

NUMBER_TRIES = 3  # IDs taken in all when photos or a record are already under a number
_PHOTO_MISSING = f"photo.{PhotoRefusal.MISSING}"


@dataclass(frozen=True, slots=True)
class SubmitRequest:
    name: str = field(repr=False)
    email: str = field(repr=False)
    phone: str = field(repr=False)
    # Raw public text until checked: a person could type anything here, so no repr.
    pieces: str = field(repr=False)
    firing_type: str = field(repr=False)
    glaze_type: str | None = field(repr=False)
    upload_slots: tuple[str, ...] = field(repr=False)  # bearer handles, as `UploadSlot.slot_id`
    submission_token: str = field(repr=False)  # the token the form page carried
    device: str = field(repr=False)  # the raw device cookie
    source_address: str = field(repr=False)  # the last X-Forwarded-For value


@dataclass(frozen=True, slots=True)
class Submitted:
    view: ReceivedView  # from the Submission item: no contact details
    token_hash: str = field(repr=False)  # what the web layer signs into __Host-received
    repeated: bool  # True when this token had already made the drop-off


class SubmitDropOff:
    def __init__(
        self,
        records: Records,
        ids: IdNumbers,
        photos: PhotoStore,
        inspector: PhotoInspector,
        limiter: RateLimiter,
        hasher: KeyHasher,
        clock: Clock,
        studio: CurrentStudio,
    ) -> None:
        self._records = records
        self._ids = ids
        self._photos = photos
        self._inspector = inspector
        self._limiter = limiter
        self._hasher = hasher
        self._clock = clock
        self._studio = studio

    def __call__(self, request: SubmitRequest) -> Submitted:
        # 1. The token and the device, by shape, before anything is counted, so callers
        # without a cookie never share one `device#` bucket.
        if not is_form_token(request.submission_token) or not is_form_token(request.device):
            _refused("form_expired")
            raise InvalidDetails({"form": FORM_EXPIRED_KEY})
        now = self._clock.now()
        token_hash = self._hasher.submission(request.submission_token)
        stored = self._records.submission(token_hash)
        if stored is not None:
            if is_live(stored, now):
                # A refresh or a double tap: the same drop-off, nothing counted or stored.
                log_event("drop_off_repeated", drop_off_id=str(stored.drop_off_id))
                return Submitted(received_view(stored), token_hash, repeated=True)
            # Expired but not yet deleted by the TTL: every Put of this key would conflict.
            _refused("form_expired")
            raise InvalidDetails({"form": FORM_EXPIRED_KEY})

        # 2. The rate limit (#2), failing closed.
        self._check_limits(request, now)

        # 3. The slots, before any photo read; then every field.
        slots = distinct_slots(request.upload_slots)
        if slots is None:
            _refused("invalid_details", fields="photos")
            raise InvalidDetails({"photos": PHOTO_COUNT_KEY})
        errors: dict[str, str] = {}
        studio = self._studio()
        details: DropOffDetails | None = None
        try:
            details = DropOffDetails.create(
                name=request.name,
                email=request.email,
                phone=request.phone,
                pieces=request.pieces,
                firing_type=request.firing_type,
                glaze_type=request.glaze_type,
                photo_count=len(slots),
                studio=studio,
            )
        except InvalidDetails as refused:
            errors.update(refused.errors)

        # 4. The photos, every one, so the page shows every problem at once.
        checked: list[CheckedPhoto] = []
        for n, slot in enumerate(slots, start=1):
            problem = self._check_photo(slot, checked)
            if problem is not None:
                errors[f"photo.{n}"] = problem
        if errors or details is None:
            if _PHOTO_MISSING in errors.values():
                # A double tap's other request may have committed and used the uploads up.
                winner = live_submission(self._records, token_hash, now)
                if winner is not None:
                    log_event("drop_off_repeated", drop_off_id=str(winner.drop_off_id))
                    return Submitted(received_view(winner), token_hash, repeated=True)
            _refused("invalid_details", fields=",".join(sorted(errors)))
            raise InvalidDetails(errors)

        # 4b. The recipient's limit (#18), then the daily cap on received emails (#30),
        # only for a drop-off that would otherwise be stored, so a refused field never
        # counts. A refused recipient isn't counted against the cap, so one address being
        # flooded can't use up the studio's day (decision 0008). Outside the ID loop, so a
        # retry with the next ID counts once. A double tap whose two requests race both
        # pass step 1 and both count here, two of the recipient's three and two of the
        # cap's slots (decision 0008 accepts both); when the other one took the last slot
        # and stored the drop-off, it is this one's answer. The recipient's hit stays
        # spent when nothing is stored after it (the cap refuses or can't be counted, or a
        # later step fails), as decision 0008 records. Both refusals give the same page.
        try:
            self._check_recipient(details.contact.email, now)
            self._check_cap(studio, now)
        except DropOffNotTaken:
            winner = self._winner_or_none(token_hash, now)
            if winner is None:
                raise
            log_event("drop_off_repeated", drop_off_id=str(winner.drop_off_id))
            return Submitted(received_view(winner), token_hash, repeated=True)

        firing_type = studio.item(CatalogList.FIRING_TYPES, details.firing_type).name
        glaze_type = (
            None
            if details.glaze_type is None
            else studio.item(CatalogList.GLAZE_TYPES, details.glaze_type).name
        )

        # 5 to 7. The ID, the photos kept under it, and one commit.
        tries = 0
        while True:
            tries += 1
            drop_off_id = self._ids.next_drop_off_id()
            try:
                refs = self._photos.keep(drop_off_id, checked)
            except PhotosAlreadyKept:
                _skipped(drop_off_id, "photos_already_kept")
                if tries >= NUMBER_TRIES:
                    raise
                continue
            submission = Submission(
                token_hash=token_hash,
                drop_off_id=drop_off_id,
                pieces=details.pieces,
                firing_type=firing_type,
                glaze_type=glaze_type,
                created_at=now,
                expires_at=now + SUBMISSION_LIFETIME,
            )
            try:
                self._records.commit(
                    [
                        Put(new_drop_off(drop_off_id, details, refs, now)),
                        Put(new_email(drop_off_id, EmailKind.RECEIVED, now)),
                        Put(submission),
                    ]
                )
            except Conflict:
                # The winner is read before anything is deleted: `Conflict` should mean
                # nothing was written, but a stored submission naming this drop-off means
                # it landed after all, and its photos are kept.
                try:
                    winner = live_submission(self._records, token_hash, now)
                except Exception:
                    # Can't tell; trust `Conflict`: the kept photos have no record.
                    self._delete_kept(drop_off_id)
                    raise
                if winner is None or winner.drop_off_id != drop_off_id:
                    deleted = self._delete_kept(drop_off_id)
                    if winner is not None:
                        # The same token committed first, in a race.
                        self._discard(slots, winner.drop_off_id)
                        log_event("drop_off_repeated", drop_off_id=str(winner.drop_off_id))
                        return Submitted(received_view(winner), token_hash, repeated=True)
                    if not deleted:
                        raise
                    _skipped(drop_off_id, "conflict")
                    if tries >= NUMBER_TRIES:
                        raise
                    continue
                submission = winner
            except Exception as error:
                landed = self._landed_anyway(drop_off_id, token_hash, error)
                if landed is None:
                    if isinstance(error, CommitOutcomeUnknown):
                        # It may still land after this read: deleting the photos could
                        # leave a drop-off without them, so the backstop (#19) has them.
                        log_event(
                            "photos_not_deleted",
                            level=logging.ERROR,
                            drop_off_id=str(drop_off_id),
                            error_code=_code(error),
                        )
                        raise
                    self._delete_kept(drop_off_id)
                    raise
                submission = landed
            self._discard(slots, drop_off_id)
            log_event("drop_off_submitted", drop_off_id=str(drop_off_id), count=len(refs))
            return Submitted(received_view(submission), token_hash, repeated=False)

    def _check_limits(self, request: SubmitRequest, now: datetime) -> None:
        # Hashed before counting: a key that can't be read goes up with nothing counted.
        device_key = self._hasher.device(request.device)
        address_key = self._hasher.address(request.source_address)
        check_limits(
            self._limiter,
            device_key=device_key,
            device_limit=DEVICE_LIMIT,
            address_key=address_key,
            address_limit=ADDRESS_LIMIT,
            now=now,
            refused_event="drop_off_refused",
        )

    def _check_recipient(self, address: str, now: datetime) -> None:
        # The key was read for the device's hash in step 2, so no key failure starts here.
        check_recipient(
            self._limiter,
            recipient_key=self._hasher.recipient(address),
            now=now,
            refused_event="drop_off_refused",
        )

    def _check_cap(self, studio: Studio, now: datetime) -> None:
        # The setting is read from the studio this request already read (settings as data).
        check_received_cap(
            self._limiter, per_day=studio.received_emails_per_day, now=now, refused_event="drop_off_refused"
        )

    def _winner_or_none(self, token_hash: str, now: datetime) -> Submission | None:
        """The same token's stored drop-off after a refusal; `None` when there is none or
        it can't be read, so the refusal stands."""
        try:
            return live_submission(self._records, token_hash, now)
        except Exception as error:
            log_event("submission_unreadable", level=logging.WARNING, error_code=_code(error))
            return None

    def _check_photo(self, slot: str, checked: list[CheckedPhoto]) -> str | None:
        """Reads and inspects one upload; its message key when refused."""
        try:
            data = self._photos.read_upload(slot)
        except UploadMissing:
            return _PHOTO_MISSING
        try:
            checked.append(self._inspector.inspect(data))
        except PhotoRefused as refused:
            return f"photo.{refused.kind}"
        return None

    def _landed_anyway(self, drop_off_id: DropOffId, token_hash: str, error: Exception) -> Submission | None:
        """After a commit that raised something other than `Conflict`: a timed-out
        transaction can still have landed. The stored submission when it holds this
        drop-off; `None` when nothing is stored. If that can't be read either, the kept
        photos are left for the backstop (they may belong to a stored drop-off) and the
        commit's error goes up."""
        try:
            stored = self._records.submission(token_hash)
        except Exception as unreadable:
            log_event(
                "photos_not_deleted",
                level=logging.ERROR,
                drop_off_id=str(drop_off_id),
                error_code=_code(unreadable),
            )
            raise error from unreadable
        if stored is not None and stored.drop_off_id == drop_off_id:
            return stored
        return None

    def _delete_kept(self, drop_off_id: DropOffId) -> bool:
        """The close (#7) only deletes photos that have a record, so a failed commit
        deletes the ones it kept. False when that fails too: the backstop (#19) removes
        them, and the caller raises the commit's error."""
        try:
            self._photos.delete_drop_off(drop_off_id)
        except Exception as error:
            log_event(
                "photos_not_deleted",
                level=logging.ERROR,
                drop_off_id=str(drop_off_id),
                error_code=_code(error),
            )
            return False
        return True

    def _discard(self, slots: tuple[str, ...], drop_off_id: DropOffId) -> None:
        """Uses the raw uploads up once a drop-off made from them is committed."""
        try:
            self._photos.discard_uploads(slots)
        except Exception as error:
            # The drop-off is stored, so nothing here fails its request; the bucket's
            # lifecycle rule removes the uploads.
            log_event(
                "uploads_not_discarded",
                level=logging.WARNING,
                drop_off_id=str(drop_off_id),
                error_code=_code(error),
            )


def _code(error: Exception) -> str:
    """An error's code for a log: a port's code, or the exception's class name."""
    return error_code(error.code if isinstance(error, Unavailable) else type(error).__name__)


def _refused(reason: str, *, fields: str | None = None) -> None:
    if fields is None:
        log_event("drop_off_refused", reason=reason)
    else:
        log_event("drop_off_refused", reason=reason, fields=fields)


def _skipped(drop_off_id: DropOffId, reason: str) -> None:
    log_event("drop_off_id_skipped", level=logging.WARNING, drop_off_id=str(drop_off_id), reason=reason)
