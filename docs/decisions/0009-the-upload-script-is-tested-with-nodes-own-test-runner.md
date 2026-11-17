# 0009: The drop-off form's upload script is tested with Node's own test runner, started by pytest

Status: proposed. It adds to [0002](0002-how-the-app-is-built-and-deployed.md)'s "Pages
are rendered on the server with Starlette and Jinja2" (the only script in the browser is
the form's photo upload, with no build step) and changes nothing it chose. Planned in
[photo-form-follow-ups](../../.implementation_plans/photo-form-follow-ups/README.md).

The drop-off form's script, `src/asmbly_ceramics/web/static/upload.js`, grew with the
"Take a photo" button (pull request #52): two inputs feed one list, the list renumbers
its labels after a removal, a full list disables every way to add a photo, an over-size
photo's message follows it through removals, a status line says what happened beside the
buttons, and the camera button shows only on a touch screen. None of that runs in CI.
`tests/web/test_form.py` asserts substrings of the script's text, which shows a line is
there, not that it does what it should; #52's reviewer noted the gap, and #52 was checked
by hand in a browser with Playwright. The repository has no JavaScript test runner, no
`package.json` and no build step, and 0002 keeps it that way for the app.

## Node's built-in test runner on a hand-written DOM stub, started from pytest

**Chosen:** the script's behaviour is tested by `tests/web/js/upload.test.mjs` with
Node's built-in `node:test` and `node:assert`, running the unchanged `upload.js` in a
`node:vm` context against a small hand-written DOM stub (`tests/web/js/dom.mjs`) that
implements only what the script calls. No npm package, no `package.json`, no lock file,
no `node_modules`, no build step, and nothing new in `pyproject.toml` or `uv.lock`.
`tests/web/test_upload_script.py` renders the real form with the in-memory fakes, hands
its photo field's limits and messages and the script's element IDs to the Node tests as
a JSON file, runs `node --test` on them and fails with Node's output when any fails. So
`uv run pytest --cov`, the command CLAUDE.md and CI already run, runs them: no new
command, no change to "Done means verified", no change to `.github/workflows/`. CI uses
the Node that GitHub's `ubuntu-24.04` runner image already has on its `PATH`.

Node 20 or later is a development requirement from then on, like uv (seen on Node 22
only; 20 is the floor the built-ins need, not a version that has been run). When `node` is not
on the `PATH`, or is older than 20, the test **fails** with a message that says what to
install; it is never skipped, because CLAUDE.md forbids skipping a test and a skipped
check would let a contributor without Node, or a runner image without it, pass without
the script ever running.

**Why:** the smallest footprint that runs the real script's behaviour on every pull
request. The alternatives that lost:

- **A JavaScript engine as a Python development dependency** (`quickjs`,
  `py-mini-racer`, `dukpy`): a native wheel in `uv.lock` and in the dependency audit,
  with no DOM either, so the stub is needed anyway; Node is already on every machine
  that runs CI.
- **jsdom, Playwright or another npm package:** a `package.json`, a lock, `node_modules`
  and an install step in CI, which is the frontend toolchain 0002 avoids. Playwright
  stays a by-hand check in a real browser (as #52 did, and #8's iPhone check).
- **A separate `node --test` step in `pr-checks.yml`:** a second command to keep in step
  with CLAUDE.md's "Done means verified", the README, CONTRIBUTING and the pull request
  template (`tests/repo/test_checks.py` pins them), for no gain over pytest starting it.
- **`actions/setup-node` in CI, pinned by commit:** an exact Node version, at the cost of
  a CI change and another pinned action for Dependabot to bump. Not needed while the
  runner image has Node; it is the remedy if that changes (below).
- **Skipping the test when Node is missing:** forbidden by CLAUDE.md, and it would hide
  exactly the case it should catch.

**Consequence, accepted:** a contributor without Node 20 sees one failing test until
they install it. The tests check the script against a stub, not a browser: layout,
focus as a browser moves it, real file pickers and a phone's camera are still checked by
hand. Coverage measures Python only, so the script's lines are not in the floor.

**Revisit if:** GitHub's `ubuntu-24.04` image drops Node or ships one older than 20
(then add `actions/setup-node`, pinned by commit, with its version in the workflow's
`env`); a Node version on the runner image changes the TAP summary lines
(`# tests`, `# pass`) that `tests/web/test_upload_script.py` counts, which would turn
the required check red with no code change; the stub grows past what the script needs (a sign that a DOM library has become
the cheaper choice); or the console gains scripts of its own.

## What has and has not been seen to work

On 17 November 2026, while planning: Node 22 runs here (`node --version`), `node:test`,
`node:assert` and `node:vm` are Node built-ins, and `upload.js` is a plain script whose
globals (`document`, `window`, `URL`, `fetch`, `FormData`, `HTMLFormElement`) a context
object can supply.

On 17 November 2026, with phase 2 of the plan built: the 14 tests in
`tests/web/js/upload.test.mjs` pass on Node 22.23 here, started by
`tests/web/test_upload_script.py` inside `uv run pytest --cov`, and the same pytest run
with no `node` on the `PATH` fails with the "Node 20 or later" message instead of
skipping. Breaking the script in a scratch copy (no renumbering after a Remove, the
button left enabled on a full list, no size message when a photo is added, the camera
button always shown, a Remove or a pick let through during an upload, among others) made
a test fail each time.

On 17 November 2026, on GitHub's runner: pull request #54's `Python` job ran
`tests/web/test_upload_script.py` inside `uv run pytest --cov` and all six of its tests
passed, so the 14 Node tests ran and passed there, on the Node the runner image already
has. The job log does not print Node's version; it names the image, `ubuntu-24.04`
version 20261111.370.1, whose software list names Node.js 22.23.4.
