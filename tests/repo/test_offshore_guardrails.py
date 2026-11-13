"""The /offshore guardrail hook blocks what an unattended run must never do, and nothing else.

`.claude/hooks/offshore-guardrails.sh` runs before every tool call. For a session that
claimed itself with `: offshore-start <run>` (and the subagents it spawns, which carry its
session_id) it blocks questions, pushes to `main`, merges, deploys, AWS changes (and any
AWS command not run with the `asmbly` profile), hook bypasses, hand edits to `uv.lock`, a
lower coverage floor and `pull_request_target`. Every other session, in the same folder
or not, is allowed everything, and several runs can go on at once. Each case below pipes
a PreToolUse payload into the hook and checks its exit code: 0 allows the call, 2
blocks it.

Every case runs twice: once reading the payload with jq, and once with jq off the PATH,
where the hook falls back to its awk reader. On macOS the second run uses /bin/bash,
which is bash 3.2, so the hook stays portable.
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.repo.files import REPO

HOOK = REPO / ".claude" / "hooks" / "offshore-guardrails.sh"
SETTINGS = REPO / ".claude" / "settings.json"
RUN = "3-drop-off-form"
BRANCH = f"feat/{RUN}"
SESSION = "session-run-1"
# What the hook needs besides bash; jq is left out of the fallback PATH on purpose.
TOOLS = ("awk", "cat", "cut", "date", "find", "git", "grep", "head", "ls", "mkdir", "rm", "sed", "sort", "tr")


@dataclass(frozen=True)
class Setup:
    reader: str
    bash: str
    path: str


@dataclass(frozen=True)
class Result:
    code: int
    stderr: str


def which(tool: str) -> str:
    found = shutil.which(tool)
    assert found, f"{tool} is needed to run the guardrail tests"
    return found


@pytest.fixture(scope="module")
def repos(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A project checked out on the run's branch, and a second checkout on main."""
    git = which("git")
    root = tmp_path_factory.mktemp("guardrails")
    found: dict[str, Path] = {}
    for name, branch in (("project", BRANCH), ("on-main", "main")):
        repo = root / name
        repo.mkdir()
        subprocess.run([git, "init", "-q", str(repo)], check=True)  # noqa: S603
        # An unborn branch is enough: the hook only asks which branch is checked out.
        subprocess.run(  # noqa: S603
            [git, "-C", str(repo), "symbolic-ref", "HEAD", f"refs/heads/{branch}"], check=True
        )
        (repo / "pyproject.toml").write_text("[tool.coverage.report]\nfail_under = 90\n")
        found[name] = repo
    return found


@pytest.fixture(scope="module", params=["jq", "awk"])
def setup(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Setup:
    if request.param == "jq":
        if shutil.which("jq") is None:
            pytest.skip("jq is not installed; the awk run covers the hook")
        return Setup("jq", which("bash"), os.environ["PATH"])
    bin_dir = tmp_path_factory.mktemp("no-jq-bin")
    for tool in TOOLS:
        (bin_dir / tool).symlink_to(which(tool))
    old_bash = Path("/bin/bash")
    bash = str(old_bash) if old_bash.exists() else which("bash")
    return Setup("awk", bash, str(bin_dir))


def claims(project: Path) -> Path:
    return project / ".git" / "offshore" / "sessions"


def reset(project: Path) -> None:
    shutil.rmtree(project / ".offshore", ignore_errors=True)
    shutil.rmtree(project / ".git" / "offshore", ignore_errors=True)


def claim(project: Path, session: str = SESSION, run: str = RUN) -> None:
    """What `: offshore-start <run>` leaves behind, written directly to keep the tests quick."""
    claims(project).mkdir(parents=True, exist_ok=True)
    state = project / ".offshore" / run
    (claims(project) / session).write_text(f"run={run}\nroot={project}\nstate={state}\nstarted=then\n")


def call(
    setup: Setup,
    project: Path,
    payload: dict[str, Any] | str,
    env: dict[str, str] | None = None,
    session: str = SESSION,
) -> Result:
    """Pipe one payload into the hook, as `session` unless the payload names one."""
    environment = {"PATH": setup.path, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(project)}
    environment.update(env or {})
    if isinstance(payload, dict):
        payload = {"session_id": session, **payload}
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    done = subprocess.run(  # noqa: S603
        [setup.bash, str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
        timeout=30,
    )
    return Result(done.returncode, done.stderr)


def run(
    setup: Setup,
    project: Path,
    payload: dict[str, Any] | str,
    claimed: bool = True,
    env: dict[str, str] | None = None,
    session: str = SESSION,
) -> Result:
    """One call in a fresh state: the run's session claimed, or no claim at all."""
    reset(project)
    if claimed:
        claim(project)
    return call(setup, project, payload, env, session)


def assert_checked(project: Path) -> None:
    """An allowed call was checked: the hook didn't fall over and allow it by default."""
    log = (project / ".offshore" / RUN / "guardrails.log").read_text()
    assert "internal error" not in log, log


def bash(command: str, cwd: Path | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


def edit(path: str, old: str, new: str) -> dict[str, Any]:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": old, "new_string": new}}


def write(path: str, content: str) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


HEREDOC_AMEND = "git commit --amend -m \"$(cat <<'EOF'\nfix: typo\nEOF\n)\""
HEREDOC_MESSAGE = (
    "git commit -F - <<'EOF'\nfix: stop using --no-verify\n\ngit push origin main is blocked\nEOF"
)
HEREDOC_SUBSTITUTION = "git commit -m \"$(cat <<'EOF'\nchore: explain --amend and reset --hard\nEOF\n)\""
HEREDOC_DOCS = "git commit -F - <<'EOF'\ndocs: sam deploy\n\naws s3 rm s3://b/a\nEOF"
HEREDOC_WORKFLOW = "cat > .github/workflows/x.yml <<'EOF'\non:\n  pull_request_target:\nEOF"
HEREDOC_PYPROJECT = "cat > pyproject.toml <<'EOF'\n[tool.coverage.report]\nfail_under = 50\nEOF"

BLOCKED_COMMANDS = [
    # Pushes to main, in every form.
    "git push origin main",
    "git push -u origin HEAD:main",
    "git push origin feat/x:refs/heads/main",
    "git push origin :main",
    "git push origin --delete main",
    "git push origin --all",
    "git push --mirror origin",
    "git add -A && git commit -m wip && git push origin main",
    "git -C .. push origin main",
    'echo "$(git push origin main)"',
    "git push \\\n  origin main",
    # Force pushes.
    f"git push --force origin {BRANCH}",
    f"git push -f origin {BRANCH}",
    f"git push origin +{BRANCH}",
    # Hook bypass, hard resets, amends.
    'git commit --no-verify -m "wip"',
    "git commit -n -m wip",
    "git commit -anm wip",
    f"git push --no-verify origin {BRANCH}",
    "git rebase --no-verify origin/main",
    "git -c core.hooksPath=/dev/null commit -m wip",
    "git config core.hooksPath /dev/null",
    "git reset --hard HEAD~1",
    "git commit --amend --no-edit",
    HEREDOC_AMEND,
    # Merges and repository settings.
    "gh pr merge 12 --squash",
    "gh pr merge 12 --admin --squash --match-head-commit abc1234",
    "gh -R asmbly-makerspace/asmbly-ceramics pr merge 12",
    "gh api -X PUT repos/asmbly-makerspace/asmbly-ceramics/pulls/12/merge",
    "gh api -X PUT repos/asmbly-makerspace/asmbly-ceramics/rulesets/1",
    "gh workflow run deploy.yml",
    "gh variable set DEPLOY_ENABLED --body true",
    "gh secret set TOKEN",
    "gh repo edit --visibility private",
    # Deploys.
    "sam deploy",
    "sam deploy --config-env prod",
    "sam --config-env stage deploy --no-confirm-changeset",
    "sam sync --stack-name asmbly-ceramics-stage",
    "sam delete",
    "sam remote invoke fn",
    "sam package --s3-bucket b",
    "sam pipeline bootstrap",
    "/opt/homebrew/bin/sam deploy",
    "sam build && sam deploy",
    "uvx --from aws-sam-cli sam deploy",
    "timeout -k 5 60 sam deploy",
    "sam \\\n  deploy",
    # AWS changes, even with the right profile.
    "aws --profile asmbly cloudformation deploy --template-file template.yaml",
    "aws --profile asmbly cloudformation delete-stack --stack-name asmbly-ceramics-stage",
    "aws --profile asmbly lambda update-function-code --function-name f",
    "aws --profile asmbly lambda invoke --function-name f out.json",
    "aws --profile asmbly s3 cp a s3://b/a",
    "aws --profile asmbly s3 rm s3://b/a",
    "aws --profile asmbly s3 sync . s3://b",
    "aws --profile asmbly iam create-role --role-name r",
    "aws --profile asmbly ssm put-parameter --name /asmbly-ceramics/stage/x --value y",
    "aws --profile asmbly dynamodb put-item --table-name t --item i",
    "aws --profile asmbly athena start-query-execution --query-string x",
    "aws --profile asmbly sesv2 send-email --content x",
    "aws --profile asmbly configure set region us-east-2",
    "aws --profile asmbly s3",
    "AWS_PROFILE=asmbly aws s3 rm s3://b/a",
    "uv run aws --profile asmbly s3 rm s3://b/a",
    'aws "s3" "rm" s3://b/a --profile asmbly',
    "aws --profile asmbly s3 ls && aws --profile asmbly s3 rm s3://b/a",
    'echo "$(aws --profile asmbly s3 rm s3://b/a)"',
    "bash -c 'aws --profile asmbly s3 rm s3://b/a'",
    'sh -c "sam deploy"',
    'eval "git push origin main"',
    # Secret values.
    "aws --profile asmbly secretsmanager get-secret-value --secret-id x",
    "aws --profile asmbly ssm get-parameter --name /asmbly-ceramics/stage/form-key --with-decryption",
    "aws ssm get-parameter --name x \\\n  --with-decryption --profile asmbly",
    # Any aws command with another profile, or none.
    "aws sts get-caller-identity",
    "aws --profile default sts get-caller-identity",
    "aws --profile=makervera cloudformation describe-stacks",
    "AWS_PROFILE=newberry aws s3 ls",
    "export AWS_PROFILE=other && aws s3 ls",
    "export AWS_PROFILE=asmbly; unset AWS_PROFILE; aws s3 ls",
    "/usr/local/bin/aws s3 ls",
    # uv.lock by hand.
    "sed -i '' 's/1.0/2.0/' uv.lock",
    "echo x >> uv.lock",
    "printf x > ./uv.lock",
    "cat new.lock | tee uv.lock",
    "cp /tmp/other.lock uv.lock",
    "rm uv.lock",
    # The coverage floor.
    "sed -i '' 's/fail_under = 90/fail_under = 80/' pyproject.toml",
    HEREDOC_PYPROJECT,
    "uv run pytest --cov --cov-fail-under=50",
    "uv run pytest --cov --cov-fail-under 0",
    # pull_request_target.
    HEREDOC_WORKFLOW,
    "sed -i 's/pull_request:/pull_request_target:/' .github/workflows/pr-checks.yml",
    # Switching the guardrail off from the shell.
    "echo x > .claude/hooks/offshore-guardrails.sh",
    "sed -i '' 's/exit 2/exit 0/' .claude/hooks/offshore-guardrails.sh",
    "chmod -x .claude/hooks/offshore-guardrails.sh",
    "printf '{\"disableAllHooks\": true}' > .claude/settings.local.json",
    "cp /tmp/settings.json .claude/settings.json",
    "python3 -c \"open('.claude/settings.local.json', 'w').write('{}')\"",
    "rm -rf .claude",
    "rm -rf .git/offshore",
    f'rm -f "$(git rev-parse --git-common-dir)/offshore/sessions/{SESSION}"',
    "echo run=other > .git/offshore/sessions/someone-else",
    "mv .git/offshore/sessions /tmp/claims",
    "rm -rf .offshore",
    "rm -rf .git",
    f": offshore-end {RUN} && git push origin main",
    # Abbreviated long options, which git accepts.
    "git commit --no-verif -m wip",
    "git commit --amen --no-edit",
    "git reset --har HEAD~1",
    f"git push --no-verif origin {BRANCH}",
    "git rebase --no-ver origin/main",
    # A backslash or a wrapper in front of the command.
    "\\aws --profile asmbly s3 rm s3://b/a",
    "\\git push origin main",
    "\\gh pr merge 5",
    "\\sam deploy",
    "command git push origin main",
    "env -u AWS_PROFILE aws s3 ls",
    "nice -n 5 sam deploy",
    "sudo -u root aws --profile asmbly s3 rm s3://b/a",
    # gh api calls that merge or change the repository.
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: 1}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {pullRequestId: 1}) { x } }'",
    "gh api repos/o/r/actions/workflows/deploy.yml/dispatches -f ref=main",
    "gh api -X PUT repos/o/r/actions/secrets/TOKEN -f encrypted_value=x",
    "gh api repos/o/r/actions/variables -f name=X -f value=y",
    "gh api -X PATCH repos/o/r -f visibility=private",
    "gh api --method DELETE repos/o/r/git/refs/heads/main",
    "gh api repos/o/r/git/refs -f ref=refs/heads/x -f sha=abc",
    "gh api -XPOST repos/o/r/merges",
    "gh api --method=PUT repos/o/r/contents/README.md --input body.json",
    # Reads CLAUDE.md forbids: a drop-off's details, photos, staff accounts.
    "aws --profile asmbly dynamodb scan --table-name asmbly-ceramics-stage",
    "aws --profile asmbly dynamodb query --table-name asmbly-ceramics-stage",
    "aws --profile asmbly dynamodb get-item --table-name asmbly-ceramics-stage --key k",
    "aws --profile asmbly dynamodb batch-get-item --request-items x",
    "aws --profile asmbly dynamodb execute-statement --statement x",
    "aws --profile asmbly s3api get-object --bucket b --key AC-12/1.jpg out.jpg",
    "aws --profile asmbly s3 cp s3://asmbly-ceramics-stage-photos/AC-12/1.jpg .",
    "aws --profile asmbly s3 sync s3://asmbly-ceramics-stage-photos .",
    "aws --profile asmbly ssm get-parameter --name x --with-decryption=true",
    "aws --profile asmbly cognito-idp list-users --user-pool-id x",
    # Other deploy tools.
    "cdk deploy --all",
    "npx cdk deploy",
    "terraform apply -auto-approve",
    "terraform -chdir=infra destroy",
    "pulumi up --yes",
]

ALLOWED_COMMANDS = [
    f"git push --force-with-lease origin {BRANCH}",
    'git push -u --force-with-lease origin "feat/$PLAN_NAME"',
    "git push origin main:feat/from-main",
    "git push origin feat/main-fix",
    "git push --delete origin offshore/drop-off-and-firing/phase-4-aws-adapters",
    "git push",
    "git push origin HEAD",
    'git commit -m "don\'t use --no-verify"',
    'git commit -m "Fix --amend handling; never git push origin main --force"',
    HEREDOC_MESSAGE,
    HEREDOC_SUBSTITUTION,
    HEREDOC_DOCS,
    "git reset --soft abc1234",
    "git log --oneline origin/main..HEAD",
    "git config --get core.hooksPath",
    'echo "git push origin main --force"',
    'grep -rn -- "--no-verify" docs/',
    "gh pr view 12 --json state",
    "gh pr create --draft --base main --title 'feat: drop-offs' --body-file /tmp/body.md",
    "gh pr ready 12",
    "gh pr checks 12 --watch",
    'gh pr create --title "chore: stop running sam deploy" --body "aws s3 rm is blocked"',
    "uv run ruff check . && uv run ruff format --check .",
    "uv run mypy",
    "uv run pytest --cov",
    "uv run pytest --cov --cov-fail-under=95",
    "uv add starlette",
    "uv lock",
    "git checkout -- uv.lock",
    "git diff uv.lock",
    "cat uv.lock | head",
    "cp uv.lock /tmp/uv.lock.bak",
    "grep -n fail_under pyproject.toml",
    "grep -rn pull_request_target .github/ 2>/dev/null",
    "sam build",
    "sam validate --lint",
    "sam --version",
    "uvx --from aws-sam-cli sam validate --lint",
    "aws --version",
    "aws help",
    "aws s3 help",
    "aws --profile asmbly s3 ls",
    "aws --profile asmbly s3 ls s3://b > out.txt",
    "aws --profile asmbly sts get-caller-identity",
    "aws --profile=asmbly --region us-east-2 cloudformation describe-stacks",
    "aws --profile asmbly cloudformation validate-template --template-body x",
    "aws --profile asmbly cloudformation wait stack-update-complete --stack-name x",
    "aws --profile asmbly logs tail /aws/lambda/asmbly-ceramics-stage-web --since 1h",
    "aws --profile asmbly logs start-query --log-group-name x --query-string y",
    "aws --profile asmbly ssm get-parameter --name /config/cognito/staff/issuer",
    "aws --profile asmbly secretsmanager describe-secret --secret-id x",
    "aws --profile asmbly iam simulate-principal-policy --policy-source-arn x",
    "aws --profile asmbly configure list",
    'aws --query "Stacks[0].Outputs" --output text --profile asmbly cloudformation describe-stacks',
    "AWS_PROFILE=asmbly aws sts get-caller-identity",
    "export AWS_PROFILE=asmbly && aws s3 ls",
    "AWS_PROFILE=asmbly; aws s3 ls",
    "env AWS_PROFILE=asmbly aws sesv2 get-account",
    'echo "sam deploy and aws s3 rm"',
    'git commit -m "docs: never run sam deploy or aws s3 rm by hand"',
    "# aws s3 rm s3://b/a",
    'grep -rn "aws s3 rm" docs/',
    "cat samconfig.toml",
    ": offshore-end some-other-run",
    'ls "$(git rev-parse --git-common-dir)/offshore/sessions"',
    f"cat .git/offshore/sessions/{SESSION}",
    "git worktree add .claude/worktrees/offshore-9-kiln-schedule -b feat/9-kiln-schedule origin/main",
    "git worktree list",
    "cat .claude/settings.json",
    "grep -n exit .claude/hooks/offshore-guardrails.sh",
    "cat .offshore/guardrails.log",
    "ls .offshore/",
    "cp .implementation_plans/p/CHECKPOINT.json .offshore/checkpoint.json",
    "rm -f .offshore/pr-body.md",
    "git commit --no-verbose -m wip",
    "sed -n '/pkg-info/p' uv.lock",
    "gh api repos/o/r/pulls/12/comments -X POST -f body=fixed -F in_reply_to=1",
    "gh api repos/o/r/pulls/12/comments --paginate",
    "gh api repos/o/r/issues/12/comments -f body=done",
    "gh api repos/o/r/issues/1/sub_issues -X POST -F sub_issue_id=5",
    "gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: 1}) { thread { id } } }'",
    "gh api repos/o/r/actions/secrets",
    "gh api repos/o/r/rulesets --jq '.[] | .name'",
    "gh pr comment 12 --body done",
    "aws --profile asmbly dynamodb describe-table --table-name asmbly-ceramics-stage",
    "aws --profile asmbly s3api head-object --bucket b --key k",
    "aws --profile asmbly s3api list-objects-v2 --bucket b",
    "\\git status",
    "terraform plan",
    "cdk synth",
    "pulumi preview",
]


@pytest.mark.parametrize("command", BLOCKED_COMMANDS)
def test_a_dangerous_command_is_blocked(setup: Setup, repos: dict[str, Path], command: str) -> None:
    result = run(setup, repos["project"], bash(command, repos["project"]))
    assert result.code == 2, result.stderr
    assert "OFFSHORE GUARDRAIL: blocked" in result.stderr


@pytest.mark.parametrize("command", ALLOWED_COMMANDS)
def test_ordinary_work_is_allowed(setup: Setup, repos: dict[str, Path], command: str) -> None:
    result = run(setup, repos["project"], bash(command, repos["project"]))
    assert result.code == 0, result.stderr
    assert_checked(repos["project"])


def test_a_push_while_main_is_checked_out_is_blocked(setup: Setup, repos: dict[str, Path]) -> None:
    result = run(setup, repos["project"], bash("git push", repos["on-main"]))
    assert result.code == 2
    assert "main is checked out" in result.stderr


def test_the_claim_is_found_from_any_folder_of_the_repository(
    setup: Setup, repos: dict[str, Path], tmp_path: Path
) -> None:
    # The claim lives in the repository's common git folder, so a call from a subfolder
    # finds it even when Claude Code's project folder is somewhere else.
    project = repos["project"]
    inside = project / "src"
    inside.mkdir(exist_ok=True)
    elsewhere = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    assert run(setup, project, bash("git push origin main", inside), env=elsewhere).code == 2
    assert run(setup, project, bash("git push origin main", inside), claimed=False, env=elsewhere).code == 0
    assert not (project / ".offshore").exists()
    assert not (tmp_path / ".offshore").exists()


def test_another_session_in_the_same_folder_is_untouched(setup: Setup, repos: dict[str, Path]) -> None:
    project = repos["project"]
    for payload in (
        bash("git push origin main", project),
        {"tool_name": "AskUserQuestion", "tool_input": {}},
        edit(str(project / "uv.lock"), "a", "b"),
    ):
        assert run(setup, project, payload, session="someone-else").code == 0
    assert not (project / ".offshore").exists(), "the hook wrote state for another session"


def test_the_runs_subagents_are_guarded(setup: Setup, repos: dict[str, Path]) -> None:
    project = repos["project"]
    subagent = {**bash("git push origin main", project), "agent_id": "a1", "agent_type": "general-purpose"}
    assert run(setup, project, subagent).code == 2
    # Should a subagent ever carry its own session_id, its transcript still sits in the
    # folder of the session that spawned it.
    transcript = f"/home/u/.claude/projects/p/{SESSION}/subagents/agent-a1.jsonl"
    assert run(setup, project, {**subagent, "transcript_path": transcript}, session="other").code == 2
    assert run(setup, project, subagent, session="other").code == 0


def start(setup: Setup, cwd: Path, session: str, run: str, project: Path | None = None) -> Result:
    return call(setup, project or cwd, bash(f": offshore-start {run}", cwd), session=session)


def end(setup: Setup, cwd: Path, session: str, run: str, project: Path | None = None) -> Result:
    return call(setup, project or cwd, bash(f": offshore-end {run}", cwd), session=session)


def test_starting_claims_this_session_and_ending_releases_it(setup: Setup, repos: dict[str, Path]) -> None:
    project = repos["project"]
    push = bash("git push origin main", project)
    reset(project)
    assert call(setup, project, push).code == 0
    assert start(setup, project, SESSION, RUN).code == 0
    claimed = (claims(project) / SESSION).read_text()
    assert f"run={RUN}\n" in claimed
    assert (project / ".offshore" / RUN).is_dir()
    assert call(setup, project, push).code == 2
    assert call(setup, project, push, session="someone-else").code == 0
    # A resume claims again without harm, and keeps the start time.
    assert start(setup, project, SESSION, RUN).code == 0
    assert (claims(project) / SESSION).read_text() == claimed
    assert end(setup, project, SESSION, RUN).code == 0
    assert not (claims(project) / SESSION).exists()
    assert call(setup, project, push).code == 0


def test_two_runs_go_on_at_once(setup: Setup, repos: dict[str, Path]) -> None:
    project = repos["project"]
    push = bash("git push origin main", project)
    reset(project)
    assert start(setup, project, "session-a", "2-drop-off-form").code == 0
    assert start(setup, project, "session-b", "6-studio-settings").code == 0
    assert call(setup, project, push, session="session-a").code == 2
    assert call(setup, project, push, session="session-b").code == 2
    assert end(setup, project, "session-a", "2-drop-off-form").code == 0
    assert call(setup, project, push, session="session-a").code == 0
    assert call(setup, project, push, session="session-b").code == 2
    logs = project / ".offshore"
    assert "BLOCK" in (logs / "2-drop-off-form" / "guardrails.log").read_text()
    assert "BLOCK" in (logs / "6-studio-settings" / "guardrails.log").read_text()


def test_one_run_belongs_to_one_session(setup: Setup, repos: dict[str, Path]) -> None:
    project = repos["project"]
    reset(project)
    assert start(setup, project, "session-a", RUN).code == 0
    taken = start(setup, project, "session-b", RUN)
    assert taken.code == 2
    assert "held by another session" in taken.stderr
    assert not (claims(project) / "session-b").exists()
    # And one session runs one run at a time.
    assert start(setup, project, "session-a", "9-kiln-schedule").code == 2
    # Ending someone else's run does nothing.
    assert end(setup, project, "session-b", RUN).code == 0
    assert (claims(project) / "session-a").exists()


@pytest.mark.parametrize(
    ("command", "session"),
    [
        (f": offshore-start {RUN}", ""),
        (": offshore-start Bad_Slug", SESSION),
        (": offshore-start -x", SESSION),
    ],
)
def test_a_start_the_hook_cant_scope_is_refused(
    setup: Setup, repos: dict[str, Path], command: str, session: str
) -> None:
    project = repos["project"]
    reset(project)
    assert call(setup, project, bash(command, project), session=session).code == 2
    assert not claims(project).exists()


def test_a_new_session_takes_over_a_silent_run_to_resume_it(setup: Setup, repos: dict[str, Path]) -> None:
    project = repos["project"]
    reset(project)
    assert start(setup, project, "session-a", RUN).code == 0
    assert start(setup, project, "session-b", RUN).code == 2
    log = project / ".offshore" / RUN / "guardrails.log"
    an_hour_ago = log.stat().st_mtime - 3600
    os.utime(log, (an_hour_ago, an_hour_ago))
    assert start(setup, project, "session-b", RUN).code == 0
    assert not (claims(project) / "session-a").exists()
    assert "TAKEOVER" in log.read_text()


def test_a_run_in_its_own_worktree_is_guarded_everywhere_in_the_repository(
    setup: Setup, tmp_path: Path
) -> None:
    git = which("git")
    repo = tmp_path / "repo"
    identity = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t" + "@" + "example.org",
        "GIT_COMMITTER_EMAIL": "t" + "@" + "example.org",
        "PATH": os.environ["PATH"],
    }
    for command in (
        ["init", "-q", "-b", "main", str(repo)],
        ["-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"],
        ["-C", str(repo), "worktree", "add", "-q", "-b", "feat/9-kiln-schedule", ".claude/worktrees/w"],
    ):
        subprocess.run([git, *command], check=True, env=identity)  # noqa: S603
    worktree = repo / ".claude" / "worktrees" / "w"
    assert start(setup, worktree, SESSION, "9-kiln-schedule", project=repo).code == 0
    assert (repo / ".git" / "offshore" / "sessions" / SESSION).exists()
    assert (worktree / ".offshore" / "9-kiln-schedule").is_dir()
    push = bash("git push origin main", repo)
    assert call(setup, repo, push).code == 2
    assert call(setup, repo, push, session="someone-else").code == 0


def test_an_aws_profile_in_the_environment_counts(setup: Setup, repos: dict[str, Path]) -> None:
    project = repos["project"]
    command = bash("aws s3 ls", project)
    assert run(setup, project, command, env={"AWS_PROFILE": "asmbly"}).code == 0
    assert run(setup, project, command, env={"AWS_PROFILE": "other"}).code == 2


BLOCKED_TOOLS: list[tuple[str, dict[str, Any]]] = [
    ("a question", {"tool_name": "AskUserQuestion", "tool_input": {"questions": []}}),
    (
        "the GitHub merge tool",
        {"tool_name": "mcp__github__merge_pull_request", "tool_input": {"pullNumber": 12}},
    ),
    ("editing uv.lock", edit("{root}/uv.lock", 'version = "1.0"', 'version = "2.0"')),
    ("writing uv.lock", write("uv.lock", "version = 1\n")),
    (
        "editing uv.lock with MultiEdit",
        {
            "tool_name": "MultiEdit",
            "tool_input": {"file_path": "{root}/uv.lock", "edits": [{"old_string": "a", "new_string": "b"}]},
        },
    ),
    ("lowering the floor", edit("{root}/pyproject.toml", "fail_under = 90", "fail_under = 85")),
    ("removing the floor", edit("{root}/pyproject.toml", "fail_under = 90\n", "")),
    ("a pyproject without a floor", write("{root}/pyproject.toml", "[project]\nname = 'x'\n")),
    (
        "a pyproject with a lower floor",
        write("{root}/pyproject.toml", "[tool.coverage.report]\nfail_under = 10\n"),
    ),
    (
        "a lower floor in a workflow",
        edit("{root}/.github/workflows/pr-checks.yml", "--cov", "--cov --cov-fail-under=0"),
    ),
    ("a lower floor in .coveragerc", write("{root}/.coveragerc", "[report]\nfail_under = 40\n")),
    (
        "pull_request_target in a workflow",
        edit("{root}/.github/workflows/pr-checks.yml", "  pull_request:", "  pull_request_target:"),
    ),
    (
        "a new workflow on pull_request_target",
        write(".github/workflows/x.yml", "on:\n  pull_request_target:\n"),
    ),
    ("editing the hook", edit("{root}/.claude/hooks/offshore-guardrails.sh", "exit 2", "exit 0")),
    ("editing the settings", write("{root}/.claude/settings.json", "{}")),
    (
        "the AWS tool that runs code",
        {"tool_name": "mcp__claude_ai_AWS_MCP__aws___run_script", "tool_input": {}},
    ),
    (
        "the AWS upload tool",
        {"tool_name": "mcp__claude_ai_AWS_MCP__aws___get_presigned_url", "tool_input": {}},
    ),
    ("pushing with the GitHub tool", {"tool_name": "mcp__github__push_files", "tool_input": {}}),
    (
        "writing a file with the GitHub tool",
        {"tool_name": "mcp__github__create_or_update_file", "tool_input": {}},
    ),
    ("auto-merge with the GitHub tool", {"tool_name": "mcp__github__enable_pr_auto_merge", "tool_input": {}}),
    ("writing a claim", write("{root}/.git/offshore/sessions/someone-else", "run=x")),
    ("editing local settings", write("{root}/.claude/settings.local.json", '{"disableAllHooks": true}')),
]

ALLOWED_TOOLS: list[tuple[str, dict[str, Any]]] = [
    ("reading a file", {"tool_name": "Read", "tool_input": {"file_path": "{root}/uv.lock"}}),
    ("editing code", edit("{root}/src/asmbly_ceramics/domain/drop_off.py", "x = 1", "x = 2")),
    ("raising the floor", edit("{root}/pyproject.toml", "fail_under = 90", "fail_under = 92")),
    ("editing pyproject elsewhere", edit("{root}/pyproject.toml", 'name = "a"', 'name = "b"')),
    (
        "a pyproject that keeps its floor",
        write("{root}/pyproject.toml", "[tool.coverage.report]\nfail_under = 90\n"),
    ),
    ("a workflow on pull_request", write("{root}/.github/workflows/x.yml", "on:\n  pull_request:\n")),
    ("a doc that mentions pull_request_target", edit("{root}/CLAUDE.md", "a", "never pull_request_target")),
    ("writing the plan's checkpoint", write("{root}/.implementation_plans/p/CHECKPOINT.json", "{}")),
    (
        "a spawn, which is logged",
        {"tool_name": "Agent", "tool_input": {"subagent_type": "review-lead", "description": "Cold review"}},
    ),
    ("another tool", {"tool_name": "Glob", "tool_input": {"pattern": "**/*.py"}}),
    ("no tool name", {"tool_input": {}}),
    (
        "AWS documentation",
        {"tool_name": "mcp__claude_ai_AWS_MCP__aws___search_documentation", "tool_input": {}},
    ),
    ("reading a pull request", {"tool_name": "mcp__github__get_pull_request", "tool_input": {}}),
    ("another MCP tool", {"tool_name": "mcp__claude_ai_Linear__list_issues", "tool_input": {}}),
]


def with_root(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(json.dumps(payload).replace("{root}", str(root)))
    return loaded


@pytest.mark.parametrize(("name", "payload"), BLOCKED_TOOLS, ids=[name for name, _ in BLOCKED_TOOLS])
def test_a_dangerous_tool_call_is_blocked(
    setup: Setup, repos: dict[str, Path], name: str, payload: dict[str, Any]
) -> None:
    result = run(setup, repos["project"], with_root(payload, repos["project"]))
    assert result.code == 2, f"{name}: {result.stderr}"


@pytest.mark.parametrize(("name", "payload"), ALLOWED_TOOLS, ids=[name for name, _ in ALLOWED_TOOLS])
def test_an_ordinary_tool_call_is_allowed(
    setup: Setup, repos: dict[str, Path], name: str, payload: dict[str, Any]
) -> None:
    result = run(setup, repos["project"], with_root(payload, repos["project"]))
    assert result.code == 0, f"{name}: {result.stderr}"
    assert_checked(repos["project"])


@pytest.mark.parametrize("payload", ["this is not json", ""])
def test_a_payload_it_cant_read_is_allowed(setup: Setup, repos: dict[str, Path], payload: str) -> None:
    assert run(setup, repos["project"], payload).code == 0


@pytest.mark.parametrize(
    "payload",
    [
        bash("git push origin main"),
        bash("git commit --amend"),
        bash("sam deploy"),
        bash("aws s3 rm s3://b/a"),
        {"tool_name": "AskUserQuestion", "tool_input": {}},
        edit("uv.lock", "a", "b"),
    ],
)
def test_nothing_is_blocked_without_a_claim(
    setup: Setup, repos: dict[str, Path], payload: dict[str, Any]
) -> None:
    project = repos["project"]
    assert run(setup, project, payload, claimed=False).code == 0
    assert not (project / ".offshore").exists(), "the hook wrote state outside a run"
    assert not claims(project).exists(), "the hook wrote a claim outside a run"


def test_decisions_and_spawns_are_logged(setup: Setup, repos: dict[str, Path]) -> None:
    project = repos["project"]
    assert run(setup, project, bash("git push origin main", project)).code == 2
    state = project / ".offshore" / RUN
    blocked = (state / "guardrails.log").read_text()
    spawn = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "scribe", "description": "Write the briefing"},
    }
    assert run(setup, project, spawn).code == 0
    assert "BLOCK tool=Bash git push to main" in blocked
    assert "scribe | Write the briefing" in (state / "agents.log").read_text()
    if setup.reader == "awk":
        assert "WARN jq not found" in (state / "guardrails.log").read_text()


def test_the_settings_run_the_hook_before_every_tool() -> None:
    settings = json.loads(SETTINGS.read_text())
    entries = settings["hooks"]["PreToolUse"]
    commands = [
        hook["command"] for entry in entries for hook in entry["hooks"] if entry.get("matcher") == "*"
    ]
    assert any(".claude/hooks/offshore-guardrails.sh" in command for command in commands)
