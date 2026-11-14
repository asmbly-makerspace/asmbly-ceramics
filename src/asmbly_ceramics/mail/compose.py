"""`JinjaComposer`: the studio's emails, composed from the templates shipped with the
package (`mail/templates/`).

Everything a person typed (the name, the rejection message, the pickup hours, item
names) reaches the HTML only through autoescape; line breaks become paragraphs in the
templates, one escaped line each, so nothing here marks text as safe. The subject holds
the drop-off's ID only, so nothing typed reaches a header. Times are Austin's
(`STUDIO_TZ`), formatted by hand so the locale can't change them. Nothing here logs.
"""

from collections.abc import Callable
from datetime import date, datetime

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from asmbly_ceramics.domain.closing import pickup_day
from asmbly_ceramics.domain.dropoff import Contact, DropOff
from asmbly_ceramics.domain.errors import UnknownItem
from asmbly_ceramics.domain.ids import DropOffId, ItemId
from asmbly_ceramics.domain.limits import STUDIO_TZ
from asmbly_ceramics.domain.photos import PhotoRef
from asmbly_ceramics.domain.studio import CatalogList, Studio
from asmbly_ceramics.ports.composer import ComposedEmail

FOOTER = (
    "Asmbly Makerspace · 9701 Dessau Rd, Suite 304, Austin, TX 78754. "
    "Reply to this email to reach ceramics staff."
)
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def austin_day(day: date) -> str:
    """`Fri Nov 13`."""
    return f"{_DAYS[day.weekday()]} {_MONTHS[day.month - 1]} {day.day}"


def austin_time(at: datetime) -> str:
    """`Fri Nov 13, 10:42 AM`, in Austin time."""
    local = at.astimezone(STUDIO_TZ)
    hour = local.hour % 12 or 12
    return f"{austin_day(local.date())}, {hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def pickup_by(sent_at: datetime, window_days: int) -> date:
    """The last Austin day of the pickup window (`domain.closing.pickup_day`), counted
    from when the ready email went out; the close waits until that day has ended."""
    return pickup_day(sent_at, window_days)


def counted(count: int, noun: str) -> str:
    """`1 piece`, `3 pieces`."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def lines(text: str) -> list[str]:
    """The text's non-blank lines, each shown as its own paragraph."""
    return [line for line in text.splitlines() if line.strip()]


class JinjaComposer:
    """The one `ports.composer.Composer`."""

    def __init__(self) -> None:
        # `.html` templates are autoescaped; `.txt` ones are plain text and are not.
        self._env = Environment(
            loader=PackageLoader("asmbly_ceramics.mail"),
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def received(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail:
        context = self._drop_off_context(drop_off, studio, image_src)
        glaze = (
            _name(drop_off, studio, CatalogList.GLAZE_TYPES, drop_off.glaze_type)
            if drop_off.glaze_type is not None
            else None
        )
        return self._compose(
            "received",
            f"We received your drop-off ({drop_off.id})",
            context,
            drop_off.id,
            pieces=counted(drop_off.pieces, "piece"),
            firing_type=_name(drop_off, studio, CatalogList.FIRING_TYPES, drop_off.firing_type),
            glaze_type=glaze,
            dropped_off=austin_time(drop_off.created_at),
        )

    def ready(
        self, drop_off: DropOff, studio: Studio, sent_at: datetime, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail:
        if sent_at.utcoffset() is None:
            raise ValueError(f"{drop_off.id}'s ready email needs an aware time")
        context = self._drop_off_context(drop_off, studio, image_src)
        return self._compose(
            "ready",
            f"Ready for pickup ({drop_off.id})",
            context,
            drop_off.id,
            pickup_by=austin_day(pickup_by(sent_at, studio.pickup_window_days)),
            window=counted(studio.pickup_window_days, "day"),
        )

    def rejected(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail:
        context = self._drop_off_context(drop_off, studio, image_src)
        rejection = drop_off.rejection
        if rejection is None:
            raise ValueError(f"{drop_off.id} has no rejection to email")
        return self._compose(
            "rejected",
            f"Your drop-off needs attention ({drop_off.id})",
            context,
            drop_off.id,
            reason=_name(drop_off, studio, CatalogList.REASONS, rejection.reason),
            message_lines=lines(rejection.message or ""),
        )

    def test(self, studio: Studio) -> ComposedEmail:
        return self._compose("test", "Test email from Asmbly Ceramics", self._studio_context(studio))

    def _studio_context(self, studio: Studio) -> dict[str, object]:
        return {
            "sending_address": studio.sending_address,
            "hours_lines": lines(studio.pickup_hours_text),
            "footer": FOOTER,
        }

    def _drop_off_context(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> dict[str, object]:
        contact = _contact(drop_off)
        return {
            **self._studio_context(studio),
            "id": str(drop_off.id),
            "name": contact.name,
            "photos": [(image_src(ref), ref.index) for ref in drop_off.photos],
        }

    def _compose(
        self,
        name: str,
        subject: str,
        context: dict[str, object],
        about: DropOffId | None = None,
        **more: object,
    ) -> ComposedEmail:
        values = {**context, **more, "subject": subject}
        return ComposedEmail(
            subject=subject,
            html=self._env.get_template(f"{name}.html").render(values),
            text=self._env.get_template(f"{name}.txt").render(values),
            drop_off_id=about,
        )


def _contact(drop_off: DropOff) -> Contact:
    if drop_off.contact is None:
        raise ValueError(f"{drop_off.id} is closed: a closed drop-off is never emailed")
    return drop_off.contact


def _name(drop_off: DropOff, studio: Studio, which: CatalogList, id: ItemId) -> str:
    """The item's name, retired or not; `ValueError` naming the drop-off for one the
    studio doesn't have, as `Composer` promises."""
    try:
        return studio.item(which, id).name
    except UnknownItem as error:
        raise ValueError(f"{drop_off.id} names an item missing from the studio's {which.value}") from error
