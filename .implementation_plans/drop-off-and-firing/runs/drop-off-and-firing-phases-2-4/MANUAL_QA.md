# Manual QA: drop-off and firing, phases 2a-2d, 3 and 4

Nothing is deployed: there is no template, no page and no deploy workflow. What you can
check by hand today is the checks, the use cases against the in-memory fakes, and a few
guarantees the AWS adapters' tests hold. Run everything from the repository root.

## 1. The checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
uv run pytest tests/repo -q
```

Expect all to pass, and the coverage floor in `pyproject.toml` to hold.

## 2. Use cases against the fakes

This builds the test `world` (every fake and use case, with made-up data), submits a
drop-off through the form's use case, fires it in a load and sends the queued emails.

```bash
cat > "${TMPDIR:-/tmp}/qa.py" <<'PY'
from tests.use_cases.conftest import world
from tests.use_cases.flows import dropped_off, fired, pending, send_all

w = world.__wrapped__()
drop_off = dropped_off(w, 1)           # AC-1, made up, photos kept
print(drop_off, w.waiting().totals)    # one waiting bisque drop-off
print(len(pending(w)))                 # 1: the received email is queued
fired(w, drop_off)                     # a load: add, start firing, mark fired
print(send_all(w), len(w.mailer.sent)) # two emails sent: received, ready
PY
PYTHONPATH=. uv run python "${TMPDIR:-/tmp}/qa.py"
```

Expected: `AC-1`, a totals line with one drop-off and `overdue=0`, `1`, then
`[<EmailStatus.SENT: 'sent'>, <EmailStatus.SENT: 'sent'>] 2`.

Other things to try with `w`: `w.find("AC-1")` (search by ID), `w.waiting()` after
`fired` (empty), and the close (`w.close`) after moving `w.clock` past the pickup
window; `tests/use_cases/test_close.py` shows the calls and what stays (the ID, dates and load).
`tests/use_cases/conftest.py` lists every use case on `world`.

## 3. Key tests to read

| Guarantee | Test |
| --- | --- |
| The close deletes name, email, phone, message and photos, keeps the rest | `tests/use_cases/test_close.py::test_closing_deletes_name_email_phone_message_and_photos_and_keeps_the_rest` |
| Photos are deleted before the record closes | `test_photos_are_deleted_before_the_record_is_closed` (same file) |
| No personal detail reaches a log from any flow | `tests/use_cases/test_no_personal_details_logged.py` |
| The close deletes all 12 photo keys in one call, without listing | `tests/adapters/aws/test_photos.py::test_delete_drop_off_deletes_the_twelve_keys_in_one_call_without_listing` |
| S3 is addressed on its regional host | `tests/adapters/aws/test_clients.py::test_s3_is_addressed_on_its_regional_virtual_host` |
| The mailer logs no address, subject or body | `tests/adapters/aws/test_mailer.py::test_nothing_logged_holds_the_address_subject_or_body` |
| No object key or upload ID is logged | `tests/adapters/aws/test_photos.py::test_no_object_key_or_upload_id_is_logged` |
| No token, code or verifier is logged | `tests/adapters/aws/test_staff_tokens.py::test_no_token_code_or_verifier_is_logged` |

Run one: `uv run pytest tests/adapters/aws/test_photos.py -q`.

## 4. Not checkable yet

The pages, the stream and schedule triggers, real DynamoDB, S3, SES and Cognito
behavior, and the deploy. They come with phases 5 to 9.
