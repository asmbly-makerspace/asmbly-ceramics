---
phase_id: 9
title: "Console: loads, settings, counts, the close"
epic: 1
implements: [4, 6, 7]
depends_on: [8]
domain: [web, infra]
estimated_size: L
---

# Phase 9: Console: loads, settings, counts, the close

> **Status:** [ ] Pending

## Required reading

- [CLAUDE.md](../../CLAUDE.md), [the plan's README](README.md) and
  [decision 0002](../../docs/decisions/0002-how-the-app-is-built-and-deployed.md)
  ("Email goes through an outbox", "The scheduled close runs daily, Austin time").
- [Phase 3](phase-3-load-and-studio-use-cases.md): every use case this phase puts a page
  on (`StartLoad`, `AddToLoad`, `RemoveFromLoad`, `StartFiring`, `MarkFired`,
  `ViewLoad`, `ListLoads`, `RetryEmail`, `ViewStudio`, `ChangeEmailSettings`,
  `SendTestEmail`, `AddCatalogItem`, `RetireCatalogItem`, `RestoreCatalogItem`,
  `DeleteCatalogItem`, `CloseFinished`, `WeeklyCounts`) and their errors.
- [Phase 8](phase-8-console-waiting-and-reject.md): `require_staff`, the CSRF and origin
  checks, `ConsoleServices`, the console layout, the drop-off page's email statuses.
- [Phase 7](phase-7-first-deploy.md): `infra/app.yaml`'s mailer, alarm topic and
  `Globals`, and `scripts/smoke.py`.
- Stories #4, #6 and #7, and the design's "Building a load", "The load at the kiln",
  "Settings" and "Weekly counts" screens.
- AWS's documentation:
  - "Schedule types in EventBridge Scheduler"
    (`https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html`): cron
    schedules in a named time zone.
  - "Configuring flexible time windows in EventBridge Scheduler"
    (`.../scheduler/latest/UserGuide/managing-schedule-flexible-time-windows.html`).
  - "RetryPolicy" (`.../scheduler/latest/APIReference/API_RetryPolicy.html`):
    `MaximumRetryAttempts` 0–185, `MaximumEventAgeInSeconds` 60–86400.
  - "Configuring a schedule's dead-letter queue in EventBridge Scheduler"
    (`.../scheduler/latest/UserGuide/configuring-schedule-dlq.html`): an SQS queue.
  - "Creating a scheduled rule (legacy) in Amazon EventBridge"
    (`.../eventbridge/latest/userguide/eb-create-rule-schedule.html`): why not a rule
    (UTC only).
  - "Actions, resources, and condition keys for Amazon Simple Email Service v2"
    (`.../service-authorization/latest/reference/list_sesv2.html`) and "Identity and
    access management in Amazon SES" (`.../ses/latest/dg/control-user-access.html`):
    `ses:SendEmail` on the identity, `ses:FromAddress`.
  - "TransactWriteItems"
    (`.../amazondynamodb/latest/APIReference/API_TransactWriteItems.html`): 100 actions,
    which is why a load holds at most 48 drop-offs.

## Goal

Staff build a kiln load by scanning or typing an ID, by searching, or by tapping Add in
the waiting list; they always see what's in it, take things out while it is loading,
start the firing and mark it fired, which emails each drop-off "Ready for pickup" once;
a failed email is shown by its ID and can be sent again. Staff set the sending address
(refusing one outside `asmbly.org`), send themselves a test email from it, edit the
pickup window and hours and the studio's lists, and see who changed what. Staff see
weekly counts and the overdue drop-offs. Every night the close deletes the personal
details and photos of drop-offs whose pickup window has passed. After this phase #4, #6
and #7 are done.

## Files to create

| Path | What |
| --- | --- |
| `src/asmbly_ceramics/web/console/loads.py` | The load pages and actions |
| `src/asmbly_ceramics/web/console/settings.py` | The settings page and its actions |
| `src/asmbly_ceramics/web/console/counts.py` | Weekly counts |
| `src/asmbly_ceramics/web/templates/console/loads.html` | Open and past loads, and the "Start a load" form |
| `src/asmbly_ceramics/web/templates/console/load.html` | One load: contents, add, waiting list, status, emails |
| `src/asmbly_ceramics/web/templates/console/settings.html` | Emails, the studio's lists, change history |
| `src/asmbly_ceramics/web/templates/console/history.html` | All changes, paged |
| `src/asmbly_ceramics/web/templates/console/counts.html` | Weekly counts |
| `src/asmbly_ceramics/entry/close.py` | `handler(event, context)`: runs `CloseFinished` |
| `tests/web/console/test_loads.py` | |
| `tests/web/console/test_settings.py` | |
| `tests/web/console/test_counts.py` | |
| `tests/entry/test_close.py` | |

## Files to modify

| Path | Change |
| --- | --- |
| `src/asmbly_ceramics/web/console/__init__.py` | Mounts the new routes; the tab row's Loads, Weekly counts and Settings become live |
| `src/asmbly_ceramics/web/console/dropoffs.py` | "Add to a load" opens the load picker (`/console/loads?add=AC-12`) |
| `src/asmbly_ceramics/composition.py` | `ConsoleServices` gains the phase 3 use cases above and a `Mailer` (for the test email only); `build_closer() -> CloseFinished` |
| `infra/app.yaml` | `ses:SendEmail` on the console's role; the close function, its role, log group, schedule, scheduler role, dead-letter queue and two alarms |
| `scripts/smoke.py` | `/console/loads` and `/console/settings` redirect to sign-in without a session (the close isn't public, so it is checked under Rollout instead) |
| `tests/repo/test_app_template.py` | Pins for the new resources |
| `.implementation_plans/drop-off-and-firing/README.md` | Phase 9's status |

## Implementation details

Every route below is behind phase 8's `require_staff`; every POST also passes
`check_csrf` and `check_origin`, then answers `303` to the page it came from with a
one-line message (Post/Redirect/Get), so a refresh repeats nothing. Domain errors are
shown on the page, in the words below, with the typed input kept; nothing is stored. A
`Conflict` from `Records.commit` (someone else changed the load or the drop-off) is shown
as "L-4 changed while you were working. Here it is now; try again." Logs carry
`event`, `drop_off_id`, `load_id`, `user`, `reason` and `error_code` only (phase 2's `LOG_FIELDS`).

### web: loads

| Path | Method | Calls |
| --- | --- | --- |
| `/console/loads` | GET | `ListLoads` |
| `/console/loads` | POST | `StartLoad(kiln, firing_type, date, by)` |
| `/console/loads/{load}` | GET | `ViewLoad`, `WaitingList` (filtered), `FindDropOffs` |
| `/console/loads/{load}/add` | POST | `AddToLoad(load, drop_off, confirm_mismatch, by)` |
| `/console/loads/{load}/remove` | POST | `RemoveFromLoad(load, drop_off, by)` |
| `/console/loads/{load}/edit` | POST | `ChangeLoad(load, kiln, firing_type, date, version, by)`, while loading |
| `/console/loads/{load}/start-firing` | POST | `StartFiring(load, by)` |
| `/console/loads/{load}/fire` | POST | `MarkFired(load, by)` |
| `/console/loads/{load}/emails/{drop_off}/retry` | POST | `RetryEmail(drop_off, "ready", "", staff)` |

`{load}` matches `L-[1-9][0-9]{0,8}`, `{drop_off}` `AC-[1-9][0-9]{0,8}`; anything else
is 404.

- **`GET /console/loads`**: "Start a load" (kiln, firing type and date selects; date
  defaults to today, Austin time; only active kilns and firing types), then open loads
  (loading or firing) and past loads (fired), newest first, each as "Athena · Glaze ·
  Fri Nov 13", its status, drop-offs and pieces. With `?add=AC-12` (from a drop-off's
  page) each open loading load has "Add AC-12 here".
- **`POST /console/loads`**: a retired or unknown kiln or firing type: "Pick a kiln
  from the list." / "Pick a firing type from the list."; a date that isn't a date:
  "Enter a date like 2026-11-13." Success: `303` to the new load (`L-n` from
  `IdNumbers`). Logged `event=load_started`.
- **`GET /console/loads/{load}`**, as the design's "Building a load":
  - the heading "Athena · Glaze · Fri Nov 13", "Load started by <username> at 9:20 AM",
    and while loading "Change kiln, firing or date" (the edit form). The kiln and the
    date can change while the load is loading. The firing type can change only while
    the load is empty: once it has drop-offs the firing-type select is shown read-only
    (`disabled`, with its value sent in a hidden field) and under it "Remove its
    drop-offs to change the firing type." A POST that changes it anyway gets
    `FiringTypeLocked` from `ChangeLoad` and the page shows its message, "Load L-4 has
    drop-offs in it: remove them before changing its firing type.", and changes
    nothing. A retired or unknown kiln or firing type: "Pick a kiln from the list." /
    "Pick a firing type from the list."; a load that is firing or fired: the
    `LoadNotLoading` message. Success: `303` back to the load, logged
    `event=load_changed`;
  - the status steps 1 Loading, 2 Firing, 3 Fired (`aria-current="step"` on the current
    one), and the next action: "Start firing" while loading (disabled with "Add a
    drop-off first" when empty), "Mark fired" while firing;
  - "In this load": a table of ID, name, pieces and a 48 px thumbnail, with totals
    ("12 drop-offs · 41 pieces") and, while loading, "Remove" on each row; empty: "Nothing
    in this load yet. Scan a slip, search, or tap Add in the waiting list.";
  - while loading, "Add by ID or name": one field "Scan a slip, or type an ID or name"
    (`autocomplete=off`, `inputmode=text`, autofocus, so a barcode scanner that types
    and presses Enter works) and Add. An ID (`AC-12`, `ac12`, `12`) is added at once;
    text that isn't an ID is a name search that lists matching waiting drop-offs with Add
    next to each;
  - while loading, "Waiting · glaze": the waiting list filtered to the load's firing
    type, each row with thumbnail, ID, name, pieces and Add; "Show all firing types"
    (`?all=1`) lifts the filter;
  - when fired: "Fired Nov 13 by <username>", the contents without Remove, and the
    emails: "11 of 12 emails sent", then each failed one by ID, "Sending failed
    (code)", and "Try sending again"; pending ones "Waiting to send".
- **Adding** (`POST .../add`, field `drop_off` as typed, optional `confirm=1`):
  - not an ID and not found: "No waiting drop-off matches that. Check the ID, or try
    part of the name.";
  - `NotWaiting`: the domain's reason, e.g. "AC-88 isn't waiting: it was fired in Vulcan
    on Nov 9." or "AC-61 is already in load L-3." or "AC-70 was rejected.";
  - `LoadNotLoading`: "L-4 is firing: nothing can be added or removed.";
  - `LoadFull`: "L-4 holds 48 drop-offs, the most one load can.";
  - `FiringTypeMismatch` (different firing type, no `confirm`): the page again with a
    warning panel "AC-61 is Bisque. This load is Glaze." and two buttons, "Add anyway"
    (the same POST with `confirm=1`) and "Don't add". The page names the two firing
    types from the studio's items, by the error's `.drop_off_firing_type` and
    `.load_firing_type` (phase 1c's hand-off). This is the one domain error whose page
    text isn't its `.message`: that message holds the item IDs (slugs), which are not
    for staff to read;
  - success: "AC-61 added." and the field cleared and focused for the next scan.
    Logged `event=added_to_load`, `drop_off_id`, `load_id`, `user`.
- **Removing**: "AC-61 is back in the waiting list."; refused once firing.
- **Start firing / Mark fired**: each asks no question but is a POST button with a
  plain label; `MarkFired` queues one `ready` email per drop-off in the same
  transaction (phase 3). Marking fired again: "L-4 is already fired. No emails were
  sent again." Logged `event=load_firing` / `event=load_fired` with the load and the
  count.
- **At the kiln**: the page is one column under 40rem, the add field and buttons are
  44 px or more, the contents table drops to ID, name, pieces and thumbnail, and the
  page doesn't depend on hover. It reloads nothing on its own.

### web: settings

| Path | Method | Calls |
| --- | --- | --- |
| `/console/settings` | GET | `ViewStudio` |
| `/console/settings/email` | POST | `ChangeEmailSettings(sending_address, pickup_window_days, pickup_hours_text, by)` |
| `/console/settings/test-email` | POST | `SendTestEmail(sending_address, to=member, by)` |
| `/console/settings/{list}/add` | POST | `AddCatalogItem(list, name, by)` |
| `/console/settings/{list}/retire` | POST | `RetireCatalogItem(list, item, by)` |
| `/console/settings/{list}/restore` | POST | `RestoreCatalogItem(list, item, by)` |
| `/console/settings/{list}/delete` | POST | `DeleteCatalogItem(list, item, by)` |
| `/console/settings/history` | GET | `ViewStudio` (the full history, 50 a page) |

`{list}` is one of `kilns`, `firing-types`, `glaze-types`, `reasons`; anything else is
404.

- **The Emails card**: "Sending address" (`type=email`, at most 254 characters), its
  hint "Every drop-off, fired and rejection email comes from this address. Replies go to
  it too."; "Send a test email to me" (sends from the address in the field, saved or
  not, to the signed-in staff member, and saves nothing; the note under it says "Sends
  to the address on your staff account. Save after it arrives."); "Pickup window" (a
  number, 1 to 90, "days after the pickup email"); "Pickup hours, as shown in emails"
  (a textarea, at most 2,000 characters, shown in emails with line breaks kept and
  everything escaped); "Save email settings".
  - An address not at `asmbly.org`: next to the field, "Use an @asmbly.org address."
    (the domain's `NotAsmblyAddress`; the message names the domain only, never an
    address). A malformed address: "Enter an email address."
  - A window outside 1 to 90: "Enter a number of days from 1 to 90."
  - The test email when the staff member's token has no verified email: "Your staff
    account has no email address to send to. Ask the Facilities Manager." A send that
    SES refuses: "The test email couldn't be sent (code). Nothing was saved." Success:
    "A test email is on its way to you from the new address."
  - Saved: "Email settings saved." Logged `event=settings_changed`, `user`,
    `code=email`; never the address or the text.
- **The studio's lists**: one section per list (Kilns, Firing types, Glaze types,
  Rejection reasons), each item with its use count from `ViewStudio` ("Used by 212
  loads", "Not used yet", "Always available; needs a message" for a reason that needs
  one), a "Retired" tag when retired, and one action: Retire (used and active), Bring
  back (retired), Delete (never used). An "Add" field per list (1 to 60 characters,
  unique within the list ignoring case: "There's already a kiln called Athena."). A
  firing type is added with a "Needs a glaze type" checkbox; a reason with "Needs a
  message". Deleting a used item is refused: "Athena is used by 212 loads. Retire it
  instead." Retiring the last active firing type or kiln is refused: "Keep at least one
  active kiln."
- **Change history**: the last 10 changes, newest first, each as what changed, who
  (username) and when (Austin time), e.g. "Pickup window: 10 → 14 days · sam.r · Nov 12,
  4:18 PM"; "Show all changes" opens `/console/settings/history`. The sending address
  change reads "Sending address changed" with no address in it, so the history page
  holds no address beyond the current one shown in the field.

Every email composed after a change uses the new settings, because the mailer reads the
studio when it sends (phase 3's `SendPendingEmail`).

### web: weekly counts

`GET /console/counts?week=2026-11-09` calls `WeeklyCounts(week_start)`; the week is
Monday to Sunday in Austin time, defaulting to the current week, with previous and next
links. It shows, as the design's "Weekly counts":

- first, the overdue drop-offs (waiting 60 days or more): ID, name, days waiting, each
  linking to its page;
- drop-offs received and pieces, by firing type; loads fired per kiln; rejections by
  reason; drop-offs closed;
- a note: "Closing a drop-off deletes its name, email, phone, rejection message and
  photos. Its ID, dates, firing type, pieces, load and reason are kept for these
  counts."

A week parameter that isn't a Monday date is replaced by the Monday of its week; one that
isn't a date shows the current week.

### app: the close entry point (`entry/close.py`)

```python
def handler(event: Mapping[str, object], context: object) -> dict[str, int]:
    """Run by the daily schedule. Closes every drop-off whose pickup window has passed."""
```

It builds `CloseFinished` once per container (`composition.build_closer()`), calls it
with the clock's now, and returns and logs `event=close_run`, `closed=<n>`,
`skipped=<n>`, `outcome=ok`, plus one `event=closed` line per drop-off with only its ID.
`CloseFinished` (phase 3) is idempotent: a drop-off already closed is skipped, and a
photo already deleted is not an error, so a retried or duplicated run does no harm. A
failure on one drop-off is logged with its ID and the AWS error code and the run goes on;
if any failed, the handler raises at the end so that the schedule's retry runs it again
and, after the retries, the event lands in the dead-letter queue (alarmed). The event's
content is ignored.

`build_closer()` builds `Records`, `PhotoStore` and `Clock` only: the close sends no
email and needs no secret.

### infra: `infra/app.yaml`

The console's role gains the right to send the test email:

```yaml
            - Sid: SendTestEmail
              Effect: Allow
              Action: ses:SendEmail
              Resource: !Sub 'arn:aws:ses:${AWS::Region}:${AWS::AccountId}:identity/asmbly.org'
              Condition:
                StringLike:
                  ses:FromAddress: '*@asmbly.org'
```

It is the same statement as the mailer's (phase 7), on the same identity, agreed in
AsmblyMCPs before phase 7. Recipients can't be limited in IAM (each staff member's own
address); `SendTestEmail` only ever sends to the signed-in member's verified address.

The close function and its schedule:

```yaml
  CloseLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub /aws/lambda/${ProjectSlug}-${AppEnv}-close
      RetentionInDays: !If [IsProd, 90, 14]

  CloseFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub ${ProjectSlug}-${AppEnv}-close
      CodeUri: ../src
      Handler: asmbly_ceramics.entry.close.handler
      MemorySize: 512
      Timeout: 300
      ReservedConcurrentExecutions: 1
      LoggingConfig: {LogGroup: !Ref CloseLogGroup}
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Sid: Records
              Effect: Allow
              Action: [dynamodb:GetItem, dynamodb:Query, dynamodb:UpdateItem, dynamodb:ConditionCheckItem]
              Resource: [!GetAtt RecordsTable.Arn, !Sub '${RecordsTable.Arn}/index/*']
            - Sid: ListKeptPhotos
              Effect: Allow
              Action: s3:ListBucket
              Resource: !GetAtt PhotoBucket.Arn
              Condition:
                StringLike: {s3:prefix: 'dropoffs/*'}
            - Sid: DeleteKeptPhotos
              Effect: Allow
              Action: s3:DeleteObject
              Resource: !Sub '${PhotoBucket.Arn}/dropoffs/*'

  CloseDeadLetterQueue:
    Type: AWS::SQS::Queue
    Properties:
      QueueName: !Sub ${ProjectSlug}-${AppEnv}-close-dlq
      SqsManagedSseEnabled: true
      MessageRetentionPeriod: 1209600

  CloseSchedulerRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub ${ProjectSlug}-${AppEnv}-close-scheduler
      Path: /asmbly-ceramics-app/
      PermissionsBoundary: !ImportValue asmbly-ceramics-function-boundary-arn
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal: {Service: scheduler.amazonaws.com}
            Action: sts:AssumeRole
            Condition:
              StringEquals: {aws:SourceAccount: !Ref AWS::AccountId}
      Policies:
        - PolicyName: invoke-close
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: lambda:InvokeFunction
                Resource: !GetAtt CloseFunction.Arn
              - Effect: Allow
                Action: sqs:SendMessage
                Resource: !GetAtt CloseDeadLetterQueue.Arn

  CloseSchedule:
    Type: AWS::Scheduler::Schedule
    Properties:
      Name: !Sub ${ProjectSlug}-${AppEnv}-close
      Description: Closes finished drop-offs and deletes their personal details (#7)
      ScheduleExpression: cron(17 3 * * ? *)
      ScheduleExpressionTimezone: America/Chicago
      FlexibleTimeWindow: {Mode: 'OFF'}
      State: ENABLED
      Target:
        Arn: !GetAtt CloseFunction.Arn
        RoleArn: !GetAtt CloseSchedulerRole.Arn
        Input: '{}'
        RetryPolicy: {MaximumRetryAttempts: 3, MaximumEventAgeInSeconds: 3600}
        DeadLetterConfig: {Arn: !GetAtt CloseDeadLetterQueue.Arn}

  CloseErrorsAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${ProjectSlug}-${AppEnv}-close-errors
      Namespace: AWS/Lambda
      MetricName: Errors
      Dimensions: [{Name: FunctionName, Value: !Ref CloseFunction}]
      Statistic: Sum
      Period: 3600
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlarmTopic]
      OKActions: [!Ref AlarmTopic]

  CloseDlqAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub ${ProjectSlug}-${AppEnv}-close-dlq
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions: [{Name: QueueName, Value: !GetAtt CloseDeadLetterQueue.QueueName}]
      Statistic: Maximum
      Period: 3600
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlarmTopic]
      OKActions: [!Ref AlarmTopic]
```

The close role's path, boundary and the shared environment come from phase 7's
`Globals`. The scheduler role is a plain IAM role, so it sets its path and boundary
itself; the execution role may create it under `/asmbly-ceramics-app/` with the boundary
(phase 5's `GrantOnlyInsideTheBoundary`). The execution role needs `scheduler:*` on
`schedule/default/asmbly-ceramics-*` and `sqs:*` on `asmbly-ceramics-*` queues, plus
`iam:PassRole` of `role/asmbly-ceramics-app/*` to `scheduler.amazonaws.com`; phase 5
lists them so this phase adds no right to the bootstrap. If phase 5 left them out,
**this phase stops** and the bootstrap is changed first, by its runbook.

The time 03:17 Austin time is outside the hours anyone drops off or fires, and the
minute is off the hour to avoid the busiest scheduling minute. The schedule's
`MaximumEventAgeInSeconds` keeps a retry inside the same night.

### infra: `scripts/smoke.py`

Adds: `GET /console/loads` and `GET /console/settings` without a session answer `302` to
the sign-in. The close function isn't publicly reachable and isn't smoke-tested; the
first night's run is checked under Rollout.

## Tests

`tests/web/console/test_loads.py`:

- `test_start_a_load_with_todays_austin_date_by_default`
- `test_a_retired_kiln_cannot_start_a_load`
- `test_add_by_id` (parametrized: `AC-12`, `ac12`, `12`)
- `test_add_by_name_lists_choices_and_adds_the_chosen_one`
- `test_add_from_the_waiting_list_filtered_to_the_loads_firing_type`
- `test_show_all_firing_types_lifts_the_filter`
- `test_a_drop_off_that_isnt_waiting_is_refused_with_the_reason` (fired, in another
  load, rejected: each message names the IDs and, for fired, the kiln and date)
- `test_a_different_firing_type_asks_for_confirmation_then_adds_on_confirm`
- `test_dont_add_leaves_the_load_unchanged`
- `test_change_kiln_and_date_of_a_load_with_drop_offs_in_it`
- `test_the_firing_type_is_read_only_once_the_load_has_drop_offs`: the select is
  `disabled` with "Remove its drop-offs to change the firing type."; a POST that
  changes it anyway shows "Load L-4 has drop-offs in it: remove them before changing
  its firing type." and leaves the load unchanged; an empty load's firing type changes.
- `test_the_load_page_shows_contents_and_totals`
- `test_remove_puts_it_back_in_the_waiting_list`
- `test_nothing_can_be_added_or_removed_once_firing`
- `test_a_load_holds_at_most_48`
- `test_start_firing_an_empty_load_is_refused`
- `test_mark_fired_queues_one_ready_email_per_drop_off`
- `test_marking_fired_again_sends_nothing`: after the first fire and
  `SendPendingEmail`, a second fire POST leaves the fake mailer's count unchanged.
- `test_a_fired_load_and_its_drop_offs_cannot_be_changed` (edit, add, remove, and
  rejecting one of its drop-offs, all refused)
- `test_a_failed_email_is_shown_by_id_and_retry_clears_it`: the fake mailer fails one
  send; the page shows "11 of 12 emails sent" and that ID; retry, then
  `SendPendingEmail` succeeds; the failure is gone.
- `test_retry_from_the_load_sends_only_to_that_drop_off`
- `test_past_loads_stay_viewable_with_their_contents`
- `test_a_conflicting_change_is_reported_and_nothing_is_stored`
- `test_load_pages_need_the_group_and_posts_need_csrf` (one parametrized test over
  every load route)

`tests/web/console/test_settings.py`:

- `test_an_address_outside_asmbly_org_is_refused_next_to_the_field`: the message is
  shown, nothing is saved, and the message contains no full address.
- `test_a_lookalike_domain_is_refused` (parametrized: a subdomain spoof such as
  `asmbly.org.example.net`, `xasmbly.org`, a trailing dot, uppercase that is fine)
- `test_the_test_email_goes_from_the_unsaved_address_to_the_staff_member_and_saves_nothing`
- `test_the_test_email_without_a_verified_staff_address_says_so`
- `test_a_refused_test_email_shows_the_code_and_saves_nothing`
- `test_saving_records_who_and_when_in_the_history`
- `test_the_history_shows_no_address`
- `test_every_email_after_a_change_uses_the_new_settings`: queue a ready email, change
  the window and the hours and the address, run `SendPendingEmail`; the fake mailer's
  message has the new From, deadline and hours.
- `test_a_used_item_can_be_retired_not_deleted`
- `test_an_unused_item_can_be_deleted`
- `test_a_retired_item_can_be_brought_back`
- `test_a_retired_kiln_is_not_offered_for_a_new_load_but_stays_on_past_loads`
- `test_duplicate_names_are_refused_ignoring_case`
- `test_the_last_active_kiln_cannot_be_retired`
- `test_markup_in_the_pickup_hours_is_escaped_on_the_page_and_in_the_email`
- `test_an_unknown_list_is_404`

`tests/web/console/test_counts.py`:

- `test_counts_by_firing_type_kiln_and_reason_for_one_week`
- `test_the_week_runs_monday_to_sunday_in_austin_time`: a drop-off at 23:30 Sunday
  Austin time (05:30 Monday UTC) counts in that Sunday's week.
- `test_a_week_across_the_daylight_saving_change` (the week of 2 November 2026 and the
  week of 8 March 2027)
- `test_overdue_drop_offs_are_listed_first`
- `test_a_week_that_isnt_a_monday_shows_its_monday`

`tests/entry/test_close.py`:

- `test_the_handler_closes_what_is_due_and_logs_ids_only`
- `test_a_run_with_nothing_to_close_does_nothing_and_succeeds`
- `test_running_twice_is_harmless` (same clock; the second run closes nothing, deletes
  nothing, raises nothing)
- `test_a_failure_on_one_drop_off_does_not_stop_the_others_and_the_run_fails_at_the_end`
- `test_the_event_content_is_ignored`

`tests/repo/test_app_template.py` additions:

- `test_the_close_schedule_runs_daily_in_austin_time_with_a_dead_letter_queue`
- `test_the_scheduler_role_invokes_only_the_close_function`
- `test_the_close_role_deletes_only_kept_photos_and_cannot_read_them`
- `test_ses_send_is_limited_to_the_asmbly_org_identity_and_from_address` (both roles)
- `test_every_new_name_starts_with_the_prefix_and_every_alarm_has_actions`

## Acceptance criteria

1. A load is a kiln (Athena, Helios or Vulcan to start, from the studio's list), a
   firing type and a date, today by default (#4).
2. Staff add a drop-off by typing or scanning an ID, by searching and choosing a result,
   or with Add in the waiting list, which shows the load's firing type by default (#4).
3. A drop-off that isn't waiting or is in a load is refused with the reason; a different
   firing type asks for confirmation (#4).
4. The load's page shows each drop-off's ID, name, pieces and thumbnail with totals, and
   Remove puts one back in the waiting list; it reads on a phone or tablet (#4).
5. A load goes loading, firing, fired; once firing nothing is added or removed (#4).
6. Fired queues one "Ready for pickup" email per drop-off; firing again sends nothing; a
   failed email is shown by its ID (#4).
7. "Try sending again" on the load's page sends only to that drop-off and clears the
   failure once sent (#4; the drop-off page's button is phase 8's).
8. A fired load and its drop-offs can't be changed; past loads stay viewable (#4).
9. An address outside `asmbly.org` is refused with a message (#6).
10. "Send a test email to me" sends from the new address to the signed-in staff member
    before it is saved (#6).
11. Staff edit the pickup window and hours, the kilns, firing types, glaze types and
    rejection reasons; a used item is retired, not deleted (#6).
12. Every change records the username and time, and staff can see the history (#6).
13. Every email after a change uses the new settings (#6).
14. Once a day, at 03:17 Austin time, drop-offs whose pickup window has passed are
    closed: their name, email, phone, rejection message and photos are deleted; ID,
    dates, firing type, pieces, load and reason are kept (#7).
15. A drop-off waiting 60 days or more shows as overdue in the console and is not
    deleted (#7).
16. Staff see weekly counts, Monday to Sunday Austin time: drop-offs and pieces by firing
    type, loads per kiln, rejections by reason (#7).
17. A failed close run alarms the maintainers, through retries and a dead-letter queue.

## Verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest tests/web/console tests/entry -q
uv run pytest --cov
uvx cfn-lint==1.57.1 infra/*.yaml
sam validate --lint -t infra/app.yaml
```

After the merge, on stage, with test drop-offs made with made-up details and a mailbox
the maintainer owns:

1. Start a load in Athena for glaze. Add one drop-off by typing its number, one by name,
   one with Add in the waiting list; try a bisque one (confirmation asked); remove one.
2. Start firing; try to add (refused). Mark fired; the "Ready for pickup" emails arrive,
   with the photos, the pickup date and the hours. Mark fired again: nothing more
   arrives.
3. In Settings, type an address outside `asmbly.org` (refused); send a test email from a
   new `asmbly.org` address to yourself; save; check the history shows your username.
   Retire Helios; it isn't offered for a new load and still shows on a past load.
4. Set stage's pickup window to 1 day. The next morning, the close's log group has a
   `close_run` line with `closed` of at least the fired test drop-offs, and their pages
   say "Closed" with no contact details or photos. Set the window back to 14.
5. Open Weekly counts for this week: the test drop-offs, the load and the rejection are
   counted.

## Rollout

- **What is done:** the merge deploys stage, then prod: the console's new pages, the
  test email right, the close function, its schedule (enabled), its dead-letter queue
  and alarms.
- **Check:** the smoke test on each environment; the stage checks above; on prod, the
  next morning's `close_run` line (with `closed=0` until anything is due) in
  `/aws/lambda/asmbly-ceramics-prod-close`, read with a read-only
  `aws logs filter-log-events` for `close_run`, and no alarm.
- **Who confirms:** the maintainer, and one ceramics staff member who runs the load
  cycle on stage.
- **Undo:** a revert pull request. Its deploy removes the pages, the close function and
  the schedule; nothing is closed after that. Drop-offs closed already stay closed
  (their details are gone by design; backups hold them for 7 days, decision 0002).

## Admin actions

- After the first deploy, confirm the alarm topic's subscribers receive the close
  alarms (the same topic as phase 7; a test with
  `aws cloudwatch set-alarm-state` is a change, so the maintainer runs it only if asked).
- If phase 5's execution role lacks the Scheduler, SQS or `PassRole` rights above, the
  bootstrap is updated by its runbook before this phase merges.

## Hand-off

Filled in when the phase is done. Phase 10 relies on:

- the console complete for #3 to #7 on both environments, at
  `https://ceramics.asmbly.org/console` and `https://ceramics-stage.asmbly.org/console`;
- the close running nightly on both;
- the form's address `https://ceramics.asmbly.org/`, unpublished until the switch.
