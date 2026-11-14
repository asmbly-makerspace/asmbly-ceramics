# Briefing: drop-off and firing, phases 2-4

## What happened

- Prep split phase 2 into 2a to 2d. Phases 2a, 2b, 2c, 2d, 3 and 4 were each built,
  reviewed, cold-reviewed by `review-lead` and `privacy-guardian`, and fixed.
- The integration gate was clean: 2034 tests. After the follow-up fixes there are 2059
  tests at 99.48% coverage.
- The whole-branch cold review raised a BLOCK. The presigned S3 POST went to the global
  host, but the planned CSP allows only the regional one. It was fixed and re-reviewed.
- You asked to merge soon, so PR #23 was merged on your word (admin squash, `94d22cd`)
  before the docs, the manual QA and this briefing. They come in this follow-up PR.
- Phase 4's sub-agent stalled about 12 hours waiting on a background review and was
  nudged.
- Nothing reaches AWS: there is no template, page or deploy yet.

Details: `CHECKPOINT.json` (phases, decisions, gate and review results) and
`MANUAL_QA.md`, both in this folder.

## Action items for you

| Item | When |
| --- | --- |
| Answer #20: retention for a fired drop-off whose ready email never sends | Before phase 9 merges |
| Build the #19 backstop: kept photos whose drop-off was never stored (no lifecycle on `dropoffs/`) | Before prod takes real drop-offs |
| Write the amending decision record for 0002 (below) | Before phase 7 merges |
| asmbly-staff-login: the app's sign-in client must allow the `openid` and `email` scopes | Before phase 8 |
| Update the 800-line phase limit if ~5,000 should last (below) | When you decide |

**The 0002 amendment must cover:**

- The form role's rights from the plan README: S3 on `uploads/` including `ListBucket`,
  studio seeding `PutItem` on `STUDIO`, and `PutItem` on `DROPOFF#*` and `EMAIL#*`.
- The risk that a compromised form function could rewrite an address and queue an email
  with that drop-off's photos.
- The bucket's random suffix, which replaces 0002's `-photos-<account>`.

**The 800-line phase limit** is still in `.implementation_plans/readme.md` and in the
`prep`, `build` and `plan-tech` skills.

## For later phases

- **Phase 5 and 7:**
  - Rotating the hash key orphans live submissions; the runbook must say so.
  - The form role seeding the studio needs a conditional create.
  - Phase 7 picks a whole-request deadline, because per-call timeouts don't bound a
    submit.
  - The stream mailer gets a 30 s SES read timeout.
- **Phase 6:** refuse requests without `X-Forwarded-For` and take the last value; never
  log `str(error)`; send distinct slots.
- **Phase 8:**
  - Every console route checks the token and the `ceramics` group. That includes
    `/console/drop-offs/AC-n/photos/n` and `/console/emails`. Test no token and a token
    outside the group.
  - Search and the rejection preview go by POST.
  - Throttle JWKS refetch for unknown kids.
  - Use a fixed `redirect_uri` on this site.

## Open questions

- Product: the rejected email has hours but no pick-up-by date. This matches the plan.
- Inspector memory under 1 GB is unmeasured.

## Issues opened during the run

- #18: a rate limit per recipient address on the public form
- #19: backstop for kept photos whose drop-off was never stored
- #20: retention of fired drop-offs whose ready email never sends, and rejected ones
  whose email didn't go
- #21: follow-ups from phase 3 (the retire-then-delete race, a lost claim response, a
  repeated Start load)
- #22: an outbox claim whose commit outcome is unknown waits for a manual retry
