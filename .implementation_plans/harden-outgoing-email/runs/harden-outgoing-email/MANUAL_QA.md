# Manual QA: Harden outgoing email

Manual acceptance steps for `feat/harden-outgoing-email`, organized by story so each check maps back to
an issue (#22, #30, #18; #21 part 2 is part of #22's area).

> **Automated coverage** already passed the integration gate: 3834 tests passed, coverage
> 99.33% (the floor is in `pyproject.toml`). `sam validate --lint` and `sam build` were
> skipped: `sam` is not installed where the gate ran, so CI's `PR check` is their first
> run. The domain's rules are tested against the in-memory fakes. The steps below cover
> what a person should confirm on a phone and in the console before merging.

This change closes #22, #30 and #18 and refers to #21 (only its part 2, a lost claim
response; parts 1 and 3 are not in this change and stay open).

## Prerequisites

- Where: the checks run on **stage** (`ceramics-stage.asmbly.org`) and, for two read-only
  looks, **prod** (`ceramics.asmbly.org`). Nothing here runs locally: `web/local.py` runs
  the public form on in-memory fakes only, with no console and no email. A merge to `main`
  deploys stage, runs its smoke test, then deploys prod and runs its smoke test
  (`.github/workflows/deploy.yml`), so every stage step comes after the merge's deploy has
  reached stage. No admin action is needed before the stage steps. The steps that need one
  say so and name it.
- Accounts: a staff account in the `ceramics` group, and one signed in through the staff
  sign-in but outside it (to check it is refused). No account for the public form. For
  the read-only log and alarm steps, someone with read access to Asmbly's AWS account
  (`AWS_PROFILE=asmbly`, us-east-2).
- Inboxes: two inboxes the tester can read, called inbox A and inbox B below. Use your own,
  never a made-up `example.org` address: nothing arrives there, and each send would likely
  bounce on the shared `asmbly.org` sending identity this change protects. One address can
  make 3 drop-offs a day, so inbox A is spent by the steps for #22 and #30; the steps for
  #18 use inbox B (or inbox A 24 hours later).
- Data: a firing type is needed on the form (the studio's starting data has them); the
  steps create the drop-offs.
- Made-up details only: a name like "Test Potter", a phone number you invent, and test
  photos you took for the purpose, never a member's.
- Devices: a phone (the form is used there) and a desktop browser for the console. The #18
  steps need a different device or browser window (a private window) for each drop-off, so
  the per-device limit (10 in 10 minutes) doesn't get in the way.

---

## #22: Outbox claim whose commit outcome is unknown waits for a manual retry (phase 1; also #21 part 2)

The case itself (a timeout on the mailer's claim that lands anyway) can't be made to
happen by hand; automated tests cover it. These steps check that the normal path still
sends once.

1. On stage, on the phone, open the public form and drop off as "Test Potter" with inbox A,
   one test photo and valid details → the page shows the drop-off's ID (`AC-<number>`).
2. Open inbox A → one "received" email arrives, from the studio's address at `asmbly.org`,
   for that drop-off; wait ten minutes and it is still only one.
3. Read the mailer's CloudWatch log for stage (read only) → it shows `email_sent` for that
   drop-off's ID and no `email_claim_unknown` line.
4. Sign in to the stage console as a `ceramics` staff member and open the emails-needing-attention
   list → that drop-off's email is not on it.

## #30: Cap the received emails the form can queue, per environment (phase 2)

5. On stage, as a `ceramics` staff member, open Settings (`/console/settings`) and find
   the Emails section → a field "Received emails a day, at most" shows 300, with a hint
   that past it the form turns drop-offs away and asks people to see staff.
6. Enter `0`, and then `2001`, and then `abc`, saving each time → each time the field
   shows "Enter a number from 1 to 2,000." and the setting stays 300 (reload to confirm).
7. In the console, count the stage drop-offs made in the last 24 hours, step 1's among them
   (call the number N) → you have N.
8. Enter N + 1 in the field and save → the settings page confirms it, and the settings
   history (`/console/settings/history`) has the line "Received emails a day, at most:
   300 → N + 1" (with your N + 1).
9. On the phone, drop off as "Test Potter" with inbox A → the drop-off is taken, the page
   shows its ID, and the received email arrives in inbox A.
10. Drop off again with inbox A, from a different browser window → the page shows the
    friendly sentence: "Sorry, we can't take this drop-off online right now. Please ask
    ceramics staff at the studio for help." It shows no limit or number. No new drop-off
    appears in the console, and no email arrives in inbox A.
11. Read the stage form's CloudWatch log (read only) → `drop_off_refused` with
    `reason=daily_cap` at WARNING, with no address, name, count or setting value in it;
    and no alarm email arrives from the `logged-errors` alarm.
12. **Admin action: a `ceramics` staff member puts the cap back to 300** (Settings, Emails,
    "Received emails a day, at most", save) → the history shows "N + 1 → 300". Do this
    before the steps for #18, or the cap refuses them.
13. Sign in to stage with the account outside the `ceramics` group and open
    `/console/settings` → "not allowed", no field shown.
14. Run `aws cloudwatch describe-alarms --alarm-names asmbly-ceramics-stage-email-volume
    --profile asmbly --region us-east-2` (read only) → the alarm exists in `OK` or
    `INSUFFICIENT_DATA`, period 3600, threshold 100.
15. On prod (read only; make no drop-off there), a `ceramics` staff member opens Settings
    → the field shows 300, and the same `describe-alarms` command with
    `asmbly-ceramics-prod-email-volume` shows the alarm.

## #18: Public form: consider a rate limit per recipient address (phase 3)

Needs the cap back at 300 (step 12) and inbox B, which steps 1 to 11 didn't use (inbox A
has spent its three: step 1, step 9, and step 10's refused attempt, which still counts
against the address). Alternatively use inbox A 24 hours after those steps.

16. On stage, make four drop-offs as "Test Potter", each in a different private window or
    device, all to inbox B but spelled differently: as typed, with a `+` tag added to the
    local part (if your provider delivers it), in other letter case, and a fourth in any
    of those spellings → the first three show a drop-off ID.
17. The fourth drop-off shows the same friendly sentence as step 10 ("Sorry, we can't
    take this drop-off online right now. …") and no new drop-off appears in the console.
18. Open inbox B → only three received emails arrived, the fourth never.
19. Read the stage form's CloudWatch log (read only) → `drop_off_refused` with
    `reason=recipient_limit`, and no address, hash or count in it.

## Deploy

20. In GitHub Actions, open the merge's **Deploy** run → the stage job and its smoke test
    pass, then the prod job and its smoke test pass.
21. **Admin action after the merge: tell ceramics staff** about "Received emails a day, at
    most" (300; no need to change it), that one email address can make at most three
    drop-offs a day, and that someone the form turns away is asked to see staff: take that
    drop-off by hand and tell the maintainers → staff confirm they were told.

## Trade-offs for the maintainer to decide

[Decision 0008](../../../../docs/decisions/0008-the-form-caps-received-emails-per-day-and-per-recipient.md)
is `proposed`; accepting it is the maintainer's. It records these costs:

- **Refused attempts keep a limit closed.** An attempt the form turns away still counts, so
  a person flooding one address keeps that address closed for 24 hours, and once the
  daily cap is reached, attempts keep the form shut until the count falls or staff raise the
  cap. A refused recipient is not counted against the cap, so one address can't use up the
  studio's day. Is that acceptable?
- **A refusal tells a caller who already knows an address that it was used 3 times.** The
  page's sentence is the same for both refusals and names no limit, but a caller who knows
  an address can tell that it was refused after three drop-offs. Is that acceptable?
- **The form can shut with no alarm if the cap is reached slowly.** The email-volume alarm
  fires only at 100 or more emails in one clock hour; a cap reached over a day (300 by
  default) doesn't trip it, and the refusal is logged at WARNING so it doesn't hold the
  `logged-errors` alarm. Staff learn of it when someone is turned away and tells them. Is
  that acceptable, or should it have its own alarm?

---

## Automated re-run (optional)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```
