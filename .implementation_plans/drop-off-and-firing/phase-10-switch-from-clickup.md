---
phase_id: 10
title: The switch from ClickUp
epic: 1
implements: [8]
depends_on: [9]
domain: [docs]
estimated_size: S
---

# Phase 10: The switch from ClickUp

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md) and [the plan's README](README.md) (Rollout, Admin
  actions, Related work).
- Story #8 and epic #1's **Decided** list: no migration from ClickUp, items already in
  ClickUp are finished there, the QR sign's short address, contact address and wording
  are deferred.
- [Phase 9](phase-9-console-loads-settings-close.md)'s hand-off: the console is complete
  and the close runs nightly.
- The facilities repository's kiln drop-off viewer:
  `functions/ceramics/kiln_dropoff_recent_entries_viewer/` and the files that name it
  (listed in the issue text below).
- [docs/README.md](../../docs/README.md), "Runbooks": how a runbook is listed.

## Goal

People dropping off at the studio reach the new form, from the QR code and from the old
pages, and nobody drops off through ClickUp by mistake. Ceramics staff know the date
beforehand. Drop-offs already in ClickUp are finished there. Nothing is deployed: the app
is already live (phase 7 to 9); this phase writes the runbook for the day, updates the
documents that say where things stand, and the maintainer and staff carry it out.

## Files to create

| Path | What |
| --- | --- |
| `docs/runbooks/switch-from-clickup.md` | The switch: before the day, on the day, after; each step with its check and its undo |

## Files to modify

| Path | Change |
| --- | --- |
| `docs/README.md` | "Runbooks" lists `switch-from-clickup.md` beside phase 5's `aws-bootstrap.md` |
| `README.md` | **Status**: the app is live; the table says which stories are done; **How changes reach production** already says what a merge deploys (phase 7), so it only gains a link to the runbook |
| `docs/architecture.md` | **Today**: the form at `https://ceramics.asmbly.org/`, the console at `/console`, ClickUp retired for drop-offs on the switch date |
| `.implementation_plans/drop-off-and-firing/README.md` | Phase 10's status |

When every phase is on `main`, the plan folder moves to `.implementation_plans/DONE/` in
a separate `chore:` pull request, not in this phase.

## Implementation details

### docs: `docs/runbooks/switch-from-clickup.md`

The runbook has the shape of the others: what it is for, who runs each step, and for each
step what to do, the check that shows it worked, and the undo. It holds no address of a
person and no ClickUp list ID.

**Before the day**

1. **Pick the date** with the ceramics staff lead: a day at least a week ahead, not a
   firing day. The maintainer records it in the epic as a comment.
   - Check: the date is in the epic.
   - Undo: pick another date; tell staff again.
2. **Tell ceramics staff**, at least a week ahead, in their usual channel. The notice:

   > From <date>, drop-offs use the new form at ceramics.asmbly.org, reached from the
   > studio's QR code. Each drop-off gets an ID like AC-12 on screen; people write it on
   > their slip. You'll see what's waiting, build loads, fire them and reject drop-offs
   > in the ceramics console (ceramics.asmbly.org/console, sign in with your staff
   > account). People get an email with their photos when their drop-off is received,
   > fired or rejected. Anything already in ClickUp is finished in ClickUp. Questions:
   > ask <the maintainer's username> in the ceramics staff channel.

   - Check: the notice is posted; each ceramics staff member has signed in to the
     console on stage at least once (the console's log shows their username's
     `signed_in` line; read with a read-only log query).
   - Undo: post a correction.
3. **Try it on stage with staff**: a staff member makes drop-offs with made-up details,
   builds a load, fires it, rejects and undoes one, changes and restores a setting.
   - Check: each step behaves as phases 8 and 9 describe.
   - Undo: none needed; stage's test drop-offs close themselves.
4. **Check the prod form on phones**: on an iPhone and on an Android phone, open
   `https://ceramics.asmbly.org/`, take a photo with the camera and choose one from the
   library, and submit with made-up details and a mailbox the tester owns. Then, in the
   prod console, reject the test drop-off with "Other" and the message "Test, please
   ignore".
   - Check: the ID shows; the received email arrives with the photos and the iPhone
     photo arrived as a JPEG (phase 6's HEIC note; a HEIC refusal here means the
     `accept` list must change before the switch); the rejection email arrives. The test
     drop-offs close on their own after the pickup window.
   - Undo: none needed.
5. **Settings on prod**: the sending address, pickup window (14) and pickup hours
   (epic #1's text) are set in the prod console, and the starting lists match epic #1
   (kilns Athena, Helios, Vulcan; firing types bisque and glaze; glaze types house dip
   and commercial; reasons "Has glaze issues", "Needs more time to dry", "Other").
   - Check: the settings page shows them; the history shows who set them.
   - Undo: change them back in the console.
6. **The facilities issue is merged or ready**: the issue below is open in the
   facilities repository and its pull request is approved, waiting for the day.

**On the day**

7. **Point ClickUp's form at the new form**: in ClickUp (Ceramics, Drop Off Requests,
   the Kiln Drop Off form's settings), set the redirect after submitting to
   `https://ceramics.asmbly.org/`, and add to the form's description "This form has
   moved: use ceramics.asmbly.org".
   - Check: submitting nothing (open the form) shows the notice.
   - Undo: restore the old redirect and description.
8. **Stop the ClickUp form taking submissions**: turn the form off (or make it private)
   in ClickUp. Existing tasks stay where they are.
   - Check: the form's public address no longer accepts a submission.
   - Undo: turn it back on.
9. **Merge the facilities pull request**: the viewer route is removed or replaced by a
   redirect to `https://ceramics.asmbly.org/`, as the issue decides.
   - Check: `https://facilities.asmbly.org/KilnOpsDropoffRecentEntriesViewer` answers as
     the issue says (a redirect, or not found), and the facilities deploy finished.
   - Undo: revert that pull request there.
10. **Replace the QR sign**: the studio's QR code points at `https://ceramics.asmbly.org/`.
    The sign's short address, contact address and wording are deferred in epic #1; the
    maintainer and the ceramics staff lead decide them before the day, and until then the
    QR code's target is the full address.
    - Check: scanning the new sign with a phone opens the form.
    - Undo: put the old sign back.

**After**

11. **A real drop-off through the QR code** arrives in the console's waiting list, and
    its person gets the received email.
12. **Items already in ClickUp** are finished there: staff fire or reject them in ClickUp
    as before, until none is left; nothing is imported (epic #1).
13. **Nothing is retired in AWS.** This repository's stacks stay as they are.

### The issue for the facilities repository

Opened by the maintainer, or by an agent the maintainer asks, in
asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation, titled "Retire
the kiln drop-off viewer once the asmbly-ceramics form is live". Its body, from the
research done for this plan (file paths as of 13 November 2026):

- **Before anything**: the ClickUp form's redirect points at the new form, or the form is
  off (asmbly-ceramics' runbook, steps 7 and 8). Decide whether
  `/KilnOpsDropoffRecentEntriesViewer` answers for a while with a redirect to
  `https://ceramics.asmbly.org/` or is removed.
- **`template.yaml`**: remove the `/KilnOpsDropoffRecentEntriesViewer` path, the
  `CeramicsStack` nested stack and `CeramicsInvokePermission` (or replace them with the
  redirect).
- **Delete** `templates/ceramics.yaml`, `configs/clickup_ceramics_dropOffRequests.json`,
  `functions/ceramics/kiln_dropoff_recent_entries_viewer/` and, if empty,
  `functions/ceramics/`.
- **`.github/dependabot.yml`**: remove the viewer's directory (`tests/test_dependabot.py`
  checks it).
- **Shared tests**: `tests/test_page_csp.py` (the kiln entry in `PUBLIC_PAGES`; decide
  whether a synthetic hash-policy page keeps `HASH_PAGES` non-empty),
  `tests/test_shared_brand.py` (written for two pages), `tests/capture_page_pins.py`,
  and the kiln names in `tests/test_page_style.py` and `layers/common/tests/test_csp.py`.
- **Docstrings and comments** that name the viewer: `layers/common/python/common/brand.py`,
  `layers/common/python/common/csp.py`, `tests/page_style.py`, `tests/page_csp.py`,
  `scripts/list_api_routes.py`, the class photo page's README and one test comment.
- **Docs**: the route table and the "Ceramics" entry in `docs/README.md` (point to
  asmbly-ceramics), and the viewer as the example hash-CSP page in
  `docs/CONTRIBUTING.md`.
- **`template-cicd.yaml`**, after the stacks no longer have them: remove the viewer's
  function, log group and SSM parameter from the deploy policies; an admin redeploys that
  stack as `docs/Deploying.md` says.
- **Risk**: a public page that showed people's names stops serving. The ClickUp redirect
  must already point elsewhere.

The issue names no person and no ClickUp list ID.

### AsmblyMCPs

Nothing in AsmblyMCPs links the ClickUp drop-off flow (its ceramics server works with
shelves and the ceramics mailbox). If the maintainer finds a link there on the day, an
issue there points it at the new form; otherwise nothing.

## Tests

The repository's own checks cover this phase's documents:

- `tests/repo/test_links.py`: every relative link in the runbook, `README.md`,
  `docs/README.md` and `docs/architecture.md` resolves.
- `tests/repo/test_personal_data.py`: no address, phone number or account ID in them.

No new test: nothing here is code.

## Acceptance criteria

1. The studio's QR code opens `https://ceramics.asmbly.org/` (#8).
2. The facilities kiln drop-off page links or redirects to the new form, or is gone with
   the ClickUp redirect pointing at the new form (#8).
3. The ClickUp form stops taking submissions; items already in ClickUp are finished
   there (#8).
4. Ceramics staff are told the switch date at least a week beforehand (#8).
5. `docs/runbooks/switch-from-clickup.md` exists, is listed in `docs/README.md`, and
   gives each step a check and an undo.
6. `README.md` and `docs/architecture.md` say the app is live and where.

## Verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

After the switch: scan the QR sign with a phone and make a real drop-off's way through
(step 11); open the old facilities address (step 9); open the ClickUp form (step 8).

## Rollout

Nothing is deployed from this repository. The runbook's steps are the rollout, run in
order by the maintainer with the ceramics staff lead:

- **Done:** the notice, the stage and phone checks, the prod settings, then on the day
  ClickUp's redirect and form, the facilities pull request and the QR sign.
- **Check:** each step's check; at the end, a real drop-off through the QR code.
- **Who confirms:** the ceramics staff lead, by a real drop-off on the day; the
  maintainer for the facilities page.
- **Undo:** put the old QR sign back, turn the ClickUp form on and restore its redirect,
  revert the facilities pull request. Drop-offs made in the new app stay there and are
  finished there.

## Admin actions

- The maintainer and the ceramics staff lead pick the date and tell staff (steps 1, 2).
- The maintainer opens the facilities issue above and, on the day, merges its pull
  request with that repository's rules.
- Someone with rights to the ClickUp space changes the form's redirect and turns it off
  (steps 7, 8).
- The QR sign's wording and short address are decided and the sign is printed and put up
  (step 10).
- Epic #1's "Work in other repositories" checkbox for the facilities repository is ticked
  once its pull request merges.

## Hand-off

Filled in when the phase is done. After it, the plan is complete: the folder moves to
`.implementation_plans/DONE/` in a `chore:` pull request, and the kiln schedule (#9) gets
its own plan on the model in the README.
