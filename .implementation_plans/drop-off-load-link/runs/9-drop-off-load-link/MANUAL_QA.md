# Manual QA: link a drop-off's page to its load

Manual acceptance steps for the branch, organized by story: the staff console's drop-off
page (story #3) and loads (story #4).

> **Automated coverage** passed: 3896 tests, coverage 99.34% (the floor is in
> `pyproject.toml`) on the code change, plus 68 passing tests in the drop-off page's file
> after the last test edit. `sam` and `cfn-lint` were not run: no template changed.

## Prerequisites

- Where: locally (`uv run python -m asmbly_ceramics.web.local`, the fakes) or stage.
- Accounts: a staff account in the `ceramics` group.
- Data: two made-up drop-offs (for example "Test Potter", an address at `example.org`),
  one kiln load.
- Devices: a desktop browser.

---

## #3 and #4: the drop-off page shows and links to its load

1. Open a waiting drop-off's page → no "Load:" line is shown.
2. Add that drop-off to a load, then reopen its page → a "Load: L-n" line appears under
   the state line ("In load L-n").
3. Click the load's ID → the load's page opens, and the drop-off is listed in it.
4. Fire the load, then reopen the drop-off's page → the "Load: L-n" link is still there
   and still opens the load.
5. Remove another drop-off from its load before firing, then reopen its page → the
   "Load:" line is gone.
6. Open a drop-off's page signed in outside the `ceramics` group → "not allowed", no link.

---

## Automated re-run (optional)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```
