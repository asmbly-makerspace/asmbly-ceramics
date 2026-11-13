# Manual QA: drop-offs and firings, phase 1 (domain model, ports and fakes)

Manual acceptance steps for `feat/drop-off-and-firing-phase-1`, organized by story so
each check maps back to an issue (#2, #3, #4, #5, #6, #7).

> **Automated coverage** already passed the integration gate: 1169 tests passed, coverage
> 99.50% (the floor is in `pyproject.toml`). Nothing was skipped. The domain's rules are
> tested against the in-memory fakes. This pull request ships the domain model, the ports
> and their in-memory fakes, plus plan documents. It ships no page, no endpoint, no console,
> no email sent and nothing in AWS, so there is nothing to try on a phone or in a browser.
> The steps below are checks the maintainer can do locally: run the commands, read named
> tests, and confirm the decisions the code makes.

## Prerequisites

- Where: locally, from the repository root, with `uv`. Today a merge deploys nothing, so
  every step runs on your machine and nothing reaches AWS.
- Accounts: none. There is no sign-in and no AWS access in this change.
- Data: none to create. The tests build made-up records in `tests/domain/builders.py`.
- Made-up details only: the tests use made-up names such as "Test Potter" and addresses
  built in code at `example.org`, never a real person or a real photo.
- Devices: a terminal and an editor or `git` to read test files.

---

## #2: Drop off a piece and get an ID on screen (phases 1b, 1d)

No surface a person can see yet: the form, its page and the ID on screen come in later
phases. What this pull request ships for it is the drop-off's rules, the ID format and the
rate limit, in the domain and the fakes.

1. Run `uv run pytest tests/domain/test_dropoff.py tests/domain/test_photos.py tests/domain/test_ids.py -q` → all pass. In `test_dropoff.py`, read `test_each_field_refusal_has_its_key` and `test_several_bad_fields_are_reported_together`: a bad pieces count, photo count, glaze type, name, email or phone is refused with its own field key, all together.
2. Read `test_a_refusal_message_holds_no_personal_detail` and `test_a_drop_off_repr_holds_no_personal_detail` in `tests/domain/test_dropoff.py` → a refusal and the drop-off's printed form name the ID and field, never the name, email or phone.
3. Run `uv run pytest tests/adapters/test_memory.py -q -k rate_limiter` → three tests pass. Read `test_rate_limiter_allows_10_then_refuses_within_the_window_and_allows_after` and `test_rate_limiter_window_is_rolling_across_a_fixed_boundary` → the 11th hit in 10 minutes is refused, and the window rolls: ten hits just before a clock boundary and one just after are still refused. Confirm you want a rolling window rather than a fixed one.

## #3: Ceramics staff sign in and see what's waiting (phases 1c)

No surface a person can see yet: sign-in and the waiting list page come with the use cases
and the console. This pull request ships the waiting list's ordering, totals, overdue rule
and search matching.

4. Run `uv run pytest tests/domain/test_waiting.py tests/domain/test_search.py -q` → all pass.
5. Read `test_waiting_is_oldest_first`, `test_totals_count_pieces_per_firing_type_and_glaze` and `test_overdue_at_60_days_waiting_not_59` in `tests/domain/test_waiting.py` → oldest first, totals in pieces, overdue at 60 whole Austin days and not 59.
6. Read `tests/domain/test_search.py` → `AC-12`, `ac12`, `12` and part of a name are the forms the search accepts.

## #4: Build a kiln load and fire it (phases 1c, 1d)

No surface a person can see yet: there is no console and no email. This pull request ships
the load's states and rules, and the ready email being queued, in the domain.

7. Run `uv run pytest tests/domain/test_load.py -q` → all pass.
8. Read `test_a_load_holds_at_most_48`, `test_add_with_a_different_firing_type_needs_confirmation` and `test_nothing_is_added_or_removed_once_fired` → the 48 limit, the firing-type confirmation, and a fired load staying fixed.
9. Read `test_firing_again_is_refused_and_queues_nothing` and `test_fire_marks_every_member_fired_and_queues_one_ready_email_each` → firing twice is refused and queues no second email.
10. Decision to confirm: read `test_change_load_refuses_a_new_firing_type_once_it_has_members` and the `FiringTypeLocked` error in `src/asmbly_ceramics/domain/errors.py` → a load with drop-offs in it can't change its firing type until they are removed. Confirm that is the rule you want.
11. Run `uv run pytest tests/adapters/test_memory.py -q -k all_or_nothing` → passes. Decision to confirm: a `commit` of several changes to the fake records store is all-or-nothing (one conflict leaves none applied). Confirm you want to keep all-or-nothing, since a fire is one transaction.

## #5: Reject a drop-off with a reason and a message (phases 1b)

No surface a person can see yet: no reject dialog, no rejected email. This pull request
ships the rejection and undo rules.

12. Run `uv run pytest tests/domain/test_dropoff.py -q -k "reject or undo"` → all pass.
13. Read `test_reject_needs_a_message_for_other` and `test_reject_refuses_a_message_over_1000` → a reason that needs a message is refused without one, and 1,001 characters are refused.
14. Read `test_undo_on_the_same_austin_day`, `test_undo_refused_the_next_austin_day` and `test_undo_counts_austin_days_even_when_utc_changes_date` → undo works only the same Austin day.

## #6: Staff manage the studio's settings in the console (phases 1a)

No surface a person can see yet: no settings page. This pull request ships the studio's
settings rules and history.

15. Run `uv run pytest tests/domain/test_studio.py -q` → all pass.
16. Read `test_sending_address_must_be_at_asmbly_org` → an address outside `asmbly.org` is refused.
17. Decision to confirm: read `test_used_item_can_be_retired_not_deleted`, `test_an_active_item_must_be_retired_before_it_is_deleted` and `test_a_retired_unused_item_can_be_deleted` → only a retired, unused item can be deleted, and a used one is only retired. Confirm delete-only-retired.
18. Decision to confirm: read `test_the_history_holds_no_sending_address` and `test_change_email_settings_records_one_change_per_value` → the settings history records that the address changed, not the address itself. Confirm history without the address.

## #7: Finished drop-offs close and personal details are deleted (phases 1b, 1c)

No surface a person can see yet: the daily close job and the counts come in later phases.
This pull request ships the rule for when a drop-off may close and what closing deletes.

19. Run `uv run pytest tests/domain/test_closing.py -q` → all pass.
20. Read `test_close_deletes_contact_message_and_photos_and_keeps_the_rest` → closing removes the contact, the rejection message and the photos, and keeps the rest.
21. Read `test_fired_closes_after_the_window_from_the_ready_email`, `test_rejected_closes_after_the_window_from_the_rejection` and `test_fired_without_a_sent_ready_email_never_closes` → the pickup window starts at the ready email's send time (fired) or the rejection (rejected).

#8 (the switch from ClickUp) is not touched by this pull request.

---

## Automated re-run (optional)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```
