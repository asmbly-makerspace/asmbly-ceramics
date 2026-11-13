## Summary

<!-- 1-3 sentences: what changed and why. -->

## Closes

<!-- GitHub issues this PR delivers, one per line: Closes #2
     Use "Refs #2" when the issue isn't finished by this PR. -->

## Risk

<!-- "none", or list: what this does to people's personal details (name, email,
     phone, photos): where they are stored, who can see them, how long they are kept;
     anything newly logged or printed; the public drop-off form's validation or limits;
     who can open the staff console; the emails that are sent, to whom and from which
     address; AWS resources, IAM or deploy-role changes; anything another repository
     reads. If it changes the live app: the step's check, its undo, and who confirms it. -->

none

## Test plan

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov`
- [ ]
