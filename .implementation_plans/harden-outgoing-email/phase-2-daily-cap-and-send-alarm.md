---
phase_id: 2
title: "The form: a daily cap on received emails, and an alarm on the send volume"
depends_on: []
domain: [app, web, infra, docs]
estimated_size: L
---

# Phase 2: The form: a daily cap on received emails, and an alarm on the send volume

> **Status:** [~] In progress

Finishes #30.

## Required reading

- [README](README.md): the Domain model, Parallelism and Rollout.
- [Decision 0008](../../docs/decisions/0008-the-form-caps-received-emails-per-day-and-per-recipient.md):
  its sections on the daily cap, on what a refused submission says, and on the alarm.
  This phase builds them; its "What has and has not been seen to work" gets this phase's
  evidence.
- Issue #30, and [decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md)'s
  "The rate limit is counted in the table".
- The pattern to follow, #2's device limit: `domain/limits.py` (`RateLimit`,
  `DEVICE_LIMIT`), `ports/rate_limit.py` (the rolling window, refused hits counted, fails
  closed), `use_cases/limits.py` (`check_limits`: one log line per refusal by `reason`),
  `use_cases/submit.py` (`_check_limits`), `adapters/memory/rate_limit.py` and
  `adapters/aws/rate_limit.py` (unchanged here), and how `web/public.py`'s `submit`
  answers `TooManySubmissions` (429, the error page).
- A numeric studio setting end to end, the pickup window: `domain/studio.py`
  (`Studio.pickup_window_days`, `change_email_settings`, `_pickup_window`),
  `adapters/aws/keys.py` (the studio's item, and how a studio stored before #42 reads
  with defaults), `use_cases/settings.py` (`ChangeEmailSettings`),
  `web/console/settings.py` (`EmailForm`, `save_email_settings`) and
  `web/templates/console/settings.html` (the Emails card).
- `infra/app.yaml`'s Alarms section (`EmailFailuresFilter`, `EmailFailuresAlarm`) and
  `tests/repo/test_app_template.py` (the alarm set, the tags, the runbook row test).
- `docs/runbooks/operations.md`, "When an alarm fires".
- AWS: [PutMetricAlarm](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_PutMetricAlarm.html)
  (`Period`: 3,600 with one evaluation period is allowed),
  [AWS::Logs::MetricFilter](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-logs-metricfilter.html),
  [AWS::CloudWatch::Alarm](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-cloudwatch-alarm.html).

## Goal

- The studio has a setting, **received emails a day, at most**, starting at **300**,
  which staff change on the console's settings page with a history line, and which a
  studio stored before it reads as 300.
- The submit counts each otherwise-acceptable drop-off against that setting in a rolling
  24 hours; past it, the drop-off is refused with one friendly sentence that says nothing
  about a cap, nothing is stored, no email is queued, and an ERROR line tells the
  maintainers.
- An alarm, `asmbly-ceramics-<env>-email-volume`, goes off when the mailer sends 100 or
  more emails in an hour.

## Files to create

None.

## Files to modify

- `src/asmbly_ceramics/domain/limits.py`: `RECEIVED_EMAILS_PER_DAY_MIN = 1`,
  `RECEIVED_EMAILS_PER_DAY_MAX = 2000`, `RECEIVED_CAP_WINDOW = timedelta(days=1)`.
- `src/asmbly_ceramics/domain/studio.py`: `STARTING_RECEIVED_EMAILS_PER_DAY = 300`,
  `Studio.received_emails_per_day`, `change_email_settings`' fourth value,
  `_received_emails_per_day`.
- `src/asmbly_ceramics/domain/errors.py`: `DropOffNotTaken`.
- `src/asmbly_ceramics/adapters/aws/keys.py`: the studio item's new attribute, and its
  default when absent; the module docstring (the studio paragraph, and the key table's
  `RATE#` row: a keyed hash or the cap's fixed name).
- `src/asmbly_ceramics/ports/rate_limit.py`: the `key` docstring allows a fixed,
  non-personal name.
- `src/asmbly_ceramics/use_cases/limits.py`: `RECEIVED_CAP_KEY`, `check_received_cap`.
- `src/asmbly_ceramics/use_cases/submit.py`: `_check_cap`, called after every field and
  photo passes; the module docstring.
- `src/asmbly_ceramics/use_cases/settings.py`: `ChangeEmailSettings` takes
  `received_emails_per_day`.
- `src/asmbly_ceramics/web/public.py`: `submit` answers `DropOffNotTaken`.
- `src/asmbly_ceramics/web/console/settings.py` and
  `src/asmbly_ceramics/web/templates/console/settings.html`: the field.
- `infra/app.yaml`: `EmailsSentFilter`, `EmailVolumeAlarm`.
- Tests: `tests/domain/test_studio.py`, `tests/domain/test_errors.py`,
  `tests/adapters/aws/test_keys.py`, `tests/use_cases/test_submit.py`,
  `tests/use_cases/test_settings.py`, `tests/web/test_submit.py`,
  `tests/web/console/test_settings.py`, `tests/repo/test_app_template.py`. Every other
  test that calls `change_email_settings` or `ChangeEmailSettings` gains the argument:
  `tests/use_cases/test_flow_logs.py`, `tests/use_cases/test_emails.py`,
  `tests/use_cases/test_close.py`, `tests/adapters/test_memory.py`,
  `tests/adapters/contract/test_records.py`.
- Docs: `docs/runbooks/operations.md` (the alarm's row; the sentence under the table,
  "Each returns to OK by itself when the next five minutes are quiet", now says the
  `email-volume` alarm returns after a quiet hour; the setting in the staff notes if the
  runbook lists settings), `docs/architecture.md` (Today; "What the domain code
  settles"), `docs/decisions/0008-…` ("What has and has not been seen to work").

## Implementation details

### app

**The setting** (`domain/studio.py`):

```python
STARTING_RECEIVED_EMAILS_PER_DAY = 300  # decision 0008


@dataclass(frozen=True, slots=True)
class Studio:
    ...
    clay_bodies: tuple[CatalogItem, ...] = STARTING_CLAY_BODIES
    received_emails_per_day: int = STARTING_RECEIVED_EMAILS_PER_DAY
    version: int = 0
```

`starting_studio` leaves it at the default. `change_email_settings` gains a keyword
`received_emails_per_day: str`, checked by `_received_emails_per_day(text) -> int` in the
shape of `_pickup_window` (strip; length checked before `int()`; a whole number from
`RECEIVED_EMAILS_PER_DAY_MIN` to `RECEIVED_EMAILS_PER_DAY_MAX`; else
`InvalidSetting("received_emails_per_day", "Enter a number from 1 to 2,000.")`). All four
values are checked before anything changes. A changed value records
`SettingChange(at, by, f"Received emails a day, at most: {old} → {new}")`; an unchanged
one records nothing. The docstring says "all four".

**The refusal** (`domain/errors.py`):

```python
class DropOffNotTaken(DomainError):
    """The form can't take this drop-off now (the daily cap, or, from phase 3, the
    recipient's limit). One fixed sentence for every reason: it names no cap, limit,
    count, address or hash (decision 0008)."""

    def __init__(self) -> None:
        super().__init__(
            "Sorry, we can't take this drop-off online right now. "
            "Please ask ceramics staff at the studio for help."
        )
```

**The count** (`use_cases/limits.py`), beside `check_limits`:

```python
RECEIVED_CAP_KEY = "received-emails"
"""The daily cap's one bucket per environment (its table). A fixed name that holds
nothing personal, stored as `RATE#received-emails`; never a hash of anything."""


def check_received_cap(limiter: RateLimiter, *, per_day: int, now: datetime, refused_event: str) -> None:
    """Counts one received email against the studio's daily cap, in a rolling
    `RECEIVED_CAP_WINDOW`; `DropOffNotTaken` past it, logged as `refused_event` with
    `reason=daily_cap` at ERROR, so the logged-errors alarm tells the maintainers.
    `RecordsUnavailable` goes up after a WARNING line (`reason=limiter_unavailable`): the
    cap fails closed."""
```

It calls `limiter.hit(RECEIVED_CAP_KEY, RateLimit(limit=per_day, window=RECEIVED_CAP_WINDOW), now)`.
A cap lowered below the number of stored hits refuses at once; one raised counts the
hits kept (the item keeps at most the old limit's hits, which is fewer, so it allows
more, never fewer than it should). `ports/rate_limit.py`'s docstring: "`key` must be a
keyed hash (phase 2's `KeyHasher`), or a fixed name that holds nothing personal (the
daily cap's `received-emails`), never a raw address or cookie value".

**The submit** (`use_cases/submit.py`): after step 4 (every field and photo passed, the
`_PHOTO_MISSING` winner path already returned), before the firing type's name is read and
before any ID is taken:

```python
# 4b. The daily cap on received emails (#30, decision 0008), only for a drop-off that
# would otherwise be stored, so a refused field never counts.
self._check_cap(studio, now)
```

`_check_cap(self, studio: Studio, now: datetime) -> None` calls
`check_received_cap(self._limiter, per_day=studio.received_emails_per_day, now=now,
refused_event="drop_off_refused")`. The setting is read from the studio this request
already read (settings as data, read when used). A repeated token returns before it, so
a double tap whose second request comes after the first is stored counts once; one whose
two requests race both pass that check and both count (decision 0008 accepts it), and
when the cap refuses the loser, the submit reads the token's submission again and
answers with the winner's drop-off if it is stored (found in phase 2's review). The hit is outside the ID loop, so a commit's retry with the
next ID doesn't count twice. Nothing is kept, stored or queued when it refuses. The
constructor and `composition.py` don't change: the submit already has the limiter and
the studio.

**The settings use case** (`use_cases/settings.py`): `ChangeEmailSettings.__call__` takes
`received_emails_per_day: str` and passes it on. Its docstring lists the same errors.

**The store** (`adapters/aws/keys.py`): the studio item writes
`"received_emails_per_day": entity.received_emails_per_day`; the reader takes
`values.get("received_emails_per_day", STARTING_RECEIVED_EMAILS_PER_DAY)`. The docstring's
studio paragraph: "A studio stored before #30 has no `received_emails_per_day` and reads
300." The in-memory records store the `Studio` value as it is, so the fake needs nothing.
The form role reads `STUDIO` and the console role writes it already: no IAM change.

**What is logged:** `drop_off_refused` with `reason=daily_cap` (ERROR) or
`reason=limiter_unavailable` (WARNING, `error_code`), and `settings_changed` with the
username, as today. No count and no setting's value in a log line.

### web

**`POST /drop-off`** (public, `web/public.py`, `submit`): one more branch, beside
`TooManySubmissions`:

```python
except DropOffNotTaken as refused:
    _page_log("not_taken")
    return error_response(request, 429, refused.message)
```

The error page shows only that sentence (autoescaped, fixed text) and the page's link
back, as the device limit's does. Nothing of what was typed is echoed. The same-origin
check, the body limit and the form's own checks run first, unchanged. On a phone it is
the same error page as the device limit's.

**`GET /console/settings` and `POST /console/settings/email`** (the `ceramics` group,
CSRF checked, as today): `EmailForm` gains `received_emails_per_day: str = ""`;
`_email_form`, `_typed` and `_with_error` carry it; `save_email_settings` passes it; an
`InvalidSetting` on it shows next to the field with what was typed kept, and nothing is
saved (status 400). The Emails card's first column gains, after the pickup window:

```html
<div class="field{% if email.error_field == 'received_emails_per_day' %} field-invalid{% endif %}">
  <label for="received_emails_per_day">Received emails a day, at most</label>
  <p class="hint" id="cap-hint">The most "We received your drop-off" emails the form sends in any 24 hours. Past it, the form turns drop-offs away and asks people to see staff. A normal week has about 80 drop-offs.</p>
  {% if email.error_field == "received_emails_per_day" %}<p class="field-error" id="cap-error">{{ email.error }}</p>{% endif %}
  <input type="number" id="received_emails_per_day" name="received_emails_per_day" value="{{ email.received_emails_per_day }}" min="{{ cap_min }}" max="{{ cap_max }}" inputmode="numeric" class="input-narrow" aria-describedby="cap-hint{% if email.error_field == 'received_emails_per_day' %} cap-error{% endif %}">
</div>
```

`cap_min` and `cap_max` come from `domain/limits.py`, as `window_min` and `window_max`
do. The console is staff only, so its wording may name the cap; the public form's never
does.

### infra

In `infra/app.yaml`'s Alarms section, after `EmailFailuresFilter` and after
`EmailFailuresAlarm`:

```yaml
  # Every email the mailer sent (decision 0008): a full load sends up to 48 ready emails at
  # once, so 100 in an hour is out of the ordinary whatever its kind.
  EmailsSentFilter:
    Type: AWS::Logs::MetricFilter
    Properties:
      LogGroupName: !Ref MailerLogGroup
      FilterPattern: '{ ($.event = "email_sent") || (($.event = "email_unrecorded") && ($.outcome = "sent")) }'
      MetricTransformations:
        - MetricName: EmailsSent
          MetricNamespace: !Sub '${ProjectSlug}/${AppEnv}'
          MetricValue: '1'
          Unit: Count

  EmailVolumeAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub '${ProjectSlug}-${AppEnv}-email-volume'
      AlarmDescription: The mailer sent 100 or more emails in an hour; see email_sent in its log and drop_off_submitted in the form's.
      Namespace: !Sub '${ProjectSlug}/${AppEnv}'
      MetricName: EmailsSent
      Statistic: Sum
      Period: 3600
      EvaluationPeriods: 1
      Threshold: 100
      ComparisonOperator: GreaterThanOrEqualToThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlarmTopic]
      OKActions: [!Ref AlarmTopic]
      Tags:
        - {Key: Project, Value: !Ref ProjectSlug}
        - {Key: Component, Value: App}
        - {Key: Environment, Value: !Ref AppEnv}
        - {Key: Owner, Value: it-volunteers}
        - {Key: ManagedBy, Value: sam}
```

A metric filter takes no tags (as the existing filters). The alarm's name starts with
`asmbly-ceramics-<env>-`, from `ProjectSlug`; the bootstrap's execution role already
grants `logs:PutMetricFilter` and `cloudwatch:PutMetricAlarm`/`TagResource` on
`asmbly-ceramics-*` alarms (the seven existing alarms deploy with them): no bootstrap or
IAM change. The test email (#6) goes from the console, not the mailer, so it isn't
counted. The cap's own refusals reach the maintainers through the existing
`FormLoggedErrorsFilter` (ERROR lines), so no second alarm.

### docs

- `docs/runbooks/operations.md`, "When an alarm fires": a row for `email-volume`: look at
  the mailer's log group for `email_sent` (by drop-off ID and `kind`) and the form's for
  `drop_off_submitted` and `drop_off_refused`; ready emails after a fired load are
  normal; a flood of received emails means the form is being abused: staff can lower
  "Received emails a day, at most" in Settings, and the maintainers read the form's log
  for `reason=daily_cap`.
- `docs/architecture.md`: Today mentions the daily cap; "What the domain code settles"
  gains: "The form counts each otherwise-acceptable drop-off against the studio's daily
  cap on received emails (a setting, 300 to start) in a rolling 24 hours, and refuses
  past it with one sentence that names no cap (decision 0008)."
- Decision 0008's last section: what this phase's tests show, with the date.

## Tests

`tests/domain/test_studio.py`:

- `test_a_new_studio_caps_received_emails_at_300`.
- `test_change_email_settings_records_the_cap_change`: 300 → 120 records "Received emails a
  day, at most: 300 → 120" and nothing for the unchanged values.
- `test_received_emails_per_day_outside_1_to_2000_refused` (parametrized `"0"`, `"2001"`,
  `"-5"`, `"1.5"`, `""`, `"12abc"`, 5,000 digits): `InvalidSetting` on
  `received_emails_per_day`, studio unchanged.
- The existing `change_email_settings` tests pass the new argument.

`tests/domain/test_errors.py`:

- `test_drop_off_not_taken_names_no_cap_limit_or_hash`: the message holds none of "cap",
  "limit", "hash", "per day", "300", "too many", and no digit.

`tests/adapters/aws/test_keys.py`:

- `test_studio_round_trips_the_received_emails_cap`.
- `test_old_studio_item_reads_a_cap_of_300` (an item without the attribute).

`tests/use_cases/test_submit.py` (each test with `caplog`, asserting no log record holds
`TEST_EMAIL`):

- `test_a_drop_off_past_the_daily_cap_is_refused_and_nothing_is_stored`: with the studio's
  cap set to 2, two submits succeed, the third raises `DropOffNotTaken`; no third
  drop-off, email, submission or kept photos; the uploads are left; one
  `drop_off_refused` with `reason == "daily_cap"` at ERROR.
- `test_the_cap_is_a_rolling_24_hours`: the third, 24 hours and a microsecond after the
  first, is taken.
- `test_a_refused_field_isnt_counted_against_the_cap`: a submit refused for a field, then
  two good ones with a cap of 2, both taken (`world.limiter.keys_hit` shows the cap's key
  twice).
- `test_a_repeated_token_isnt_counted_against_the_cap`.
- `test_the_cap_is_read_from_the_studio_when_used`: raising the setting between two
  submits lets the next one through.
- `test_submit_fails_closed_when_the_cap_cant_be_counted`: a limiter that fails only for
  `RECEIVED_CAP_KEY` raises `RecordsUnavailable`, nothing stored, a WARNING
  `limiter_unavailable` line.
- `test_the_cap_is_counted_under_its_fixed_key`: the cap's key is exactly
  `RECEIVED_CAP_KEY`.
- The existing `test_no_raw_cookie_address_or_token_reaches_the_records_or_the_limiter`
  asserts every key starts with `device#` or `address#`; after this phase the cap's key
  is hit too, so its assertion becomes "starts with `device#` or `address#`, or is
  `RECEIVED_CAP_KEY`", and it still asserts no raw token, cookie or address in any key
  (found by `/prep`: unchanged, it fails).

`tests/use_cases/test_settings.py`:

- `test_the_received_emails_cap_is_saved_with_its_history`.
- The existing email-settings tests pass the new argument.

`tests/web/test_submit.py`:

- `test_a_drop_off_past_the_daily_cap_shows_the_friendly_refusal`: 429; the page holds
  `DropOffNotTaken().message`, none of "cap", "limit", "hash", and none of what was typed
  (the made-up name and address); no drop-off stored.

`tests/web/console/test_settings.py`:

- `test_the_emails_card_shows_the_received_emails_cap`.
- `test_saving_the_cap_records_it_in_the_history`.
- `test_a_cap_outside_1_to_2000_is_refused_next_to_the_field`: 400, the typed value kept,
  nothing saved.
- `test_a_signed_in_person_outside_the_group_can_t_change_the_cap` (the existing "not
  allowed" check, for this POST with the new field), and a POST without the CSRF token is
  refused.

`tests/repo/test_app_template.py`:

- `test_every_alarm_notifies_this_project_s_topic_and_ignores_missing_data`: the set gains
  `EmailVolumeAlarm` (the runbook-row and tags tests then cover it).
- `test_the_email_volume_alarm_counts_the_mailer_s_sent_emails_per_hour`: the filter is on
  `MailerLogGroup` with pattern `{ ($.event = "email_sent") || (($.event = "email_unrecorded") && ($.outcome = "sent")) }` (an email that went but whose sent mark failed
  logs `email_unrecorded` with `outcome=sent`; found in phase 2's review) into `EmailsSent`; the alarm
  sums it over 3,600 seconds, one period, threshold 100, `GreaterThanOrEqualToThreshold`.

## Acceptance criteria

1. A studio has `received_emails_per_day`, 300 to start and 300 when stored before it;
   staff change it from 1 to 2,000 in Settings › Emails, and the history records the old
   and new numbers with the username (#30: "where it lives"; settings as data).
2. A drop-off that would push the received emails queued in the last 24 hours past the
   setting is refused: nothing stored, no photo kept, no email queued (#30: "a daily
   count of queued received emails that the submit checks").
3. The refusal shows "Sorry, we can't take this drop-off online right now. Please ask
   ceramics staff at the studio for help." and nothing about a cap, a limit or a hash
   (#30: "what the form says").
4. A refused field, a repeated token and a commit's retry with the next ID never count
   against the cap.
5. If the cap can't be counted, the form answers "try again" and stores nothing.
6. The maintainers are told: `drop_off_refused reason=daily_cap` at ERROR (the
   logged-errors alarm), and `asmbly-ceramics-<env>-email-volume` at 100 emails sent in an
   hour (#30: "a CloudWatch alarm on the mailer's send volume").
7. The alarm carries the five tags and notifies the alarm topic; the runbook has its row.

## Verification

- [ ] `uv run ruff check . && uv run ruff format --check .`, `uv run mypy` and
      `uv run pytest --cov` pass; the coverage floor holds.
- [ ] `uvx cfn-lint==1.57.1 infra/*.yaml` passes.
- [ ] `sam validate --lint -t infra/app.yaml && sam build -t infra/app.yaml` pass (where
      `sam` is installed; say so if it isn't).
- [ ] `uv run pytest tests/repo` passes: the alarm's tags, topic and runbook row; no
      account ID, address or secret in the template.
- [ ] `domain/` and `use_cases/` import no AWS library or web framework.
- [ ] The public refusal's page and every log line hold no name, address, phone, hash or
      count; the console's field is autoescaped and its `min`/`max` match the domain's.

After the merge, on stage:

- Settings › Emails shows "Received emails a day, at most: 300". Set it to 1 and save;
  the history shows "300 → 1". Drop off once to the tester's own inbox, with a made-up
  name (taken; the received email arrives there), then again to the same inbox: the
  second shows the friendly sentence. The form's log
  shows `drop_off_refused` with `reason=daily_cap`, and the `logged-errors` alarm goes off
  (its email says stage). Set it back to 300.
- `aws cloudwatch describe-alarms --alarm-names asmbly-ceramics-stage-email-volume
  --profile asmbly --region us-east-2` (read only) shows the alarm in `OK` or
  `INSUFFICIENT_DATA`, period 3600, threshold 100.

## Rollout

Reaches AWS through the merge's deploy (stage, its smoke test, prod, its smoke test):

- **The studio item** gains `received_emails_per_day` on its next save; until then it
  reads 300. **The table** gains one `RATE#received-emails` item per environment on its
  first drop-off, with a TTL a day after its window.
- **CloudFormation** creates `EmailsSentFilter` and `EmailVolumeAlarm` in each stack.
- **Check:** both smoke tests pass; the stage steps above (the maintainer confirms the
  alarm email arrived and the setting is back at 300).
- **Undo:** revert the pull request. CloudFormation deletes the filter and the alarm.
  The `RATE#received-emails` item expires by its TTL. Reverted code ignores the studio's
  new attribute, and its first settings save drops it; the setting then reads 300 again
  when this is re-applied.

The phase's tracker row stays `[~] In progress` until the stage check is confirmed.

## Admin actions

- After the merge: tell ceramics staff that Settings › Emails has "Received emails a day,
  at most" (300), that they need not change it, and what the form says if it is reached
  (the person is asked to see staff; take the drop-off by hand and tell the maintainers).
- None in AWS or GitHub: the alarm uses the existing topic and its confirmed
  subscription; no new parameter, secret or right. Infrastructure clearance: one metric
  filter and one alarm, named from `ProjectSlug`, tagged, under the bootstrap's existing
  rights.

## Hand-off

Built on branch `feat/harden-outgoing-email` on 17 November 2026; stays `[~] In progress`
until the maintainer confirms the stage check after the merge (the cap set to 1 refuses
the second drop-off with the friendly sentence, the `logged-errors` alarm email arrives,
the cap set back to 300, and `describe-alarms` shows
`asmbly-ceramics-stage-email-volume`), then sets it `[x] Complete` here and in the README.

Phase 3 can rely on:

- `domain/errors.py`'s `DropOffNotTaken()` (no arguments; its one fixed sentence), and
  `web/public.py`'s `submit` answering it with 429 and that sentence (page log outcome
  `not_taken`).
- `use_cases/limits.py`: `RECEIVED_CAP_KEY = "received-emails"` and
  `check_received_cap(limiter, *, per_day, now, refused_event)`, which logs
  `refused_event` with `reason=daily_cap` at ERROR or `reason=limiter_unavailable` at
  WARNING (`error_code`), and raises `DropOffNotTaken` or `RecordsUnavailable`.
- `use_cases/submit.py`: step 4b, `self._check_cap(studio, now)`, after every field and
  photo passes and the `_PHOTO_MISSING` winner path, before the firing type's name is
  read and outside the ID loop; phase 3 puts its recipient check just before it.
- `domain/limits.py`: `RECEIVED_EMAILS_PER_DAY_MIN`, `RECEIVED_EMAILS_PER_DAY_MAX`,
  `RECEIVED_CAP_WINDOW`; `domain/studio.py`: `STARTING_RECEIVED_EMAILS_PER_DAY`,
  `Studio.received_emails_per_day`, and `change_email_settings(...,
  received_emails_per_day=...)` (a required keyword, also on `ChangeEmailSettings`).
- `ports/rate_limit.py`'s docstring allows a fixed, non-personal key.
- `tests/use_cases/test_submit.py`: `set_cap(world, n)`, `from_a_new_device(world, n)`
  (a request no device or address limit refuses) and `assert_no_personal_details_logged`;
  `test_no_raw_cookie_address_or_token_reaches_the_records_or_the_limiter` allows
  `device#`, `address#` and `RECEIVED_CAP_KEY` keys (phase 3 adds `recipient#`).
- `infra/app.yaml`: `EmailsSentFilter` and `EmailVolumeAlarm`.

Deferred: nothing. `sam validate` and `sam build` were not run (no `sam` where this was
built); `cfn-lint` 1.57.1 passes.
