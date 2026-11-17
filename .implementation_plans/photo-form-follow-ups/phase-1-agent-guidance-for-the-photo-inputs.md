# Phase 1: The agents' guidance describes the two photo inputs

> **Status:** [x] Complete — 2026-11-17 on branch claude/wizardly-bell-u8y238

## Required reading

- `CLAUDE.md` (the rules; this phase changes guidance only).
- `src/asmbly_ceramics/web/templates/form.html`: line 5 (`{% set photo_accept = ... %}`,
  decision 0002's list) and lines 70 to 72 (the library picker `#photos` with `multiple`,
  the `#take-photo` button, hidden until the script shows it, and the hidden camera input
  `#photos-camera` with `capture="environment"`, no `multiple`, no `name`).
- `src/asmbly_ceramics/web/static/upload.js`: `addFiles(input, fromCamera)` (both inputs
  feed one list), `updateControls()` (a full list disables both inputs and the button),
  and the `matchMedia("(pointer: coarse)")` block (the button shows on touch screens only).
- `tests/web/test_form.py`: `test_the_photo_field_accepts_only_jpeg_png_and_webp_and_doesnt_force_the_camera`
  and `test_the_camera_input_takes_one_photo_from_the_rear_camera_and_posts_nothing`, which
  pin the accept list on both inputs.
- `src/asmbly_ceramics/adapters/images.py`: `FORMATS = ("JPEG", "PNG", "WEBP")`, the
  server's real check.
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md), "Photos go
  straight to S3 and are re-encoded on submit", its accepted consequence (the specific
  `accept` list, so an iPhone converts HEIC to JPEG).
- The files this phase edits, whole: `.claude/agents/build/coder.md`,
  `.claude/agents/build/architect.md`, `.claude/agents/build/critic.md`,
  `.claude/agents/plan/web.md`, `.claude/agents/review/web.md`.

## Goal

Every agent and skill file describes the drop-off form's photo field as it is: a library
picker and a "Take a photo" camera input feeding one list, with the accept list as a
template literal from decision 0002, pinned by tests and checked for real by the
server's inspector. No file says the accept list comes from the domain, and none
recommends `accept="image/*"`.

## Files to create

None.

## Files to modify

Each edit replaces only the sentences quoted; the surrounding text stays.

- `.claude/agents/build/coder.md`
  - Lines 92 to 95 (under **Hostile input**): today "The page's own checks (`required`,
    `maxlength`, `accept`) are for the person's convenience only, and their values come
    from the domain constants, not copies." Make it: the page's own checks (`required`,
    `maxlength`, `min`/`max`, `accept`) are for the person's convenience only; the
    lengths, counts and sizes come from the domain constants (`domain/limits.py`), not
    copies; the photo `accept` list is the one literal in `form.html` (decision 0002's
    `image/jpeg,image/png,image/webp`, pinned by `tests/web/test_form.py`), and the
    server's photo inspector is the real check.
  - Lines 122 to 123 (under **The form must work on a phone**): today "Photos:
    `<input type="file" accept="...">` with `multiple`, which offers the camera and the
    library on a phone; the accepted types come from the domain's list." Replace with a
    bullet saying: photos come from two inputs that feed one list in `upload.js`: the
    library picker (`<input id="photos" type="file" multiple>`) and the camera input
    (`<input id="photos-camera" type="file" capture="environment">`, one photo per pick,
    no `name`, opened by the "Take a photo" button, which the script shows on touch
    screens only); both take `accept="{{ photo_accept }}"`, the template's one literal
    (decision 0002's list, pinned by tests); a full list disables both and the button;
    neither input posts anything, only the upload slots do. Never add `capture` to the
    library picker (it would hide the library) and never use `getUserMedia` (the phone's
    own camera app, not a viewfinder).
- `.claude/agents/plan/web.md`, line 121 to 124 (the **Phones** pattern): today "...and the
  camera through `accept="image/*"`." Make it: the camera through a separate
  `capture="environment"` input behind a "Take a photo" button, beside a library picker,
  both with decision 0002's specific `accept` list (`image/*` would let an iPhone send
  HEIC, which the server refuses).
- `.claude/agents/build/architect.md`, line 166 to 167 (**a limit that must match in two
  places**): today "the domain constant and the page's `maxlength`, `accept` or hint
  text". Make it: the domain constant and the page's `maxlength`, `min`/`max` or hint
  text; the page's photo `accept` list and the types the server's inspector accepts
  (`adapters/images.py`); the presigned POST's size condition and the domain's 10 MB.
- `.claude/agents/build/critic.md`, lines 45 to 48 (**Domain and page limits**): today
  "the page's `maxlength`, `accept`, `min`/`max` and hint text come from the domain
  constants (...)". Make it: `maxlength`, `min`/`max` and hint text come from the domain
  constants (the same list as today); the photo `accept` list (on both photo inputs)
  matches the types the server's inspector accepts, as one template literal.
- `.claude/agents/review/web.md`, lines 106 to 108 (**Phones (WARN)**): today "the photo
  field opens the camera or library (`accept="image/jpeg,image/png,image/webp"`)". Make
  it: the library picker and, on a touch screen, the "Take a photo" button (camera input
  with `capture="environment"`) both work and feed one list, both with
  `accept="image/jpeg,image/png,image/webp"`.

## Implementation details

### docs

Guidance text only. Before editing, grep again so nothing found since planning is missed:

```bash
grep -rn 'accept=\|domain.s list\|type="file"\|image/\*' .claude/ docs/ README.md CONTRIBUTING.md CLAUDE.md
```

Expected hits after the phase: decision 0002 and 0009 (records, left as written), the
edited lines above, and nothing that says the accept list comes from the domain or
recommends `image/*`. Generic phrases such as "the camera or the photo library"
(`plan/web.md` line 25, `prep/auditor.md`, `plan-product/studio-flow.md`,
`prep/SKILL.md`) are still true and stay.

Keep each file's style: plain sentences, backticks for code, no new headings. Don't touch
`.claude/hooks/` or `.claude/settings.json`.

## Tests

No new test: this phase changes no behaviour. The existing repository checks must still
pass, in particular `tests/repo/test_claude.py` (skills and agents well formed),
`tests/repo/test_links.py` (relative links resolve) and `tests/repo/test_checks.py`
(the documents name the CI tool versions).

## Acceptance criteria

- [x] `grep -rn "domain's list" .claude/` finds nothing.
- [x] `grep -rn 'image/\*' .claude/` finds nothing.
- [x] `coder.md` names both photo inputs (`#photos` with `multiple`, `#photos-camera` with
      `capture="environment"`), the "Take a photo" button shown on touch screens only, the
      one list they feed, and the accept list as the template's literal from decision
      0002, pinned by tests.
- [x] `architect.md` and `critic.md` no longer say the `accept` list comes from the
      domain constants; they tie it to the server's inspector.
- [x] `review/web.md`'s phone check names the library picker and the "Take a photo"
      button.
- [x] No other file changes.

## Verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

All pass (the phase changes Markdown only; `tests/repo/` is what checks it). In
production: nothing to see; the deployed app is unchanged.

## Rollout

Nothing reaches AWS. Merging deploys the app as every merge does, with no template, IAM
or script change, so the deployed app behaves as before.

## Admin actions

None.

## Hand-off

Done. Phase 2 can rely on:

- `.claude/agents/build/coder.md`, under **The form must work on a phone**: the bullet
  that starts "Photos come from two inputs that feed one list in `upload.js`" and ends
  "never use `getUserMedia` (the phone's own camera app, not a viewfinder)." Phase 2
  adds its sentence pointing at the behavioural test right after that bullet's last
  sentence.
- The **Hostile input** bullet in the same file now names the `accept` literal in
  `form.html`, pinned by `tests/web/test_form.py`, with `adapters/images.py` as the
  real check.
- One deviation from the wording above: `plan/web.md` says "a wildcard of every image
  type" instead of quoting `image/*`, so the acceptance grep for `image/\*` in
  `.claude/` finds nothing.
- Left as written (outside this phase's quoted sentences): `critic.md`'s "The presigned
  POST's size and type conditions agree with the domain." The type condition is
  decision 0002's `image/` prefix, not a domain constant; a later edit may reword it.
