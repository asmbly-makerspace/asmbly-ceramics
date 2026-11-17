# Photo form follow-ups: implementation plan

**Created:** 2026-11-17

## Overview

Pull request #52 (Refs #2) added a "Take a photo" button to the public drop-off form: a
library picker (`<input id="photos" type="file" multiple>`) and a hidden camera input
(`<input id="photos-camera" type="file" capture="environment">`, opened by the
`#take-photo` button on touch screens only) both feed one list in
`src/asmbly_ceramics/web/static/upload.js`. Its review left two follow-ups:

1. **The agents' guidance describes the old field.** `.claude/agents/build/coder.md`
   still says the photo field is one `<input type="file" accept>` with `multiple` and
   that "the accepted types come from the domain's list". There is no such list: the
   types are a literal in `src/asmbly_ceramics/web/templates/form.html`
   (`{% set photo_accept = "image/jpeg,image/png,image/webp" %}`, decision 0002's list,
   feeding both inputs), pinned by `tests/web/test_form.py`, and the server's inspector
   (`adapters/images.py`, `FORMATS = ("JPEG", "PNG", "WEBP")`) is the real check. A grep
   of `.claude/` found the same stale claim in three more places: `plan/web.md` says the
   camera comes "through `accept="image/*"`", which contradicts 0002; `build/architect.md`
   and `build/critic.md` say the page's `accept` comes from the domain constants.
   `review/web.md`'s phone check names one photo field.
2. **The script's behaviour is not tested.** The renumbering, the full-list disable, the
   add-time size message, the status line and the camera button's touch-only visibility
   are covered only by substring asserts on the script's text in
   `tests/web/test_form.py`. #52 was checked by hand with Playwright.

Phase 1 corrects the guidance. Phase 2 adds a behavioural test of `upload.js` with
Node's built-in test runner on a hand-written DOM stub, started by pytest, with no npm
package, no build step and no CI change.
[Decision 0009](../../docs/decisions/0009-the-upload-script-is-tested-with-nodes-own-test-runner.md)
(proposed, written with this plan) records that choice and the ones that lost.

What was found on 17 November 2026, from the code (nothing here touches AWS, so no AWS
read was needed):

- `upload.js` (325 lines) is a plain ES5 script in one function, reading its limits and
  sentences from `#photos-field`'s `data-*` attributes; its globals are `document`,
  `window` (`matchMedia`), `URL` (`createObjectURL`, `revokeObjectURL`), `fetch`,
  `FormData` and `HTMLFormElement`.
- CI (`.github/workflows/pr-checks.yml`, job `python`) runs `uv run pytest --cov` on
  `ubuntu-24.04`, whose image is assumed to have Node on its `PATH` (an assumption until
  the first CI run shows it); no workflow sets Node up.
  `tests/repo/test_checks.py` pins CLAUDE.md's "Done means verified" commands to what CI
  runs, so a new command would need CLAUDE.md, the README, CONTRIBUTING and the pull
  request template changed too. Started from pytest, the Node tests need none of that.
- Node 22 is installed here (`/opt/node22/bin/node`, on the `PATH`).
- `tests/repo/test_personal_data.py` scans `*.md`, `*.py`, `*.yml`, `*.yaml`, `*.json`,
  `*.toml`, `*.sh`, `*.txt`, `*.html` and `CODEOWNERS`, not `*.js` or `*.mjs`: neither
  `upload.js` nor a new JavaScript test would be scanned. `upload.js` holds nothing the
  scan's patterns match today.
- Ruff's `S603` is selected; the repository's precedent for a fixed subprocess in a test
  is `# noqa: S603 (a fixed command)` (`tests/test_composition.py`).

## Domain model

Unchanged. Neither phase touches an entity, a state, a rule, a use case, a port, an
adapter or a page's behaviour.

- The photo limits stay where they are: `PHOTOS_MIN`, `PHOTOS_MAX` and `PHOTO_MAX_BYTES`
  in `domain/limits.py`, sent to the page as `data-*` attributes; the accept list stays
  the template's literal (decision 0002), with the server's inspector as the check.
- Phase 2 tests `upload.js` as it is. If a test shows the script doing something wrong,
  the fix is part of phase 2, with that test as its regression test.
- **Room to grow.** The kiln schedule (#9) and a glaze log are server-rendered pages; if
  either ever gets a script of its own, it is tested the same way (a `tests/web/js/`
  test on the same stub, started by pytest), which decision 0009 lists as a reason to
  revisit the stub-or-library choice.

## Stories

No epic and no story: this is follow-up work on #2's form, so the phase documents carry
no frontmatter. Both phases go in one pull request, which says `Refs #2`; nothing here closes an issue.

| Story | Title | Phases |
| --- | --- | --- |
| #2 | Drop off a piece and get an ID on screen (follow-ups to #52 only) | 1, 2 (Refs only) |

## Phase tracker

| Phase | Title | Domain | Size | Status |
| --- | --- | --- | --- | --- |
| [1](phase-1-agent-guidance-for-the-photo-inputs.md) | The agents' guidance describes the two photo inputs | docs | S | [x] Complete |
| [2](phase-2-upload-script-behaviour-tests.md) | A behavioural test of the upload script | web, docs | M | [x] Complete |

## Dependencies

- Nothing outside this repository: no other plan, no work in asmbly-staff-login,
  AsmblyMCPs or the facilities repository, no by-hand AWS step.
- Phase 2 depends on phase 1: both edit `.claude/agents/build/coder.md` (phase 2 adds one
  sentence pointing at the new test under the text phase 1 rewrites).
- Phase 2 needs Node 20 or later on the `PATH` wherever `uv run pytest --cov` runs
  (decision 0009). GitHub's `ubuntu-24.04` image has it; this machine has Node 22.

## Parallelism

| Pair | Verdict | Why |
| --- | --- | --- |
| 1 and 2 | sequential-only | phase 2 depends on phase 1, and both write `.claude/agents/build/coder.md` |

## Admin actions

None. Infrastructure clearance: N/A (no AWS resource, parameter, secret, permission or
deploy step changes). Nobody needs to be told: ceramics staff and people dropping off see
no change.

## Rollout

Nothing reaches AWS. Merging the pull request deploys the app as every merge does
(stage, its smoke test, prod, its smoke test), but neither phase changes a template, a role, a
resource or the shipped script, so the deployed app behaves as before. The only
exception is a bug the phase 2 tests find in `upload.js`: its fix ships in the same
pull request, and its Verification then includes the by-hand browser check in that phase's
document.

## Related work

- **#52** (merged): added the "Take a photo" button; its description names both
  follow-ups this plan does.
- **#8** (open, "The studio switches from ClickUp"): checks the form on a real iPhone
  before the switch. Phase 2's tests run against a stub and don't replace that check.
- **`drop-off-and-firing`** (the plan that built the form, phase 6): wrote `upload.js`
  and its substring tests; phase 2 keeps those tests and adds behaviour beside them.
- No open pull request touches `upload.js`, `form.html`, `tests/web/` or
  `.claude/agents/`.

## Out of scope

- The submit flow's network path in depth (the upload slots' answers, two uploads at
  once, a failed upload's message, the hidden `slot` inputs): phase 2 tests only the
  list's lock while an upload is pending. More can join the same test file later.
- A real browser in CI (Playwright, jsdom or any npm package): decision 0009.
- Removing the substring asserts in `tests/web/test_form.py`: they stay (CLAUDE.md:
  never weaken a test); some pin things no behavioural test can, such as the absence of
  hard-coded limits in the script.
- Any change to the form's look, its inputs or its accept list.

## Security

- **Personal data:** none. The Node tests use made-up file names (`pot-1.jpg`) and
  sizes, never a real photo, name, email or phone; no image file is committed
  (`tests/repo/test_personal_data.py`). Phase 2 adds `*.js` and `*.mjs` to that scan so
  the script and its tests are checked too.
- **Photo privacy, the public form, the console, email:** unchanged. The tests run the
  script in a sandboxed `node:vm` context with stubbed `fetch`; nothing goes on the
  network.
- **CI:** no workflow changes; the Node tests run inside the existing `python` job,
  without credentials, as every test does. The subprocess runs a fixed command
  (the `node` found on the `PATH`, `--test`, a fixed file) with a minimal environment.
