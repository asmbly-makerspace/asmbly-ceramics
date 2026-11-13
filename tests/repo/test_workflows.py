"""What every workflow may do, and that `PR check` waits for every other check.

`PR check` is the one required check, so a job it doesn't wait for can fail without
stopping a merge. There is no deploy yet, so no workflow may ask for AWS credentials.
When the deploy comes, its plan names the one job that may, and this file says so.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.repo.files import REPO

WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))


def load(path: Path) -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(path.read_text())
    return loaded


def triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the key `on` as the boolean true.
    found: dict[str, Any] = workflow.get("on") or workflow[True]
    return found


def test_there_are_workflows_to_check() -> None:
    assert {path.name for path in WORKFLOWS} >= {"pr-checks.yml", "dependency-audit.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_a_workflow_only_reads_the_repository(path: Path) -> None:
    workflow = load(path)
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        assert "permissions" not in job, f"{path.name}: job {name} widens its permissions"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_no_job_gets_aws_credentials_or_an_environment(path: Path) -> None:
    for name, job in load(path)["jobs"].items():
        steps = job.get("steps", [])
        assert not any("configure-aws-credentials" in step.get("uses", "") for step in steps), (
            f"{path.name}: {name}"
        )
        assert "environment" not in job, f"{path.name}: {name}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_every_job_has_a_time_limit_and_a_pinned_runner(path: Path) -> None:
    for name, job in load(path)["jobs"].items():
        assert job["timeout-minutes"] <= 30, f"{path.name}: {name}"
        assert job["runs-on"] == "ubuntu-24.04", f"{path.name}: {name}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_no_workflow_runs_untrusted_code_with_the_repositorys_rights(path: Path) -> None:
    # The repository is public: anyone can open a pull request from a fork.
    assert "pull_request_target" not in triggers(load(path))


def test_pr_check_waits_for_every_other_job_and_fails_if_one_did() -> None:
    jobs = load(REPO / ".github" / "workflows" / "pr-checks.yml")["jobs"]
    (summary,) = [job for job in jobs.values() if job.get("name") == "PR check"]
    others = {key for key, job in jobs.items() if job is not summary}
    assert set(summary["needs"]) == others
    # It runs even when a job it needs failed, so that it reports the failure
    # instead of being skipped, which a required check would read as passing.
    assert summary["if"] == "${{ !cancelled() }}"
    assert '"$result" != success' in summary["steps"][0]["run"]


def test_pr_checks_run_on_every_pull_request() -> None:
    assert triggers(load(REPO / ".github" / "workflows" / "pr-checks.yml")) == {"pull_request": None}
