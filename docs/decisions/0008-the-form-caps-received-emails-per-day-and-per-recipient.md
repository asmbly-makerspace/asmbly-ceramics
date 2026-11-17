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
and the form function logs `drop_off_refused` with `reason=daily_cap` at WARNING. It is
kept below ERROR on purpose: the `logged-errors` alarm is one metric shared by the form,
the console and the mailer, and while the cap is reached (one attempt every 288 seconds
holds it shut) an ERROR line per refusal would keep that alarm in ALARM, so a
`mailer_crashed`, `photos_not_deleted` or `jwks_unavailable` then would notify nobody.
The maintainers' signal is the `email-volume` alarm (below), which a flood fast enough to
matter trips. Like the other limits it fails
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
included, and people are told to ask ceramics staff. No alarm watches the refusal
itself: a flood of 100 or more received emails in a clock hour trips `email-volume`, but
a slower one that reaches the cap (300 spread over a day) shows only as the WARNING lines
and as staff hearing from people the form turns away.

**Consequence, accepted:** because refused hits count, someone sending about one valid
submission every 86,400 ÷ cap seconds (every 288 seconds at 300) from rotating devices
and addresses keeps the form shut for as long as they keep going. That is the design: an
availability trade-off that keeps the `asmbly.org` identity safe, the same one the device
limiter makes. The remedy is staff raising the setting (they learn of it from people the
form turns away; the maintainers from them, or from the `reason=daily_cap` WARNING lines
in the form's log); the limiter isn't changed for it.

**Consequence, accepted:** a double tap whose two requests race both pass the repeated
token check and both count, so it uses two of the cap's slots. When the cap refuses the
loser, the submit reads the token's submission again and answers with the winner's
drop-off if it is stored, so neither request is told it wasn't taken.

**Consequence, accepted:** every accepted submit writes the one shared `received-emails`
item under a version check, read again at most `TRIES = 3` times. Submits that arrive
together can lose that race three times, and the loser is answered "try again" with
nothing stored (fail closed). At about 80 drop-offs a week this is rare; it is a
contention limit, not a lost drop-off.

**Consequence, accepted:** the limiter keeps only the latest hits up to the cap, so a
lowered number trims what is kept, at the first attempt counted while it is lowered (the
trim happens on a hit, not when the setting is saved): setting it back to 300 after an
attempt was counted at a lower number forgets the flood and allows up to 300 more in the
same 24 hours. Lowered and raised again before any attempt arrives, nothing is trimmed. The cap counts
every drop-off of the last 24 hours, so a number at or below that count refuses the next
one at once: the stage check after the merge sets the cap to the number of stage
drop-offs in the last 24 hours (phase 1's check drop-off among them) plus one, so the
next drop-off is taken and the one after it refused.

**Overlapping submits:** a submit reads and inspects its photos (seconds for six large
ones) before it counts the recipient and the cap, so a fast submit can count while a slow
one is still inspecting. Each counts at the time it reads the clock just before
counting, and the limiter counts and keeps hits later than a caller's own time, and
keeps the latest hits up to the limit whether or not they are in the writer's own window
(one just outside it may be inside the window of a slow submit that arrives later), so a
slow submit never forgets a fast one's hit, and a fast one never forgets hits a slow one
still counts: no 24 hours ever hold more than the cap's
number of allowed hits, nor more than 3 for one recipient.

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
of it. A taken drop-off keeps the address itself until it closes (#7), but not always
longer than the hash: a drop-off staff delete loses its contact at once, and a refused
submission stores no drop-off at all, so for those the address's keyed hash outlives
every other trace of it by about two days plus DynamoDB's TTL lag. The hash is useless
without the form's `hash-key`.

**Consequence, accepted:** refused hits count, as for every limit here (the
`RateLimiter` contract), so someone who knows a person's address can block it from the
form for as long as they keep going, not only for a day: three drop-offs with it, which
also send that person three emails, then three more submissions to it, each complete and
valid and from a device and network the other limits allow, before each 24 hours ends.
The refused ones send no email and store no drop-off; each logs only
`drop_off_refused` with `reason=recipient_limit` at INFO, which no alarm watches. The
person can still drop off through staff, who take it by hand, outside the system: that
drop-off gets no ID and no emails. Nothing in the console
lifts the limit: it lifts once 24 hours pass with fewer than three submissions to the
address. Rotating the `hash-key` resets the hashed counts (the recipient's among them)
only as each of the form's instances is replaced (a cold start, or a deploy that changes
the form function): each instance reads the key
once and keeps it, so until then a warm one counts under the old key and counts split
between the two. It never resets the daily cap, whose key is fixed. It has the side
effects the bootstrap runbook lists. The limiter isn't changed for it;
`tests/use_cases/test_submit.py` shows an address still refused after seven days of
three refused submissions a day. Two people who share an address share its three. Normalization merges
some addresses that a mail server would treat as different (case in the local part, a
`+` that isn't a tag); that only makes the limit stricter. Other providers' aliasing
(dots elsewhere, other tag characters) isn't folded; the daily cap backs it.

**Consequence, accepted:** the recipient is counted before the daily cap and before the
drop-off gets its ID, so its hit stays spent when nothing is then stored: the cap refuses,
the cap can't be counted (it fails closed), or taking the ID, keeping the photos or the
commit fails. The page answers "try again" (or the cap's refusal) and a retry with the
same submission token counts the recipient again, so three such failures in 24 hours use
up the address's three with no drop-off taken. The faults are rare (the cap's
contention consequence above, an AWS fault) and log their own lines; staff take the
drop-off by hand, outside the system (no ID, no emails). The cap's refusal is not rare in a flood: while the cap is reached it
refuses every attempt, so someone who tries three times then has used up their own
address's three and stays refused by the recipient limit after the cap reopens, until
24 hours pass with fewer than three attempts to it. Counting the recipient after the commit would let a race exceed the
limit.

**Consequence, accepted:** a double tap whose two requests race both pass the repeated
token check and both count the recipient, so it uses two of the address's three (and two
of the cap's slots, as the cap's section says). When the recipient refuses the loser,
the submit answers it with the winner's drop-off if it is stored. If the winner hasn't
committed yet when the loser is refused at the recipient's third slot, the loser's page
says it can't take this drop-off while the winner's drop-off is stored and emailed; that
is rare, since `upload.js`'s busy guard stops most double taps on the page.

**Consequence, accepted:** while the daily cap isn't reached, a refusal for an address
tells a caller who already knows that address that it was given three times in the last
24 hours (by anyone, that caller included). Learning it takes a complete, valid drop-off
with photos from a device and network the other limits allow, and a drop-off that is
taken instead emails that address, so probing is noisy. The page shows nothing more:
the refusal is the cap's, word for word and with the same status, so while the cap is
reached the page can't tell a caller which of the two refused. The timing may differ
slightly: a recipient refusal skips the cap's count, so it answers sooner by the cap's
count: one table read and one conditional write (more if that write loses a race). No dummy count is made to hide it; what it could tell is what the page
already tells while the cap isn't reached.

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
to say is where to go. One sentence for both keeps a caller from learning which of the
two refused, or that the studio is under a flood; it can't hide that a refusal happened
(the recipient section's last consequence says what that tells a caller).

**Consequence, accepted:** a real person refused doesn't learn why; staff take the
drop-off by hand, outside the system (it gets no ID and no emails), and the logs (by reason, never the address) tell the maintainers.

## An alarm on the mailer's send volume

**Chosen:** a metric filter on the mailer's log group counts `email_sent` lines, and
`email_unrecorded` lines with `outcome=sent` (an email that went but whose sent mark
couldn't be saved; one that failed logs `outcome=failed` and isn't counted), as
`EmailsSent` in the `asmbly-ceramics/<env>` namespace, and the alarm
`asmbly-ceramics-<env>-email-volume` goes off when 100 or more are sent in a clock hour
(`Period: 3600`, one evaluation period, missing data not breaching), notifying the
existing alarm topic. The threshold is in the template, not a studio setting: it is the
maintainers' signal, not the studio's.

**Why:** a fired full load sends up to 48 ready emails at once (`LOAD_CAPACITY`), so two
full kilns fired in the same hour stay under 100; anything above that is out of the
ordinary, whatever its kind, and the alarm sees the mailer's sends even if a bug sends
them outside the form's limits. It counts only the mailer's: the console's test email
(`test_email` in the console's log) isn't counted. CloudWatch allows a one-hour period with one evaluation period
(PutMetricAlarm's `Period`: an alarm's evaluation range may be up to seven days, one day
for periods under an hour).

**Consequence, accepted:** it fires after the hour's sends, not before them; the cap and
the per-recipient limit are what stop a flood. The hour is CloudWatch's clock-aligned
period, not a rolling one, so a burst that straddles the hour (up to 99 in each, 198 in
all) doesn't trip it.

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
  `reason=daily_cap` (at WARNING since the whole-branch review; ERROR before) and no
  count; the window rolls (24 hours and a microsecond
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

**The limit per recipient (phase 3, 17 November 2026), seen in tests only, against the
in-memory fakes:**

- `normalized_recipient` strips and lowercases, drops a plus tag (but keeps a local part
  that starts with `+`), folds Gmail's dots and `googlemail.com` into `gmail.com`, keeps
  dots for other domains (Gmail's label under another parent included), and refuses an invalid address with a message that never holds
  it (`tests/domain/test_dropoff.py`). `KeyHasher.recipient` gives one `recipient#` hash
  for one normalized address, a digest unrelated to the other purposes', holding no part
  of the address (`tests/use_cases/test_keys.py`).
- The fourth drop-off to one address in 24 hours, from a fourth device and source
  address, raises `DropOffNotTaken`: no drop-off, email or submission stored, no photo
  kept, no ID taken, one `drop_off_refused` with `reason=recipient_limit` at INFO. The
  address in another case or with a plus tag counts as the same recipient; the window
  rolls; another address isn't affected; a refused recipient isn't counted against the
  cap; a refused field and a repeated token aren't counted for the recipient; a double
  tap racing for the recipient's last slot answers the loser with the winner's drop-off;
  a recipient that can't be counted raises `RecordsUnavailable` after a WARNING line,
  with nothing stored and the cap not counted; a recipient counted before a cap that
  can't be counted stays counted, so three such failures leave the address refused with
  nothing stored; three refused submissions a day keep an address refused after seven
  days. No log line holds the address, its
  normalized form or a `recipient#` hash, and the limiter sees only the hash
  (`tests/use_cases/test_submit.py`).
- The public page answers a recipient refusal with 429 and a body identical to a cap
  refusal's for an address never used, echoing nothing typed (`tests/web/test_submit.py`).

- The whole-branch review's fixes: a hit with an earlier time doesn't forget later hits,
  on the fake and the DynamoDB adapter on moto
  (`tests/adapters/contract/test_ids_and_rate_limit.py`); a drop-off taken while another
  is still inspecting its photos takes the recipient's last place and the slow one is
  refused, as is a fifth (`tests/use_cases/test_submit.py`); the cap's refusal is logged
  at WARNING, outside the `logged-errors` filter (`tests/web/test_logging.py`,
  `tests/repo/test_app_template.py`).

Not seen yet: the limit on stage (the check after the merge: a fourth drop-off to an
inbox the tester can read that phases 1 and 2's checks didn't use (they spend one and two
of their inbox's three), or to the same inbox 24 hours after those checks, spelled four
ways the limit folds, refused, three received emails there; never a made-up address,
which would only bounce on the shared sending identity).
