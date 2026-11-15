"""`deploy.yml`: stage, its smoke test, then prod; credentials only through the
environments' secrets; nothing that prints a resolved address or an account ID.

The Actions log of this public repository is public, so this file is the fence for what
the deploy may print.
"""

import re
from typing import Any

import yaml

from tests.repo.files import REPO

PATH = REPO / ".github" / "workflows" / "deploy.yml"
TEXT = PATH.read_text()
WORKFLOW: dict[Any, Any] = yaml.safe_load(TEXT)
JOBS: dict[str, Any] = WORKFLOW["jobs"]
SITES = {"stage": "https://ceramics-stage.asmbly.org", "prod": "https://ceramics.asmbly.org"}
TIP_NOTICE = "A newer commit is on main; it deploys itself."
TIP_CONDITION = "steps.tip.outputs.tip == 'true'"


def steps(job: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = JOBS[job]["steps"]
    return found


def index(job: str, predicate: str) -> int:
    for position, step in enumerate(steps(job)):
        if (
            predicate in step.get("uses", "")
            or predicate in step.get("run", "")
            or predicate == step.get("name")
        ):
            return position
    raise AssertionError(f"{job} has no step matching {predicate}")


def test_prod_runs_only_after_stage_and_neither_is_cancelled_mid_deploy() -> None:
    assert set(JOBS) == {"stage", "prod"}
    assert JOBS["prod"]["needs"] == "stage"
    assert "needs.stage.outputs.tip == 'true'" in JOBS["prod"]["if"]
    for name, job in JOBS.items():
        assert job["environment"] == {"name": name, "url": SITES[name]}
        assert job["concurrency"] == {"group": f"deploy-{name}", "cancel-in-progress": False}
        assert job["env"] == {"CONFIG_ENV": name, "SITE_URL": SITES[name]}


def test_both_jobs_deploy_only_the_tip_of_main_with_the_same_words() -> None:
    texts = []
    for job in JOBS:
        first = steps(job)[0]
        assert first["name"] == "Deploy only the tip of main"
        assert first["id"] == "tip"
        assert first["env"] == {"GH_TOKEN": "${{ github.token }}"}
        assert TIP_NOTICE in first["run"]
        texts.append(first["run"])
        for step in steps(job)[1:]:
            assert TIP_CONDITION in step["if"], f"{job}: {step.get('name') or step.get('uses')}"
    assert texts[0] == texts[1]


def test_the_steps_run_in_order_and_the_mask_comes_before_any_aws_output() -> None:
    for job in JOBS:
        order = [
            index(job, "actions/checkout@"),
            index(job, "aws-actions/setup-sam@"),
            index(job, "Build"),
            index(job, "Compose check"),
            index(job, "aws-actions/configure-aws-credentials@"),
            index(job, "Mask the account ID"),
            index(job, "Deploy"),
            index(job, "Smoke test"),
            index(job, "Summary"),
        ]
        assert order == sorted(order), job
        mask = steps(job)[index(job, "Mask the account ID")]["run"]
        assert mask == 'echo "::add-mask::$(aws sts get-caller-identity --query Account --output text)"'


def test_credentials_come_only_from_the_environment_s_secrets() -> None:
    for job in JOBS:
        credentials = steps(job)[index(job, "aws-actions/configure-aws-credentials@")]
        assert credentials["with"] == {
            "role-to-assume": "${{ secrets.AWS_DEPLOY_ROLE_ARN }}",
            "aws-region": "${{ vars.AWS_REGION }}",
            "mask-aws-account-id": True,
        }
        deploy = steps(job)[index(job, "Deploy")]
        assert deploy["env"] == {
            "EXECUTION_ROLE": "${{ secrets.AWS_CFN_EXECUTION_ROLE_ARN }}",
            "ARTIFACTS_BUCKET": "${{ vars.SAM_ARTIFACTS_BUCKET }}",
            "WEB_ADAPTER_LAYER_ARN": "${{ vars.WEB_ADAPTER_LAYER_ARN }}",
        }
    secrets = set(re.findall(r"secrets\.([A-Z_]+)", TEXT))
    assert secrets == {"AWS_DEPLOY_ROLE_ARN", "AWS_CFN_EXECUTION_ROLE_ARN"}
    assert "vars.AWS_DEPLOY_ROLE_ARN" not in TEXT
    assert "vars.AWS_CFN_EXECUTION_ROLE_ARN" not in TEXT


def test_the_deploy_passes_every_parameter_and_names_no_address() -> None:
    for job in JOBS:
        run = steps(job)[index(job, "Deploy")]["run"]
        assert 'python3 scripts/sam_parameters.py "$CONFIG_ENV" "AppVersion=${GITHUB_SHA::7}"' in run
        assert '--parameter-overrides "$parameters"' in run
        assert '--role-arn "$EXECUTION_ROLE"' in run
        assert "@" not in run
        smoke = steps(job)[index(job, "Smoke test")]
        assert smoke["env"] == {"FORM_OFFLINE": "${{ vars.FORM_OFFLINE }}"}
        assert smoke["run"] == SMOKE_RUN
        compose = steps(job)[index(job, "Compose check")]["run"]
        assert compose == "python3 scripts/compose_check.py .aws-sam/build/MailerFunction"


SMOKE_RUN = (
    "flags=()\n"
    'if [ "$FORM_OFFLINE" = "true" ]; then flags+=(--form-offline); fi\n'
    'env -i PATH="$PATH" python3 scripts/smoke.py "$SITE_URL" "${GITHUB_SHA::7}" "${flags[@]}"\n'
)


def test_the_smoke_test_runs_without_the_deploy_role_s_credentials() -> None:
    """configure-aws-credentials exports the role's keys to every later step; the smoke
    test's environment is emptied but for PATH, and its flag is the script's own."""
    from scripts import smoke

    assert smoke.FORM_OFFLINE_FLAG == "--form-offline"
    assert "no AWS credentials" in (smoke.__doc__ or "")
    for job in JOBS:
        run = steps(job)[index(job, "Smoke test")]["run"]
        command = [line for line in run.splitlines() if "smoke.py" in line]
        assert command, job
        assert all(line.startswith('env -i PATH="$PATH" ') for line in command), job
        assert "AWS_" not in run


def test_every_action_is_pinned_to_a_commit_sha_as_the_header_says() -> None:
    assert "pinned to a commit SHA" in TEXT.split("\nname:", 1)[0]
    for job in JOBS:
        for step in steps(job):
            if "uses" in step:
                assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_nothing_prints_a_stack_s_description_or_a_secret() -> None:
    for forbidden in (
        "describe-stacks",
        "describe-change-set",
        "describe-stack",
        "list-exports",
        "get-template",
    ):
        assert forbidden not in TEXT
    for job in JOBS:
        for step in steps(job):
            run = step.get("run", "")
            assert "secrets." not in run, "a secret is passed through env, never in a script"
            assert not re.search(r"echo[^\n]*\$(EXECUTION_ROLE|ARTIFACTS_BUCKET|WEB_ADAPTER_LAYER_ARN)", run)
        summary = steps(job)[index(job, "Summary")]["run"]
        assert "GITHUB_STEP_SUMMARY" in summary
        assert set(re.findall(r"\$\{?([A-Z_]+)", summary)) <= {
            "CONFIG_ENV",
            "SITE_URL",
            "GITHUB_SHA",
            "SMOKE",
            "GITHUB_STEP_SUMMARY",
        }


def test_the_sam_cli_is_set_up_at_the_workflow_s_version() -> None:
    assert WORKFLOW["env"]["SAM_CLI_VERSION"]
    for job in JOBS:
        sam = steps(job)[index(job, "aws-actions/setup-sam@")]
        assert sam["with"] == {"version": "${{ env.SAM_CLI_VERSION }}", "use-installer": True}
        python = steps(job)[index(job, "actions/setup-python@")]
        assert python["with"] == {"python-version-file": ".python-version"}


def test_every_by_hand_aws_change_after_a_failed_first_create_is_a_runbook_step() -> None:
    # CLAUDE.md allows an AWS change only as a runbook step the maintainer asks for.
    runbook = (REPO / "docs" / "runbooks" / "operations.md").read_text()
    section = runbook.split("## If the first create of a stack fails\n", 1)[1].split("\n## ", 1)[0]
    steps = re.split(r"\n### ", section)[1:]
    assert len(steps) >= 6
    for step in steps:
        title = step.splitlines()[0]
        for part in ("**Do:**", "**Check:**", "**Who confirms:**", "**Undo:**"):
            assert part in step, f"{title}: {part}"
    for command in ("delete-stack", "delete-table", "delete-bucket", "--disable-rollback"):
        assert command in section, command
    plan = (REPO / ".implementation_plans" / "drop-off-and-firing" / "phase-7-first-deploy.md").read_text()
    assert (
        "delete-table"
        not in plan.split("### If the first create of a stack fails", 1)[1].split("\n### ", 1)[0]
    )
