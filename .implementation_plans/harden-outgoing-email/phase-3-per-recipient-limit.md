---
phase_id: 3
title: "The form: a limit per recipient address"
depends_on: [2]
domain: [app, web, docs]
estimated_size: M
---

# Phase 3: The form: a limit per recipient address

> **Status:** [~] In progress

Finishes #18.

## Required reading

- [README](README.md): the Domain model and Security.
- [Decision 0008](../../docs/decisions/0008-the-form-caps-received-emails-per-day-and-per-recipient.md):
  "A limit per recipient, under a keyed hash of the normalized address" and "What a
  refused submission says". This phase builds the first; its last section gets this
  phase's evidence.
- Issue #18.
- Phase 2's hand-off: `DropOffNotTaken`, the public route's 429 branch for it,
  `check_received_cap` and the submit's step 4b.
- The pattern: `use_cases/keys.py` (`KeyHasher`: purpose prefixes in the HMAC's input and
  output, `_address_key` normalizing a value before it is hashed, the key read once),
  `domain/limits.py` (`DEVICE_LIMIT`, `ADDRESS_LIMIT`), `use_cases/limits.py`
  (`check_limits`: the device first, the address only if the device is allowed; a log
  line per refusal by `reason`, never a key), `use_cases/submit.py` (`_check_limits`).
- `domain/studio.py`'s `is_valid_email` (what an address that reaches the hash already
  is: one `@`, an ASCII dot-atom local part, a dotted domain) and `domain/dropoff.py`'s
  `DropOffDetails.create` (the address is stripped and checked there).
- `tests/use_cases/test_keys.py` and `tests/use_cases/test_submit.py`'s
  `test_no_raw_cookie_address_or_token_reaches_the_records_or_the_limiter`.
- `tests/domain/builders.py`: `an_address(local, domain)` builds every address a test
  uses; no address is written as a literal.

## Goal

A recipient address gets at most 3 drop-offs in any 24 hours from the form. The 4th is
refused with phase 2's friendly sentence, and nothing is stored. The limiter sees only a
keyed hash of the normalized address, under its own purpose prefix; neither the address
nor its hash is ever logged. The recipient is counted only for a drop-off that would
otherwise be stored, and the daily cap only after the recipient is allowed.

## Files to create

None.

## Files to modify

- `src/asmbly_ceramics/domain/dropoff.py`: `normalized_recipient`.
- `src/asmbly_ceramics/domain/limits.py`: `RECIPIENT_LIMIT`.
- `src/asmbly_ceramics/use_cases/keys.py`: `KeyHasher.recipient`; the module docstring
  names the address among the raw values hashed here.
- `src/asmbly_ceramics/use_cases/limits.py`: `check_recipient`.
- `src/asmbly_ceramics/use_cases/submit.py`: `_check_recipient`, called just before
  `_check_cap`.
- Tests: `tests/domain/test_dropoff.py`, `tests/use_cases/test_keys.py`,
  `tests/use_cases/test_submit.py`, `tests/web/test_submit.py`.
- Docs: `docs/architecture.md` ("What the domain code settles"), `docs/decisions/0008-…`
  (the last section), `CLAUDE.md`'s "Limits from #2" sentence only if the scribe's
  `/write-docs` pass says it should name the new limits (it is a rule summary, not a
  list of every limit).

## Implementation details

### app

**The rule** (`domain/limits.py`), beside the device and address limits:

```python
RECIPIENT_LIMIT = RateLimit(limit=3, window=timedelta(days=1))  # drop-offs per recipient address (#18)
```

A rule like `DEVICE_LIMIT`, not a setting (decision 0008 says why).

**The normalization** (`domain/dropoff.py`), plain Python:

```python
_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def normalized_recipient(address: str) -> str:
    """What the recipient limit counts an address as (decision 0008): stripped and
    lowercased; anything from a `+` in the local part dropped when something comes before
    it; for gmail.com and googlemail.com, the local part's dots dropped and the domain
    read as gmail.com. Only for counting: the drop-off keeps the address as typed.
    `ValueError` for anything `is_valid_email` refuses (a caller's bug: the submit checks
    the address first)."""
```

Steps: `address.strip()`; refuse unless `is_valid_email`; split at the `@`; lowercase
both parts (the local part is ASCII, so `lower()` is exact); `local.split("+", 1)[0]`
when that is non-empty; for a Gmail domain, `local.replace(".", "")` and domain
`gmail.com`; return `f"{local}@{domain}"`.

**The hash** (`use_cases/keys.py`):

```python
RECIPIENT_PREFIX = "recipient#"


def recipient(self, address: str) -> str:
    """The recipient limit's key: an HMAC of `normalized_recipient(address)` under its own
    prefix. Never logged, never stored but by the limiter."""
    return self._hash(RECIPIENT_PREFIX, normalized_recipient(address))
```

Same key (`hash-key`), same HMAC-SHA256, same `prefix + hex` output as the other
purposes, so the same address hashed for another purpose gives an unrelated digest.

**The count** (`use_cases/limits.py`):

```python
def check_recipient(limiter: RateLimiter, *, recipient_key: str, now: datetime, refused_event: str) -> None:
    """Counts one drop-off for the recipient (`RECIPIENT_LIMIT`); `DropOffNotTaken` past it,
    logged as `refused_event` with `reason=recipient_limit` (INFO) and nothing else: never
    the key. `RecordsUnavailable` goes up after a WARNING line (`reason=limiter_unavailable`):
    it fails closed."""
```

**The submit** (`use_cases/submit.py`), at step 4b:

```python
# 4b. The recipient's limit (#18), then the daily cap (#30), only for a drop-off that
# would otherwise be stored. A refused recipient isn't counted against the cap, so one
# address being flooded can't use up the studio's day (decision 0008).
try:
    self._check_recipient(details.contact.email, now)
    self._check_cap(studio, now)
except DropOffNotTaken:
    ...  # phase 2's winner path, unchanged, for either refusal
```

Both checks sit inside phase 2's `try/except DropOffNotTaken`, so a recipient refusal
takes exactly the cap refusal's path: a double tap racing for the recipient's last slot
answers the loser with the winner's drop-off, and otherwise the same error goes up
(prep, 17 November 2026).

`_check_recipient(self, address: str, now: datetime) -> None` hashes with
`self._hasher.recipient(address)` (the key was read for the device hash in step 2, so a
key failure can't first appear here) and calls `check_recipient(..., refused_event=
"drop_off_refused")`. A repeated token returns before step 4b, so a double tap counts
once; the hit is outside the ID loop.

**Ports, adapters, fakes, IAM:** unchanged. The limiter stores the hash as
`RATE#recipient#<64 hex>` under the form role's existing `RATE#*` right, with a TTL a day
after the window. `MemoryRateLimiter.keys_hit` lets tests see the keys counted.

**What is logged:** `drop_off_refused` with `reason=recipient_limit`, or
`reason=limiter_unavailable` and an `error_code`. `use_cases/log.py` would log a 64-hex
digest or an address as `invalid` anyway; the code never passes one.

### web

`POST /drop-off` needs no new branch: `DropOffNotTaken` is phase 2's, answered with 429
and the same sentence. The tests below prove a recipient refusal reads exactly like a cap
refusal and echoes nothing typed.

### docs

- `docs/architecture.md`, "What the domain code settles": "The form counts at most 3
  drop-offs per recipient address in any 24 hours, under a keyed hash of the address
  normalized (case, plus tags, Gmail's dots), and counts the daily cap only when the
  recipient is allowed (decision 0008)."
- Decision 0008's last section: what this phase's tests show, with the date.
- Decision 0008's recipient section gains an accepted consequence: while the cap isn't
  reached, a refusal for an address tells a caller who already knows it that it was
  given three times in the last 24 hours (by anyone, that caller included); learning it
  takes a complete, valid drop-off with photos, which, if taken, emails that address.
  The page can't tell a recipient refusal from a cap refusal. "What a refused submission
  says" is corrected to match.

## Tests

`tests/domain/test_dropoff.py` (addresses from `an_address`):

- `test_normalized_recipient_lowercases_and_strips`.
- `test_normalized_recipient_drops_a_plus_tag`; `..._keeps_a_local_part_that_starts_with_plus`.
- `test_normalized_recipient_folds_gmail_dots_and_googlemail`; `..._keeps_dots_elsewhere`
  (an `example.org` address keeps its dots).
- `test_normalized_recipient_refuses_an_invalid_address` (`ValueError`).

`tests/use_cases/test_keys.py`:

- `test_each_hash_has_its_prefix_and_differs_by_purpose` gains `recipient`.
- `test_the_recipient_hash_is_the_same_for_one_normalized_address` (case and a plus tag
  give one hash; another address another).
- `test_hashes_hold_no_raw_value` gains `recipient` (no part of the address in the hash).

`tests/use_cases/test_submit.py` (each with `caplog`, asserting no record holds the
address, its normalized form, or any `recipient#` hash):

- `test_a_fourth_drop_off_to_one_recipient_in_a_day_is_refused`: three taken (from three
  made-up devices and source addresses, so only the recipient limit can refuse), the
  fourth raises `DropOffNotTaken`; nothing stored for it; one `drop_off_refused` with
  `reason == "recipient_limit"`.
- `test_the_recipient_limit_counts_the_normalized_address`: the address in another case
  and with a plus tag counts as the same recipient.
- `test_the_recipient_limit_is_a_rolling_24_hours`.
- `test_another_recipient_isnt_affected`.
- `test_a_refused_recipient_isnt_counted_against_the_cap`: with a cap of 4 and one
  recipient refused twice, one other recipient is still taken and the next refused by
  the cap (`world.limiter.keys_hit` shows the cap's key only for allowed recipients).
- `test_a_refused_field_or_a_repeated_token_isnt_counted_for_the_recipient`.
- `test_a_double_tap_racing_for_the_recipients_last_slot_returns_the_winner`.
- `test_submit_fails_closed_when_the_recipient_cant_be_counted`: `RecordsUnavailable`,
  nothing stored, a WARNING `limiter_unavailable` line.
- `test_no_raw_cookie_address_or_token_reaches_the_records_or_the_limiter` (existing)
  gains: no key holds the recipient's address or its normalized form, and the recipient's
  key starts with `recipient#`.

`tests/web/test_submit.py`:

- `test_a_fourth_drop_off_to_one_recipient_shows_the_same_friendly_refusal`: 429; the page
  holds exactly `DropOffNotTaken().message`, the same body text a cap refusal shows, none
  of "limit", "cap", "hash", "recipient", and nothing typed.

## Acceptance criteria

1. At most 3 drop-offs per recipient address in any 24 hours; the 4th is refused and
   nothing is stored for it (#18: "a few drop-offs per recipient per day").
2. The limiter counts a keyed hash (HMAC with the form's `hash-key`, prefix
   `recipient#`) of the normalized address, never the address; nothing logs the address
   or the hash (#18: "a limit per keyed hash of the recipient address, stored like the
   other counts").
3. Case, a plus tag and Gmail's dots don't make a new recipient.
4. The refusal shows the same friendly sentence as the cap's, naming no limit, cap or
   hash, and echoing nothing typed.
5. A refused field, a repeated token or a refused recipient never counts against the
   recipient or the cap beyond what decision 0008 says.
6. If the recipient can't be counted, the form answers "try again" and stores nothing.

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`, `uv run mypy` and
      `uv run pytest --cov` pass; the coverage floor holds.
- [ ] `uv run pytest tests/repo` passes (no address literal in the new tests:
      `tests/repo/test_personal_data.py`).
- [ ] `domain/` and `use_cases/` import no AWS library or web framework.
- [ ] No log line, error or page holds an address, its normalized form or a
      `recipient#` hash.

After the merge, on stage: drop off four times to an inbox the tester can read that
phases 1 and 2's checks didn't use (they spend one and two of their inbox's three, so
the first drop-off there would be refused, not the fourth), or to the same inbox 24
hours after those checks, spelled a
different way each time that the limit folds into one (as typed, with a `+` tag if your provider delivers it, in
other letter case), with made-up names and a different device for each (e.g. private
windows); the fourth shows the friendly sentence; the form's log shows
`drop_off_refused` with `reason=recipient_limit` and no address; only three received
emails arrive in that inbox. Never a made-up address here: nothing arrives at one, and
each send would likely bounce on the shared `asmbly.org` sending identity this plan
protects.

## Rollout

Code only, through the merge's deploy: the form function's new version. The table gains
`RATE#recipient#…` items, each expiring by its TTL about two days after its last hit.
Check: the stage steps above. Undo: revert the pull request; the items expire by their
TTL, unread.

## Admin actions

- After the merge: tell ceramics staff that the form takes at most three drop-offs a day
  for one email address, and that someone refused is asked to see staff (take it by hand).
- None in AWS or GitHub.

## Hand-off

Built on branch `feat/harden-outgoing-email` on 17 November 2026; stays `[~] In progress`
until the maintainer confirms the stage check after the merge (a fourth drop-off to an
inbox phases 1 and 2's checks didn't use, or 24 hours after them, spelled four folded ways, refused with the friendly sentence,
`drop_off_refused` with `reason=recipient_limit` and no address in the form's log, three
received emails in that inbox), then
sets it `[x] Complete` here and in the README.

What later work can rely on:

- `domain/dropoff.py`: `normalized_recipient(address)` (`ValueError`, with a fixed
  message, for an address `is_valid_email` refuses). Gmail's domains are the quoted
  `_GMAIL_DOMAINS` (`gmail.com`, `googlemail.com`), matched whole.
  `tests/web/test_submit.py::test_the_domain_raises_only_keys_the_page_knows` reads every
  quoted `word.word` in that module as a message key, less those two domains by name; a
  new quoted `word.word` there that isn't a message key needs the same exception.
- `domain/limits.py`: `RECIPIENT_LIMIT` (3 in 1 day).
- `use_cases/keys.py`: `RECIPIENT_PREFIX = "recipient#"`, `KeyHasher.recipient(address)`.
- `use_cases/limits.py`: `check_recipient(limiter, *, recipient_key, now, refused_event)`,
  logging `reason=recipient_limit` (INFO) or `reason=limiter_unavailable` (WARNING).
- `use_cases/submit.py`: step 4b calls `_check_recipient` then `_check_cap` inside one
  `try/except DropOffNotTaken`, so either refusal takes phase 2's winner path.
- Tests: `tests/domain/builders.py`'s `a_recipient(number)` (`TEST_EMAIL` for 1, then
  addresses that hold `TEST_EMAIL` whole but count as other recipients); the shared
  helpers that make many drop-offs (`tests/use_cases/flows.py`'s `dropped_off`,
  `tests/web/conftest.py`'s `Site.details`, `tests/web/console/conftest.py`'s
  `drop_off`, `tests/use_cases/test_submit.py`'s `from_a_new_device`) give each its own
  recipient; `to_recipient` and `assert_recipient_not_logged` in `test_submit.py`.

Deferred: `CLAUDE.md`'s "Limits from #2" sentence still names only #2's limits; this run
leaves `CLAUDE.md` to the docs step.
