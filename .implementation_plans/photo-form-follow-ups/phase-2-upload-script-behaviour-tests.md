# Phase 2: A behavioural test of the upload script

> **Status:** [x] Complete — 2026-11-17 on branch claude/wizardly-bell-u8y238

## Required reading

- [Decision 0009](../../docs/decisions/0009-the-upload-script-is-tested-with-nodes-own-test-runner.md)
  (proposed, written with this plan): what this phase builds and why, and what happens
  when Node is missing (the test fails, never skips).
- [Decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md), "Pages are
  rendered on the server": the script is plain, with no build step and no library. This
  phase changes nothing in the shipped script unless a test finds a bug.
- `src/asmbly_ceramics/web/static/upload.js`, whole. The behaviour under test: `addFiles`,
  `renumber`, `updateControls`, `sizeMessages`/`refreshErrors`, `showErrors` and its
  `data-script` mark, the kept photos' Remove, the `matchMedia("(pointer: coarse)")`
  block, `setBusy` and the submit handler up to its first `fetch`.
- `src/asmbly_ceramics/web/templates/form.html`, lines 27 to 28 (the form and its
  `submission` input) and 51 to 77 (`#photos-field` with its `data-*` attributes, the
  error box, the list, the two inputs, the button, the status line, Submit).
- `src/asmbly_ceramics/web/public.py`, the `photo_messages` entry of the form's context (lines 133 to 139): where the
  messages in the `data-message-*` attributes come from.
- `tests/web/test_form.py` lines 121 to 179: the substring tests this phase keeps and
  adds behaviour beside. `tests/web/conftest.py`: the `site` fixture (the app on the
  in-memory fakes, through Starlette's test client).
- The closest example of a test that starts a fixed subprocess:
  `tests/test_composition.py` line 178 (`# noqa: S603 (a fixed command)`) and
  `tests/mail/test_compose.py` around line 404.
- `tests/repo/test_personal_data.py` (the `TEXT` patterns), `tests/repo/test_checks.py`
  (why no new command is added to CLAUDE.md or CI), `tests/repo/files.py` (`SKIPPED`
  already holds `node_modules`).
- Node's documentation for the built-ins used, for Node 20 and later:
  [`node:test`](https://nodejs.org/docs/latest-v20.x/api/test.html) (`test`,
  `describe`, `it`, `beforeEach`, the `--test` flag and `--test-reporter=tap`),
  [`node:assert/strict`](https://nodejs.org/docs/latest-v20.x/api/assert.html) and
  [`node:vm`](https://nodejs.org/docs/latest-v20.x/api/vm.html) (`createContext`,
  `runInContext`). Use nothing newer than Node 20 has.

## Goal

`uv run pytest --cov` runs the real `upload.js` against a small DOM stub in Node and
fails if the photo list stops behaving as #52 made it: labels renumber after a removal,
a full list disables the picker, the camera and the button, picks past the limit are
refused with the count message, an over-size photo gets its message when it is added and
the message follows it, the status line says what happened, the camera button shows only
on a touch screen, and the list is locked while an upload is pending. Without Node 20 or
later on the `PATH`, that test fails and says what to install. No npm package, no
`package.json`, no build step, no new Python dependency, no workflow change.

## Files to create

- `tests/web/js/dom.mjs` (~130 lines): the hand-written DOM stub and the script runner.
  Node built-ins only.
- `tests/web/js/upload.test.mjs` (~170 lines): the behavioural tests, with `node:test`
  and `node:assert/strict`.
- `tests/web/test_upload_script.py` (~75 lines): finds Node, hands the real form's photo
  field to the Node tests, runs them, and tests its own failure messages.

## Files to modify

- `tests/repo/test_personal_data.py`: add `"*.js"` and `"*.mjs"` to `TEXT`, so the
  script and its tests are scanned for an email address, a phone number and an account
  ID like every other text file (checked while planning: `upload.js` matches none of the
  patterns).
- `README.md`, **Prerequisites**: one bullet: Node.js 20 or later on the `PATH`; `uv run
  pytest` starts Node's built-in test runner for the drop-off form's upload script
  (decision 0009); nothing is installed with npm.
- `.claude/agents/build/coder.md`: after the photo bullet phase 1 rewrote (under **The
  form must work on a phone**), one sentence: the script's behaviour is tested in
  `tests/web/js/upload.test.mjs` on the stub in `tests/web/js/dom.mjs`, started by
  `tests/web/test_upload_script.py` (decision 0009); a change to the photo list's
  behaviour changes those tests, and the stub grows only by what the script calls.
- `docs/decisions/0009-the-upload-script-is-tested-with-nodes-own-test-runner.md`,
  **What has and has not been seen to work**: the date, the Node version the tests ran
  on here, the number of tests, and (after the pull request's CI) that they ran on
  GitHub's runner. The status stays "proposed".
- `.implementation_plans/photo-form-follow-ups/README.md` and this document: the tracker
  and the hand-off.
- `src/asmbly_ceramics/web/static/upload.js`: **only if a test shows a bug**. The fix is
  the smallest change that makes the failing test pass; the test is its regression
  test, written and seen failing first. Keep every assert in `tests/web/test_form.py`
  passing; if a fix changes a line one of them quotes, change the quote to the new line
  with the same meaning, and say so in the pull request.

## Implementation details

### web (tests of the public form's script)

**`tests/web/js/dom.mjs`** exports:

```js
export function makeForm(fixture, options = {}) { /* -> { context, el, calls, document } */ }
export function run(source, context) { /* vm.runInContext(source, context, { filename: "upload.js" }) */ }
export function pick(input, files) { /* sets input.files and input.value, dispatches "change" */ }
export function photo(name, size, type = "image/jpeg") { /* -> { name, size, type } */ }
```

- `fixture` is the JSON `tests/web/test_upload_script.py` writes: `{"field": {<the
  data-* attributes of #photos-field, unescaped>}, "ids": [<every id upload.js reads with
  getElementById, except the optional `error-summary`>], "pieces": {"min", "max"} (the
  pieces input's limits as rendered), "kept": {"item", "label", "remove"} (the classes of
  a kept photo's `li`, `span` and `button`, from a refused submit that keeps one
  upload)}`. `error-summary` is on the page
  only after a refused submit (`form.html` line 15) and the script guards it
  (`if (summary)`), so the stub's `getElementById` answers `null` for it, as a fresh form
  does.
- `options`: `kept` (how many kept photos the server sent back, default 0),
  `serverError` (a server message already in `#photos-error`, default none),
  `coarse` (what `matchMedia("(pointer: coarse)")` answers: `true`, `false`, or
  `undefined` for a browser without `matchMedia`), `fetch` (the stub `fetch`, default
  one that records its calls and never settles).
- The tree mirrors `form.html`: `form#drop-off-form` holding `input[name=submission]`,
  `input#pieces`, `div#photos-field` (with the fixture's attributes), `div#photos-error`
  (with the `serverError` paragraph, unmarked, when given), `ul#photo-list` (with
  `kept` items `li.photo-item.photo-kept` each holding `span.photo-label` and
  `button.remove`, their classes taken from the fixture's `kept`), `input#photos`, `button#take-photo` (hidden),
  `input#photos-camera` (hidden), `p#upload-status` and `button#submit-button`. No
  firing-type radios, no glaze fieldset, no stepper: the script handles their absence,
  and they are outside this phase. `makeForm` throws if a fixture id has no element, so
  the stub can't drift from the script.
- `Element`: `tagName`, `id`, `type`, `name`, `value`, `files`, `hidden`, `disabled`,
  `min`, `max`, `src`, `alt`, `parentNode`, `children`, `className` (a getter and setter
  backed by the same set as `classList`: the script sets `className` on every element it
  creates and finds them again by class), `classList` (`add`, `remove`, `contains`),
  `getAttribute`/`setAttribute`/`hasAttribute`/`removeAttribute`, `textContent` (the
  setter drops the children; the getter joins the text of the subtree), `appendChild`,
  `remove()`, `addEventListener`, `dispatch(type)` (calls the listeners with
  `{ type, target, preventDefault() }`), `click()` (dispatches `click`; counted in
  `calls.clicks` per id), `focus()` (sets `document.activeElement`). `click()` and `dispatch` call the listeners
  even on a disabled element, unlike a browser, so the lock test proves the script's own
  `busy` guard and not only the `disabled` flag,
  `querySelector`/`querySelectorAll` (the subtree, in document order, as an array).
- Selectors: only what the script uses: compound simple selectors (`tag`, `.class`,
  `#id`, `[name="value"]`, `:checked`) and the descendant combinator (`".photo-kept
  .remove"`). Anything else **throws** `unsupported selector`, so a script change that
  needs more fails loudly instead of matching nothing.
- `context` (passed to `vm.createContext`): `document` (`documentElement` with a
  `classList`, `getElementById`, `createElement`, `activeElement`), `window` (with
  `matchMedia` only when `coarse` is not `undefined`, answering `{ matches: coarse }`),
  `URL` (`createObjectURL` returns `blob:1`, `blob:2`, ...; `revokeObjectURL` is
  recorded in `calls.revoked`), `fetch`, `FormData` (records `append`), and
  `HTMLFormElement` (`prototype.submit` recorded in `calls.submitted`).

**`tests/web/js/upload.test.mjs`** reads `process.env.UPLOAD_FORM` (the fixture's path)
and `process.env.UPLOAD_SCRIPT` (the path of `upload.js`) once, and fails at once with
"run me through tests/web/test_upload_script.py" if either is missing. Each test builds a
fresh form, runs the script on it, and acts through the stub (`pick`, `click`,
`dispatch("submit")`). Expected sentences come from the fixture, never typed into the
test: the count message is `field["data-message-count"]`, the size message for photo
`n` is `field["data-message-too-large"].replace("{n}", n)`, the limit is
`field["data-photos-max"]`. Status-line sentences the script writes itself ("Photo 2 of
6 added", built from the limit) are asserted as the script builds them. File names are
made up (`pot-1.jpg`); sizes are numbers, never file contents. The tests are listed under
**Tests**.

**`tests/web/test_upload_script.py`**:

```python
NODE_MIN = 20
NODE_TESTS = 14
JS = Path(__file__).parent / "js"
SCRIPT = Path(asmbly_ceramics.web.__file__).parent / "static" / "upload.js"


def find_node() -> str: ...
def photo_field(page: str) -> dict[str, str]: ...
def pieces_limits(page: str) -> dict[str, str]: ...
def kept_slot(site: Site) -> dict[str, str]: ...
```

- `find_node()`: `shutil.which("node")`; when it is `None`, `pytest.fail` with "Node 20
  or later is needed on the PATH to run the upload script's tests (decision 0009, README
  Prerequisites); this test never skips." Otherwise run `[node, "--version"]` (`check=True`,
  `capture_output`, `text`, a 30 s timeout), parse the major version from `vNN.…`, and
  `pytest.fail` with the same advice and the version found when it is below `NODE_MIN`
  or can't be parsed.
- `photo_field(page)`: the opening tag of the element with `id="photos-field"` and its
  `data-*="…"` attributes, each value through `html.unescape` (Jinja escapes the
  messages' apostrophes and quotes).
- The Node run: `subprocess.run([node, "--test", "--test-reporter=tap", str(JS /
  "upload.test.mjs")], cwd=REPO, env={"PATH": os.environ.get("PATH", ""), "UPLOAD_FORM":
  ..., "UPLOAD_SCRIPT": str(SCRIPT)}, capture_output=True, text=True, timeout=120)`
  with `# noqa: S603 (a fixed command)`. The environment is minimal on purpose: nothing
  else from the caller's environment reaches Node.
- No `skip`, `skipif` or `xfail` anywhere in the file.

Nothing in this phase logs, and nothing the tests print holds a person's details: the
stub's files are made-up names and sizes, and the messages are the form's fixed
sentences.

## Tests

In `tests/web/js/upload.test.mjs` (each one a `test(...)` with this name):

| Test | Proves |
| --- | --- |
| `a library pick adds each photo in order, named by its file` | two files: two `.photo-item`s, labels `pot-1.jpg` and `pot-2.jpg`, Remove labels `Remove photo 1` and `Remove photo 2`, status `Photo 2 of 6 added`, the picker's `value` cleared so the same file can be picked again |
| `a camera shot is called by its place, and the labels renumber after a removal` | library pick, then two camera picks: labels `pot-1.jpg`, `Photo 2`, `Photo 3`; Remove the first: `Photo 1`, `Photo 2`, Remove labels renumbered, status cleared, its object URL revoked |
| `a full list disables both inputs and the button, and a removal enables them` | six photos (across both inputs): `#photos`, `#photos-camera` and `#take-photo` disabled; one Remove: all three enabled |
| `picks past the limit are refused with the count message once` | five photos, then a pick of three: six in the list, one paragraph in `#photos-error` with the count message, and the status line shows it |
| `focus leaves a control that the full list disables` | focus on the picker, fill the list: `document.activeElement` is Submit |
| `an over-size photo gets its message when added, and the message follows it` | a small photo then one over `data-photo-max-bytes`: the size message for photo 2 in `#photos-error` and the status line; Remove the first: the message now says photo 1; Remove the large one: no message left |
| `kept photos count first and the server's own message survives a removal` | two fresh forms. `kept: 2`: Remove labels `Remove kept photo 1 of 2` and `2 of 2`, a pick's Remove label is `Remove photo 3` and the status `Photo 3 of 6 added`. `kept: 2` and a server message: Remove a kept photo before any pick: the server's paragraph is still there, the label says `Remove kept photo 1 of 1` (a pick rewrites the whole error box today, so the survival is checked before one; see the hand-off) |
| `the camera button shows only on a touch screen and opens the camera` | `coarse: true`: `#take-photo` not hidden, its click clicks `#photos-camera` once; `coarse: false` and no `matchMedia`: still hidden |
| `too few photos stop the submit before anything is sent` | submit with none: the count message, `fetch` never called, Submit still enabled |
| `the list is locked while its photos upload` | one photo, submit with a `fetch` that never settles: `fetch` called once with `/drop-off/uploads`, Submit, both inputs, the button and every Remove disabled; a Remove click and a pick change nothing |

In `tests/web/test_upload_script.py`:

| Test | Proves |
| --- | --- |
| `test_every_element_the_script_reads_is_on_the_form` | each id in `getElementById("…")` in `upload.js`, but `error-summary`, is an `id="…"` on the rendered form, so the stub (built from the same list) matches the page; `error-summary` is in `form.html` and the script tests it for `null` before using it |
| `test_the_upload_script_behaves_as_the_form_needs` | writes the fixture from the rendered form, runs Node's tests; passes only when Node exits 0 and the TAP summary's counts are exactly `# tests` and `# pass` `NODE_TESTS` (14) with `# fail`, `# cancelled`, `# skipped` and `# todo` 0 (Node counts skipped and todo tests in `# tests`, so a `test.skip` or an empty test file can't pass); the failure message holds Node's output |
| `test_a_kept_photo_has_the_classes_the_script_selects_on` | a refused submit's kept photo renders `li.photo-item.photo-kept`, `span.photo-label` and `button.remove`, and `upload.js` still selects on them, so the stub's kept markup (built from the same page) matches |
| `test_a_missing_node_fails_and_says_what_to_install` | with `shutil.which` patched to `None`, `find_node()` raises `pytest.fail.Exception` naming Node 20 and decision 0009 |
| `test_an_old_node_fails_and_names_its_version` | with `shutil.which` patched to a made-up path and the version check's `subprocess.run` patched to answer `v18.19.0`, `find_node()` raises naming `v18.19.0` |
| `test_an_unreadable_node_version_fails` | with the version check answering `not a version`, `find_node()` raises naming it |

The existing tests in `tests/web/test_form.py` stay as they are.

## Acceptance criteria

- [x] `uv run pytest tests/web/test_upload_script.py -v` passes here (Node 22), running
      all 14 Node tests, each passing (none skipped or todo).
- [x] Each behaviour the plan's Overview lists (renumbering, the full-list disable, the
      add-time size message, the status line, the camera button's touch-only
      visibility) and the upload lock has a Node test that fails when the script's
      behaviour is broken: checked by hand once by breaking each in a scratch copy
      (for example removing `renumber()` from a Remove, or `takePhoto.disabled` from
      `updateControls`), seeing its test fail, and restoring the script.
      Not committed.
- [x] With a `PATH` that holds no `node` (here, `PATH=/usr/bin:/bin .venv/bin/pytest
      tests/web/test_upload_script.py`: Node is only in `/opt/node22/bin`), the
      behaviour test fails with the "Node 20 or later" message; it is not skipped.
- [x] No `package.json`, lock file, `node_modules`, image file or build step is added;
      `pyproject.toml`, `uv.lock` and `.github/workflows/` are unchanged.
- [x] `tests/repo/test_personal_data.py` scans `*.js` and `*.mjs` and passes.
- [x] The pull request's `Python` job log shows `tests/web/test_upload_script.py`
      passing on GitHub's runner (Node from the runner image): pull request #54,
      runner image `ubuntu-24.04` version 20261111.370.1, whose software list names
      Node.js 22.23.4; all six tests in the file passed.

## Verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

All three CLAUDE.md checks pass with the coverage floor unchanged. In production: nothing
to see; the deployed form is unchanged. If a test found a bug and `upload.js` changed,
also run the form on the fakes (`uv run uvicorn asmbly_ceramics.web.local:app`) in a
phone-sized browser window with touch emulation, add photos from both inputs past six,
remove one, add an over-size one, and see the labels, the disabled controls, the
messages and the status line behave as the tests say; say in the pull request that this
was done.

## Rollout

Nothing reaches AWS. Merging deploys the app as every merge does, with no template, IAM
or workflow change. The shipped script changes only if a test found a bug, and then only
by that fix.

## Admin actions

None. Contributors need Node 20 or later on the `PATH` from this merge on (README
Prerequisites); nobody has to be told separately.

## Hand-off

What later work can rely on:

- `tests/web/js/dom.mjs` exports `makeForm(fixture, options)` (options `kept`,
  `serverError`, `coarse`, `fetch`; returns `{ context, el, calls, document }`, with
  `calls.clicks` by id, `calls.revoked`, `calls.fetched`, `calls.appended`,
  `calls.submitted`), `run(source, context)`, `pick(input, files)` and
  `photo(name, size, type)`. Its selectors are compound `tag`, `.class`, `#id`,
  `[name="value"]`, `:checked` and the descendant combinator; anything else throws. A
  disabled element still gets `click` and `dispatch`, so the tests prove the script's
  `busy` guard.
- `tests/web/js/upload.test.mjs`: 14 `node:test` tests (the plan's ten, plus the limits
  read from the page, a photo of exactly the size limit, an over-size photo stopping the
  submit, and kept photos alone submitting with no upload). A new behaviour in
  `upload.js` adds a test there, and the stub grows only by what the script calls.
- `tests/web/test_upload_script.py`: `find_node()` (fails, never skips, without Node 20+),
  `photo_field(page)`, `OPTIONAL_IDS = {"error-summary"}`,
  `pieces_limits(page)`, `kept_slot(site)`; it runs Node with only `PATH`,
  `UPLOAD_FORM` and `UPLOAD_SCRIPT` in the environment and needs exactly `NODE_TESTS`
  (14) tests, all passing, none skipped, todo or cancelled. Six Python tests.
- `tests/repo/test_personal_data.py` now scans `*.js` and `*.mjs`.
- No bug was found: `upload.js` is unchanged. Each behaviour the Overview lists was
  broken once in a scratch copy and its test failed (19 mutations; the one that first
  survived, size messages numbered without the kept photos, got an assert).
- Noticed, not changed: a new pick rewrites the whole `#photos-error` box, so the
  server's refusal messages from the last submit disappear on the next pick (a kept
  photo's Remove keeps them). That reads as intended (the server's numbering no longer
  holds once the list changes) but no document says so.
- Not covered: the submit flow past its first `fetch` (the README's Out of scope), and
  nothing ties the template's `photo_accept` literal to `FORMATS` in
  `adapters/images.py` (noted in phase 1's review; a template-and-inspector check, not a
  script one).
- Seen: the pull request's `Python` job (#54) ran `tests/web/test_upload_script.py`
  on GitHub's runner and it passed (acceptance criterion 6).
