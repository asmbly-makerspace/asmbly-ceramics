"""The rules on `main`, as the repository states them.

.github/rulesets/main.json is what gets sent to GitHub, and .github/CODEOWNERS
decides whose review the ruleset asks for. Together they say who can change
what reaches production, so a change that loosens either should fail a test
and be made on purpose. The ruleset is applied by hand; this file is what to apply.
"""

import json
from typing import Any

from tests.repo.files import REPO

RULESET: dict[str, Any] = json.loads((REPO / ".github" / "rulesets" / "main.json").read_text())
OWNER = "@sababado"
# GitHub's account ID for @sababado (`gh api users/sababado --jq .id`). A
# ruleset names a person by ID, not username, so a renamed account keeps it.
OWNER_ACCOUNT_ID = 2850189


def rule(kind: str) -> dict[str, Any]:
    (found,) = [item for item in RULESET["rules"] if item["type"] == kind]
    parameters: dict[str, Any] = found.get("parameters", {})
    return parameters


def test_the_rules_are_in_force_on_the_default_branch() -> None:
    assert RULESET["target"] == "branch"
    assert RULESET["enforcement"] == "active"
    assert RULESET["conditions"]["ref_name"] == {"include": ["~DEFAULT_BRANCH"], "exclude": []}


def test_a_pull_request_needs_a_code_owners_approval_of_its_last_push() -> None:
    reviews = rule("pull_request")
    assert reviews["required_approving_review_count"] >= 1
    assert reviews["require_code_owner_review"] is True
    assert reviews["dismiss_stale_reviews_on_push"] is True
    assert reviews["require_last_push_approval"] is True
    assert reviews["required_review_thread_resolution"] is True
    assert reviews["allowed_merge_methods"] == ["squash"]


def test_only_the_owner_can_bypass_and_only_through_a_pull_request() -> None:
    # `pull_request` mode: the owner can merge a pull request that lacks the
    # review, but can't push to main.
    assert RULESET["bypass_actors"] == [
        {"actor_id": OWNER_ACCOUNT_ID, "actor_type": "User", "bypass_mode": "pull_request"}
    ]


def test_main_cannot_be_deleted_or_rewritten_and_needs_the_check() -> None:
    kinds = {item["type"] for item in RULESET["rules"]}
    assert {"deletion", "non_fast_forward", "required_linear_history"} <= kinds
    required = [check["context"] for check in rule("required_status_checks")["required_status_checks"]]
    assert required == ["PR check"]
    # The check GitHub waits for is a job's name in the PR checks workflow.
    assert "    name: PR check\n" in (REPO / ".github" / "workflows" / "pr-checks.yml").read_text()


def test_the_owner_is_the_code_owner_of_every_file() -> None:
    lines = (REPO / ".github" / "CODEOWNERS").read_text().splitlines()
    patterns = [line.split() for line in lines if line.strip() and not line.startswith("#")]
    # The last matching pattern wins, so the catch-all comes first and nothing
    # after it may hand a path to someone else or to nobody.
    assert patterns[0] == ["*", OWNER]
    for pattern, *owners in patterns:
        assert owners == [OWNER], pattern


def test_claude_md_states_the_same_rules() -> None:
    # The ruleset is applied by hand after it merges, so until then GitHub doesn't
    # enforce it. CLAUDE.md is what agents follow either way; it must say the same.
    text = " ".join((REPO / "CLAUDE.md").read_text().split())
    assert "`PR check` is the required check" in text
    assert "squash merges" in text
    assert "code owner's approving review" in text
    assert "Push to `main`" in text  # under Never
    assert OWNER in text
