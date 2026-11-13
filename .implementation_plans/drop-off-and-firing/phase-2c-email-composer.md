---
phase_id: 2c
title: "The email composer and its templates"
epic: 1
implements: [2, 5]
depends_on: [1d]
domain: [app]
estimated_size: L
---

# Phase 2c: The email composer and its templates

> **Status:** [ ] Pending

Part of phase 2, split into 2a to 2d by `/prep` (see
[phase 2a](phase-2a-logging-studio-and-form-reads.md)). It needs only phase 1's types,
so it could be built beside 2a and 2b; the tracker builds it after them.

## Required reading

- [CLAUDE.md](../../CLAUDE.md): "Send email only from an address at `asmbly.org`",
  "escape it wherever it is shown or put in an email".
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md): the
  outbox; emails carry the photos inline.
- [Phase 1d](phase-1d-ports-and-fakes.md) (`OutgoingEmail`, `InlineImage`) and
  [phase 1b](phase-1b-drop-offs-photos-outbox.md) (`DropOff`, `Contact`, `Rejection`,
  `PhotoRef`) and [phase 1a](phase-1a-domain-core-and-studio.md) (`Studio`, `item`).
- Story #2 (the received email), #5 (the rejection email), and epic #1's **Decided**
  list (the rejection email follows the Kiln Ops template).
- The design's email board (epic #1's design comment): the received and needs-attention
  emails' sections and wording.
- Patterns: AsmblyMCPs `src/servers/ceramics/mail.py` (what it never logs).
- Jinja2's documentation on autoescaping (`select_autoescape`), on
  `Environment(undefined=StrictUndefined)` and on `PackageLoader`.

## Goal

The three emails (received, ready, rejected) and the staff test email are composed
from templates with everything a person typed escaped, ready for phase 3's mailer and
2d's rejection preview. `outgoing` turns a composed email into phase 1d's
`OutgoingEmail` with the photos inline. The templates ship with the package.

## Files to create

Under `src/asmbly_ceramics/`:

| Path | What |
| --- | --- |
| `mail/__init__.py` | Empty |
| `ports/composer.py` | `ComposedEmail`, the `Composer` Protocol (`received`, `ready`, `rejected`, `test`), `outgoing`, `cid`: what the use cases import |
| `mail/compose.py` | `JinjaComposer`, the one `Composer` (Jinja2) |
| `mail/templates/_layout.html` | The shared email frame: purple band with the Asmbly name, the ceramics bar, the footer |
| `mail/templates/received.html`, `received.txt` | "We received your drop-off" |
| `mail/templates/ready.html`, `ready.txt` | "Your pieces are ready for pickup" (used from phase 3) |
| `mail/templates/rejected.html`, `rejected.txt` | "Your drop-off needs attention" |
| `mail/templates/test.html`, `test.txt` | The staff test email (phase 3's `SendTestEmail`) |

Under `tests/`:

| Path | What |
| --- | --- |
| `tests/mail/__init__.py`, `tests/mail/test_compose.py` | The composer |
| `tests/ports/test_composer.py` (or the existing ports tests' module) | `outgoing` and `cid` |

## Files to modify

- Where the composer lives: The use cases import only the domain, the ports and each other (`tests/domain/test_imports.py`, phase 2a), so they never import `mail/` or Jinja2. `ComposedEmail`, the `Composer` Protocol, `outgoing` and `cid` live in `ports/composer.py` (decided in phase 2a's review, like "AWS behind ports": the use cases depend on an interface, the templates are its one implementation); `mail/compose.py` holds `JinjaComposer`, which satisfies `Composer`. Nothing under `ports/` imports Jinja2;
  phase 4 extends the import check to `mail/` (domain, ports and Jinja2).
- `pyproject.toml` and `uv.lock`: `uv add jinja2` (runtime). Never edit `uv.lock` by
  hand. Jinja2 ships its own types, so mypy needs no stubs.
- `pyproject.toml`: nothing for the templates, if `uv_build` already ships every file
  under the module directory (prep: its default includes the module's data files; there
  is no `[tool.uv.build-backend]` table today). The builder checks it once with
  `uv build --wheel` and lists the wheel (`unzip -l dist/*.whl`); only if the templates
  are missing does it add the `uv_build` setting uv's documentation gives. The check's
  result goes in the hand-off. `dist/` is not committed.

## Implementation details

### app: the composer (`ports/composer.py` and `mail/compose.py`)

`ComposedEmail`, `Composer` (a `Protocol` with the four methods below), `outgoing` and
`cid` are in `ports/composer.py`; `JinjaComposer` in `mail/compose.py` implements the
four methods.

```python
@dataclass(frozen=True, slots=True)
class ComposedEmail:
    subject: str
    html: str = field(repr=False)  # holds the person's name
    text: str = field(repr=False)


class JinjaComposer:  # mail/compose.py; ports/composer.py's `Composer` Protocol has the four methods
    def __init__(self) -> None:
        ...  # Environment(PackageLoader("asmbly_ceramics.mail"), autoescape=select_autoescape(["html"]),
        #             undefined=StrictUndefined); .txt templates render with autoescape off

    def received(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail: ...
    def ready(
        self, drop_off: DropOff, studio: Studio, sent_at: datetime, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail: ...
    def rejected(
        self, drop_off: DropOff, studio: Studio, image_src: Callable[[PhotoRef], str]
    ) -> ComposedEmail: ...
    def test(self, studio: Studio) -> ComposedEmail: ...  # phase 3's test email


def outgoing(
    composed: ComposedEmail, *, to: str, sending_address: str, photos: Sequence[tuple[PhotoRef, bytes]]
) -> OutgoingEmail:
    ...
    # from_name "Asmbly Ceramics", from_address and reply_to = sending_address,
    # inline images: content_id "photo-<index>", filename "AC-12-<index>.jpg"


def cid(ref: PhotoRef) -> str: ...  # "cid:photo-<index>"
```

- A drop-off without `contact` (closed) is a `ValueError` naming only its ID: a closed
  drop-off is never emailed. `rejected` needs `drop_off.rejection`; `ready` needs an
  aware `sent_at`. Item names come from `studio.item(...)` (a retired item still has its
  name).
- `outgoing` refuses a `sending_address` that isn't `is_sending_address` (phase 1d) with
  `ValueError`, before building anything, so the composer can't make a message from
  outside `asmbly.org`.

Content, following the design's email board and epic #1's **Decided** list (the Kiln
Ops templates, with the ID, the reason and the staff message added):

| Email | Subject | Body |
| --- | --- | --- |
| received | `We received your drop-off (AC-12)` | "Hi {name}, thanks for dropping off. Here's your ID:", the ID large, "Make sure each piece has a slip with this ID and your name.", pieces, firing (and glaze type), dropped off (Austin time, "Fri Nov 13, 10:42 AM"), the photos, "We'll email you again when it's fired and ready for pickup." |
| ready | `Ready for pickup (AC-12)` | "Your pieces from drop-off AC-12 have exited the kiln and are ready for pickup!", "Pick up by {sent_at + window, Austin date}. You have {window} days to collect them; after that, they may be subject to disposal.", "Pickup hours" and the hours text, "If you have any questions, reach out to our Kiln Ops team at {sending address}.", "~ Kiln Ops", the photos |
| rejected | `Your drop-off needs attention (AC-12)` | "One or more of your pieces from drop-off AC-12 has been rejected from kiln firing due to:", the reason, the staff message under "From Kiln Ops" when there is one, "Please make adjustments and resubmit for firing with the drop-off form; you'll get a new ID. If you have questions, please reach out to the kiln lead at {sending address}.", the pickup hours, "~ Kiln Ops", the photos |
| test | `Test email from Asmbly Ceramics` | "This is a test email from the ceramics studio's console. Emails to people who drop off are sent from {sending address}.", the pickup hours as they will appear |

- Every email's footer: "Asmbly Makerspace · 9701 Dessau Rd, Suite 304, Austin, TX
  78754. Reply to this email to reach ceramics staff."
- The subject holds the ID only, never a name, so nothing a person typed reaches a
  header.
- Everything typed (the name, the message, the hours text, item names) is escaped in
  the HTML by autoescape; the hours text and the message keep their line breaks
  (escaped first, then each line a paragraph). No link is built from typed text. No
  link to a kiln schedule (#9 is out of scope).
- The plain-text part says the same, without photos.
- The HTML uses inline styles only (email clients drop `<style>`) in the design's
  colours, and `<img src="{{ image_src(ref) }}" alt="Photo {n} of AC-12">`.
- The Asmbly logo is text in the band, not an image, in this phase; phase 6 may replace
  `_layout.html`'s band with the shared brand partial (the README's parallelism table).
- Nothing here logs.

## Tests

`tests/mail/test_compose.py`, with a made-up drop-off from `tests/domain/builders.py`:

- `test_each_email_has_its_subject_with_the_id`.
- `test_markup_in_the_name_message_and_hours_is_escaped` (`<script>` and `<img onerror>`
  come out as text).
- `test_line_breaks_in_the_hours_and_message_become_paragraphs`.
- `test_the_text_part_has_no_markup`.
- `test_inline_images_match_the_cid_references`.
- `test_ready_gives_the_pickup_date_from_when_it_is_sent` (the window from the studio,
  Austin date).
- `test_received_shows_the_drop_off_time_in_austin`.
- `test_rejected_includes_the_reason_and_the_message_and_omits_an_empty_message`.
- `test_a_retired_item_still_shows_its_name`.
- `test_a_closed_drop_off_cannot_be_composed`.
- `test_there_is_no_link_to_a_kiln_schedule`.
- `test_from_name_and_reply_to_are_set_by_outgoing`.
- `test_outgoing_refuses_a_sending_address_outside_asmbly`.
- `test_the_test_email_names_the_sending_address`.
- `test_the_templates_ship_with_the_package` (loads each template through the package
  loader).
- `test_composed_email_repr_holds_no_body`.

## Acceptance criteria

1. Every composed email escapes what people typed, names the ID in its subject, and
   says nothing of a kiln schedule (#2, #5).
2. The received email holds the ID, pieces, firing type (and glaze type), the Austin
   time and the photos (#2); the rejected email holds the reason and the staff message
   when there is one (#5).
3. `outgoing` sends from the studio's `asmbly.org` address only, with the photos inline
   under the `cid:` references the HTML uses.
4. The templates load through the package loader, and the wheel holds them.

## Verification

```bash
uv run pytest tests/mail
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
uv build --wheel && unzip -l dist/*.whl | grep mail/templates   # once, by the builder
```

Nothing to see in production.

## Rollout

Nothing reaches AWS.

## Admin actions

None.

## Hand-off

Filled in when the phase is done.

What the next phase can rely on, as planned:

- `ports.composer`: `Composer` (`received`, `ready`, `rejected`, `test`),
  `ComposedEmail`, `outgoing` and `cid`, which the use cases import; `mail.compose`:
  `JinjaComposer`, which composition and the use case tests build. Phase 3's mailer
  composes with them; 2d's and the console's preview pass their own `image_src`.
- Jinja2 is a runtime dependency.
