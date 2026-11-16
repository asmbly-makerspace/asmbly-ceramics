# 0006: The console's role may delete a drop-off's photos, so staff can delete a drop-off made by mistake

Status: accepted by the maintainer (@sababado), 15 November 2026. It amends
[0002](0002-how-the-app-is-built-and-deployed.md): the console function's row in
"Hosting" (what the console may do), which [0004](0004-the-form-role-and-the-photo-bucket-name.md)
describes as giving deleting kept photos to the close only.

On 15 November 2026 the maintainer asked for a way to delete a drop-off made by
accident or as a test in production. The form has no sign-in, so a mistaken or test
drop-off holds whatever name, email, phone and photos were typed. Before this change,
the only way out was to reject it. That emails the address, keeps the details until the
daily close runs after the pickup window, and counts the drop-off as a rejection.
Asked whether the photos should go at once or wait for the close, the maintainer chose
"at once", which needs this right.

## The console may delete photos under `dropoffs/`

**Chosen:** the console function's role has `s3:DeleteObject` on `dropoffs/*` in its
environment's photo bucket (statement `DeleteKeptPhotos` in `infra/app.yaml`), as the
close's role has. `tests/repo/test_app_template.py` pins it. The console still has no
`s3:PutObject`, and nothing under `uploads/`. It is used by one call:
`PhotoStore.delete_drop_off`, one `DeleteObjects` of the drop-off's 12 known keys, made by
`DeleteDropOff` when a signed-in member of the `ceramics` group deletes a waiting drop-off
and types its ID to confirm. The function permissions boundary (decision 0003) already
allowed it, so the bootstrap is unchanged.

**Why:** deleting a drop-off should delete what the person gave, now, with the record.
The photos are deleted before the record is committed, as the close does, so a failure
between the two leaves a waiting drop-off without photos that staff delete again, never
a deleted drop-off whose photos remain. The alternative was to mark the drop-off deleted
and let the daily close delete the photos. That needs no new right, but keeps photos of
a drop-off that shouldn't exist for up to a day, and gives the close a second kind of
work.

**Consequence, accepted:** a console function whose code was taken over could delete any
drop-off's photos, fired ones included, by guessing `AC-n` keys. The bucket has no
versioning, so they couldn't be recovered. The console already reads every photo and
changes every record, so this adds the loss of photos to what such a takeover could do,
not their exposure.

**Revisit if:** the bucket gets versioning, or the delete moves to a function that
already holds this right.

## What has and has not been seen to work

Checked on 15 November 2026: `cfn-lint`, `sam validate --lint` and `sam build` pass on
the template; the use case and the pages are tested against the in-memory photo store,
and `S3PhotoStore.delete_drop_off` against S3's stubs (phase 4). Only the deploy shows
the role's statement taking effect, and a first delete on stage shows the photos gone.
