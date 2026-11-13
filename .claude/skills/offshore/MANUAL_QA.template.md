# Manual QA: <plan title>

Manual acceptance steps for `feat/<run>`, organized by story so each check maps back to
an issue (<#N, #N, …>).

> **Automated coverage** already passed the integration gate: <N> tests passed, coverage
> <NN%> (the floor is in `pyproject.toml`). <Name any check that was skipped, and why,
> instead of giving it a number.> The domain's rules are tested against the in-memory
> fakes. The steps below cover what a person should confirm on a phone and in the
> console before merging.

## Prerequisites

<!-- Derive these from what the stories touch. List only what the steps need. -->

- Where: <locally (how to start the app, for example `uv run <command>` from the phase's
  Verification), stage (`ceramics-stage.asmbly.org`), or prod; and which admin actions
  must be done first, by name>.
- Accounts: <a staff account in the `ceramics` group, and one signed in but outside it,
  to check it's refused; no account for the public form>.
- Data: <records the steps depend on (a kiln, a firing type, a waiting drop-off), and
  how to create them in the console>.
- Made-up details only: a name like "Test Potter", an address at `example.org` (or your
  own inbox, to receive the emails), and test photos you took for the purpose, never a
  member's.
- Devices: a phone (the form is used there) and a desktop browser for the console.

---

## #<N>: <story title> (phases <…>)

1. <One concrete action, naming the real page, field or button> → <expected result>.
2. <Action> → <expected result>.
3. <Action that should be refused, for example a seventh photo or an 11 MB one> →
   <the message the page shows, and that nothing was stored>.

## #<N>: <story title> (phases <…>)

4. <Action> → <expected result>.
5. <Action> → <expected result, for example "the email arrives from the studio's
   address at asmbly.org, with the drop-off's ID in the subject">.

## #<N>: <story title> (phases <…>)

No surface a person can see; automated tests cover it.

---

## Automated re-run (optional)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

<!--
Manual QA rules. Keep them.

- Organize by story, not by phase. Under each story heading, name the phases that
  deliver it (from the Stories table in the plan README).
- Number steps continuously across the whole document, so a reviewer can say "step 14".
- Each step is one concrete action and its expected result. No "check it works". Name
  the real pages, fields, buttons, messages and emails the diff ships; never invent
  behavior the diff doesn't show.
- Cover the refusals as well as the happy path: the form's limits (1 to 6 photos, 10 MB
  each, 10 submissions per device in 10 minutes), a photo's address opened without
  signing in ("access denied"), and a signed-in account outside the `ceramics` group
  ("not allowed").
- The Automated coverage note cites the real numbers from the integration gate. A
  skipped check is named, not numbered.
- Cover every story with a surface a person can see. A purely internal story gets the
  one-line note.
- /offshore writes this document; it doesn't run it. Don't add pass/fail columns that
  imply the steps were run. The maintainer runs them during review.
- This file is public: made-up names, example.org addresses, no real photo, no account
  ID, no internal address.
-->
