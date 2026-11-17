# 0008: The form caps the received emails it queues, per environment and per recipient, and an alarm watches the mailer's send volume

Status: proposed. It adds to [0002](0002-how-the-app-is-built-and-deployed.md)'s "The
rate limit is counted in the table" and to its accepted consequence that anyone can make
a drop-off giving any email address. Planned in
[harden-outgoing-email](../../.implementation_plans/harden-outgoing-email/README.md).

The public form has no sign-in (#2), and each drop-off queues one "We received your
drop-off" email from the studio's `asmbly.org` address to whatever address was typed.
Its limits were per device (10 in 10 minutes) and per source address (30 in 10 minutes).
Someone rotating devices, networks and addresses could still make the form email a
third party many times, or email many addresses, from the `asmbly.org` sending identity,
which AsmblyMCPs owns and other projects share: complaints would land on that identity.
Stage and the prod form are both reachable before the switch (their names are in
Certificate Transparency logs). #18 (found preparing phase 2b of drop-off-and-firing)
asked for a limit per recipient; #30 (found preparing phase 7) asked for a ceiling for
the whole environment and an alarm on the mailer's send volume, and left open the
ceiling's value, where it lives and what the form says. The maintainer's run on
17 November 2026 set the defaults: 300 received emails per environment per day, and 3
drop-offs per recipient per day.

## A daily cap on received emails, kept as a studio setting

**Chosen:** the studio gains a setting, `Studio.received_emails_per_day`, starting at
**300**, that staff change in the console (Settings › Emails, "Received emails a day, at
most", a whole number from 1 to 2,000; the history records the old and new numbers).
A studio stored before it reads as 300. The submit counts one hit in the existing
`RateLimiter` under one fixed, non-personal key (`received-emails`, stored as
`RATE#received-emails`) with a rolling window of 24 hours and the setting's value as its
limit, once every field and photo has passed and just before the drop-off gets its ID.
Past the cap the drop-off is refused with the generic message below, nothing is stored,
and the form function logs `drop_off_refused` with `reason=daily_cap` at ERROR, so the
existing `logged-errors` alarm tells the maintainers. Like the other limits it fails
closed: if the count can't be read or written, the form answers "try again" and stores
nothing.

**Why:** a setting, because `CLAUDE.md` keeps what staff may need to change as data, and
the right ceiling depends on the studio's busiest days (about 80 drop-offs a week today,
so 300 in a day is far above any real day, yet low enough that a flood stops within a
day). The rolling window and the fixed key reuse the limiter that #2's limits already
use, with its tests, its fail-closed contract and the form role's existing `RATE#*`
right, so no new item type, port or IAM right is needed. The alternatives that lost: a
counter item updated inside the submit's transaction with a condition (exact, but it
changes the `Records` port, its fake, its adapter and the form role's rights, and a
conflict on that one hot item would cost a drop-off ID per retry); a constant in
`domain/limits.py` with this record (staff couldn't raise it on a class day without a
deploy); a calendar day (a flood just before midnight would get two caps in an hour).

**Consequence, accepted:** a hit is counted before the commit, so a submit whose commit
then fails still counts. Refused hits count too, as for every limit here, so a flood
keeps the form closed until 24 hours after it stops; staff can raise the setting to
reopen it. While the cap is reached, every drop-off from the form is refused, real ones
included, and people are told to ask ceramics staff. The ERROR line repeats for each
refusal; the alarm notifies on its change of state only.

**Consequence, accepted:** because refused hits count, someone sending about one valid
submission every 86,400 ÷ cap seconds (every 288 seconds at 300) from rotating devices
and addresses keeps the form shut for as long as they keep going. That is the design: an
availability trade-off that keeps the `asmbly.org` identity safe, the same one the device
limiter makes. The remedy is staff raising the setting (the logged-errors alarm tells
the maintainers); the limiter isn't changed for it.

**Consequence, accepted:** a double tap whose two requests race both pass the repeated
token check and both count, so it uses two of the cap's slots. When the cap refuses the
loser, the submit reads the token's submission again and answers with the winner's
drop-off if it is stored, so neither request is told it wasn't taken.

**Consequence, accepted:** every accepted submit writes the one shared `received-emails`
item under a version check, read again at most `TRIES = 3` times. Submits that arrive
together can lose that race three times, and the loser is answered "try again" with
nothing stored (fail closed). At about 80 drop-offs a week this is rare; it is a
contention limit, not a lost drop-off.

**Consequence, accepted:** the limiter keeps only the latest hits up to the cap, so
lowering the number trims what is kept: setting it back to 300 after lowering it in a
flood forgets the flood and allows up to 300 more in the same 24 hours.

**Revisit if:** a real day comes near the cap, or staff ask to pause the form on purpose
(a setting of 0 is refused today).

## A limit per recipient, under a keyed hash of the normalized address

**Chosen:** at most **3** drop-offs per recipient address in any 24 hours
(`RECIPIENT_LIMIT = RateLimit(limit=3, window=timedelta(days=1))` in `domain/limits.py`,
a rule beside `DEVICE_LIMIT` and `ADDRESS_LIMIT`, not a setting). The address is first
normalized by the domain (`normalized_recipient`): surrounding spaces removed, lowercased,
anything from a `+` in the local part removed when something comes before it, and for
`gmail.com` and `googlemail.com` the dots in the local part removed and the domain read
as `gmail.com`. `KeyHasher.recipient` then hashes it as every other key here is hashed:
HMAC-SHA256 with the form's `hash-key` from Parameter Store and the purpose prefix
`recipient#` in the input and the output. Only that hash reaches the limiter, which
stores it as `RATE#recipient#<64 hex>` with a TTL a day after the window ends. The
address and its hash are never logged; the refusal logs `drop_off_refused` with
`reason=recipient_limit` only. The recipient is counted after every field and photo has
passed, and the daily cap only when the recipient is allowed, so one address being
flooded doesn't use up the cap.

**Why:** the per-device and per-address limits can't see a caller who rotates both; the
recipient is what the harm is aimed at. Three a day is more than anyone drops off for
themselves (one drop-off holds up to 50 pieces) and keeps what a third party can be sent
small. A keyed hash keeps the address out of the limiter's items and makes the stored
value useless without the key, as 0002 already decided for devices and source addresses.
Normalizing closes the cheapest rotations (case, plus tags, Gmail's dots); a fixed rule
keeps it with the other limits #2 states. The alternatives that lost: accepting the
device and address limits alone (#18's other option), which leaves a third party open to
many emails; a studio setting (nothing suggests staff need to change it, and it would be
one more value on the settings page); hashing the address as typed (a plus tag would
make a new bucket each time).

**Consequence, accepted:** the keyed hash of an address is kept until its item's `ttl`,
about two days after the last hit, and DynamoDB deletes an expired item within a few days
of it; the drop-off itself keeps the address longer, until it closes (#7). Someone
who knows a person's address can block it from the form for a day by making three
drop-offs with it, which also sends that person three emails; the person can still drop
off through staff. Two people who share an address share its three. Normalization merges
some addresses that a mail server would treat as different (case in the local part, a
`+` that isn't a tag); that only makes the limit stricter. Other providers' aliasing
(dots elsewhere, other tag characters) isn't folded; the daily cap backs it.

**Revisit if:** real drop-offs are refused by it (a household or a class sharing one
address), or the studio starts checking addresses some other way.

## What a refused submission says

**Chosen:** a refusal by the daily cap or by the recipient limit shows one fixed,
friendly sentence on the form's error page (HTTP 429), the domain error
`DropOffNotTaken`: "Sorry, we can't take this drop-off online right now. Please ask
ceramics staff at the studio for help." It says nothing about a cap, a limit, a count,
an address or a hash, the same sentence for both, and nothing that differs with the
address typed. The device and source-address limits keep their own message.

**Why:** the person can't fix either refusal by changing the form, so the useful thing
to say is where to go. One sentence for both keeps a caller from learning whether an
address was used before, or that the studio is under a flood.

**Consequence, accepted:** a real person refused doesn't learn why; staff take the
drop-off by hand and the logs (by reason, never the address) tell the maintainers.

## An alarm on the mailer's send volume

**Chosen:** a metric filter on the mailer's log group counts `email_sent` lines, and
`email_unrecorded` lines with `outcome=sent` (an email that went but whose sent mark
couldn't be saved; one that failed logs `outcome=failed` and isn't counted), as
`EmailsSent` in the `asmbly-ceramics/<env>` namespace, and the alarm
`asmbly-ceramics-<env>-email-volume` goes off when 100 or more are sent in one hour
(`Period: 3600`, one evaluation period, missing data not breaching), notifying the
existing alarm topic. The threshold is in the template, not a studio setting: it is the
maintainers' signal, not the studio's.

**Why:** a fired full load sends up to 48 ready emails at once (`LOAD_CAPACITY`), so two
full kilns fired in the same hour stay under 100; anything above that is out of the
ordinary, whatever its kind, and the alarm sees it even if a bug sends outside the
form's limits. CloudWatch allows a one-hour period with one evaluation period
(PutMetricAlarm's `Period`: an alarm's evaluation range may be up to seven days, one day
for periods under an hour).

**Consequence, accepted:** it fires after the hour's sends, not before them; the cap and
the per-recipient limit are what stop a flood.

**Revisit if:** the studio fires more than two full kilns in an hour, or the alarm fires
on a normal day.

## What has and has not been seen to work

Written with the plan on 17 November 2026, before any of it was built. Each phase of the
plan adds what its tests show here, and the stage check after the merge shows the alarm
and the settings field in AWS.

**The daily cap and the alarm (phase 2, 17 November 2026), seen in tests only, against
the in-memory fakes and the template:**

- A new studio, and a studio item stored without the setting, read 300; the setting takes
  1 to 2,000 (a 5,000-digit number, a decimal, a sign or other digits are refused) and
  the history records "Received emails a day, at most: 300 → 120" with the username
  (`tests/domain/test_studio.py`, `tests/adapters/aws/test_keys.py`,
  `tests/use_cases/test_settings.py`, `tests/web/console/test_settings.py`, which also
  shows the field refused next to itself, the "not allowed" answer outside `ceramics`, and
  the CSRF check).
- With the cap at 2, the third drop-off raises `DropOffNotTaken`: no drop-off, email or
  submission stored, no photo kept, no ID taken, one `drop_off_refused` with
  `reason=daily_cap` at ERROR and no count; the window rolls (24 hours and a microsecond
  after the first, one more is taken); a refused field, a repeated token and a retry with
  the next ID never count; a raised or lowered setting applies to the next drop-off; a cap
  that can't be counted raises `RecordsUnavailable` after a WARNING line, and the page
  answers "try again" (`tests/use_cases/test_submit.py`, `tests/web/test_submit.py`).
- The public page shows only the sentence above (429), with nothing typed echoed, and no
  log line holds the made-up name, address or phone.
- The template's `EmailsSentFilter` counts the mailer's `email_sent` lines (and
  `email_unrecorded` with `outcome=sent`) into
  `EmailsSent`, and `EmailVolumeAlarm` sums them over 3,600 seconds, one period,
  threshold 100, notifying the alarm topic with the five tags
  (`tests/repo/test_app_template.py`; `cfn-lint` 1.57.1 passes). `sam validate` and
  `sam build` did not run in this run (no `sam` installed).

Not seen yet: the alarm and the setting in AWS (the stage check after the merge), and the
DynamoDB rate limiter under the fixed key, which only its existing stub tests cover.
