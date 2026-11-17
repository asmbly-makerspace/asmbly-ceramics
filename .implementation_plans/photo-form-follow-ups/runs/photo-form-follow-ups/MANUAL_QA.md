# Manual QA: Photo form follow-ups

Manual acceptance steps for `claude/wizardly-bell-u8y238`. There are no stories: this is
follow-up work on the drop-off form (#2, from pull request #52) and the pull request says
`Refs #2`, so the steps are organized by the two phases' outcomes.

> **Automated coverage** already passed the integration gate: 3891 tests passed, coverage
> 99.34% (the floor is in `pyproject.toml`). No steps were skipped. The domain's rules are
> tested against the in-memory fakes. This change ships no application behaviour: it adds
> a Node-based test of `upload.js` that `uv run pytest` starts, a wider personal-data scan,
> corrected guidance for the AI agents and a proposed decision (0009). The steps below
> cover what the maintainer should confirm before merging, and the one phone check that
> carries over from pull request #52.

## Prerequisites

- Where: locally, from the repository root, for steps 1 to 9; the pull request's checks on
  GitHub for steps 10 and 11; stage (`ceramics-stage.asmbly.org`) after the merge for
  steps 15 to 19. No admin action in AWS or GitHub is needed first.
- Tools: `uv`, and Node.js 20 or later on the `PATH` (README, Prerequisites). Find where
  Node is with `command -v node`.
- Accounts: none for the form. Steps 1 to 14 need no sign-in.
- Data: none. The tests use made-up file names and sizes. For the phone check (step 15
  on), take a few test photos of your own for the purpose, never a member's, and use a
  made-up name like "Test Potter" and your own inbox for the emails.
- Devices: a desktop with a shell for steps 1 to 14; an iPhone and an Android phone for
  steps 15 to 19.

---

## Phase 2: the upload script has a behavioural test

1. Run `uv run pytest tests/web/test_upload_script.py -v` with Node on the `PATH` → six
   tests pass, including `test_the_upload_script_behaves_as_the_form_needs`, which runs
   the 14 Node tests; none is skipped.
2. Run it again with Node removed from the `PATH`. Work out a `PATH` that has `uv` but no
   `node` (here Node is under `/opt/node22/bin`, so
   `PATH=/usr/bin:/bin .venv/bin/pytest tests/web/test_upload_script.py`; adjust to
   where yours lives) → `test_the_upload_script_behaves_as_the_form_needs` **fails**, with
   a message that says Node 20 or later is needed on the `PATH` and names decision 0009.
   It is not reported as skipped.
3. Check that no test in the file can skip: `grep -nE 'skip|xfail' tests/web/test_upload_script.py`
   → no output.
4. Break the script on purpose, in a copy, not the real file. First keep the page data the
   test builds: `uv run pytest tests/web/test_upload_script.py -k behaves --basetemp=<a new
   empty folder>` → passes, and a `form.json` exists under that folder (find it with
   `find <that folder> -name form.json`).
5. Copy `src/asmbly_ceramics/web/static/upload.js` to a scratch folder and, in the copy,
   delete the `renumber();` call at line 203 (the one in a picked photo's Remove handler,
   after `refreshErrors();`; `grep -n 'renumber()' <copy>` shows the lines). Run
   `UPLOAD_FORM=<form.json from step 4> UPLOAD_SCRIPT=<the copy> node --test tests/web/js/upload.test.mjs`
   from the repository root → at least one test fails (the one about labels renumbering
   after a removal), and the summary shows `# fail` above 0.
6. Repeat step 5 with a different one-line break in a fresh copy: change `takePhoto.disabled = busy || full;`
   (line 112) to `takePhoto.disabled = busy;` → the test about a full list disabling the
   inputs and the button fails.
7. Confirm the real script is untouched: `git status --short src/` and
   `git diff origin/main...HEAD --stat -- src/` → both print nothing.
8. Run `uv run pytest tests/repo -q` → passes. In particular `test_personal_data.py` now
   scans `*.js` and `*.mjs` files as well, so `upload.js` and the new tests are checked
   for an email address, a phone number and an account ID.
9. Check what the branch did not add: `git diff --stat origin/main...HEAD -- package.json pyproject.toml uv.lock .github/ infra/ src/`
   → no output (no npm package, no dependency, no workflow, no template, no application
   file).

## Phase 2: it runs in CI (acceptance criterion 6, still open)

10. Open the pull request's `PR check` run and its `Python` job log → the log shows
    `tests/web/test_upload_script.py` with six tests passing, on GitHub's runner, using
    the Node that comes with the runner image. If the job fails with the "Node 20 or later"
    message instead, the runner image has no Node: that is the case decision 0009's
    "Revisit if" covers (add `actions/setup-node`, pinned by commit), and the merge waits.
11. When step 10 is green, tick the last box under **Acceptance criteria** in
    `.implementation_plans/photo-form-follow-ups/phase-2-upload-script-behaviour-tests.md`
    and replace the "Not yet seen" sentence in decision 0009's **What has and has not been
    seen to work** with the date and the runner result. The status of 0009 does not change
    in this step.

## Decision 0009 (status: proposed)

12. Read `docs/decisions/0009-the-upload-script-is-tested-with-nodes-own-test-runner.md`
    → it says what was chosen (Node's built-in test runner on a hand-written DOM stub,
    started by pytest), the alternatives that lost, what it costs (a contributor needs
    Node 20 or later), and what would reopen it.
13. Decide: accept or reject. To accept, say so in the pull request or the conversation;
    the status line then becomes "accepted by the maintainer (@sababado)" with the date.
    To reject, say what you want instead (a library, a separate CI step, no test); the
    Node tests would then come out of the branch. Until you say, it stays `proposed`.

## Phase 1: the agents' guidance describes the two photo inputs

14. Read `git diff origin/main...HEAD -- .claude/agents/` → each file now says the page has
    two photo inputs (the library picker, `#photos`, and the hidden camera input,
    `#photos-camera`, opened by the touch-only `#take-photo` button), that the accepted
    types are the template's literal (`photo_accept` in `form.html`, decision 0002's list),
    with the server's inspector as the real check, and that the camera is reached with
    `capture`, not `accept="image/*"`. No file says the types come from a domain list.
    Check against `src/asmbly_ceramics/web/templates/form.html` and
    `src/asmbly_ceramics/adapters/images.py`.

## #2 follow-up: the camera button on a phone (carried over from pull request #52)

Do these after the merge, on stage. A merge to `main` runs **Deploy** as every merge does:
`asmbly-ceramics-stage`, its smoke test, then `asmbly-ceramics-prod` and its smoke test.
This branch changes no application file, template, role or workflow, so the deployed app
should behave exactly as before; the check below is the one from #52 that was never done
on real phones, and it tests the form that is already live.

15. On an iPhone, open `https://ceramics-stage.asmbly.org` and scroll to the photos →
    the **Take a photo** button is visible next to the library picker. On a desktop
    browser (a mouse, no touch screen) it is not shown.
16. Tap **Take a photo** on each phone → the camera opens directly, not a menu that asks
    for the library first. Take a shot → it appears in the list as "Photo 1" and the
    status line says "Photo 1 of 6 added".
17. Take or pick photos until there are six, mixing the camera and the library → all six
    are in one list, numbered in order, and nothing is lost between the two inputs.
18. With six in the list → the library picker and **Take a photo** are both disabled; Remove
    one and both come back, with the labels renumbered. Try a seventh through the
    library → refused with the count message, nothing added.
19. Submit a made-up drop-off ("Test Potter", your own inbox) with an iPhone camera photo
    → the confirmation shows an ID (`AC-<number>`), and the received email arrives with
    the photo, and the photo is a JPEG (an iPhone photo is not HEIC when it arrives).
    Repeat steps 15 to 19 on an Android phone.

---

## Automated re-run (optional)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```
