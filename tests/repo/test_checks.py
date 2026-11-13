"""The checks CLAUDE.md tells people to run are the ones CI runs, at the same versions.

"Done means verified" in CLAUDE.md is what an agent runs before it says a change is
done. If CI ran something else, a change could pass one and fail the other.
"""

import re
import tomllib
from typing import Any

from tests.repo.files import REPO

WORKFLOWS = REPO / ".github" / "workflows"
PR_CHECKS = (WORKFLOWS / "pr-checks.yml").read_text()
PYPROJECT: dict[str, Any] = tomllib.loads((REPO / "pyproject.toml").read_text())

# Where a person or an agent is told which command to run.
DOCUMENTS = [
    REPO / "README.md",
    REPO / "CLAUDE.md",
    REPO / "CONTRIBUTING.md",
    REPO / ".claude" / "settings.json",
    REPO / ".github" / "PULL_REQUEST_TEMPLATE.md",
    *sorted((REPO / ".claude").rglob("*.md")),
    *sorted((REPO / "docs").rglob("*.md")),
]


def claude_md_commands() -> list[str]:
    """The commands in the code block under "Done means verified", without their comments."""
    section = (REPO / "CLAUDE.md").read_text().split("## Done means verified", 1)[1]
    block = re.search(r"```bash\n(.*?)```", section, re.DOTALL)
    assert block, "CLAUDE.md's Done means verified has no bash block"
    commands: list[str] = []
    for line in block.group(1).splitlines():
        command = line.split("#", 1)[0].strip()
        if command:
            commands.extend(part.strip() for part in command.split("&&"))
    return commands


def workflow_version(workflow: str, name: str) -> str:
    """The value of a top-level `env:` entry, which must be the workflow's only definition of it."""
    text = (WORKFLOWS / workflow).read_text()
    values: list[str] = re.findall(rf"^  {name}: '([0-9.]+)'$", text, re.MULTILINE)
    assert len(values) == 1, f"{workflow} should define {name} exactly once, in its top-level env"
    return values[0]


def pinned(package: str, text: str) -> set[str]:
    return set(re.findall(rf"{package}==([0-9.]+[0-9])", text))


def test_claude_md_names_the_checks() -> None:
    commands = claude_md_commands()
    for expected in (
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy",
        "uv run pytest --cov",
    ):
        assert expected in commands


def test_ci_runs_every_uv_command_claude_md_names() -> None:
    for command in claude_md_commands():
        if command.startswith("uv run"):
            assert re.search(rf"run: .*{re.escape(command)}", PR_CHECKS), (
                f"pr-checks.yml doesn't run {command}"
            )


def test_the_pull_request_template_and_the_docs_give_the_same_checks() -> None:
    for document in (
        REPO / ".github" / "PULL_REQUEST_TEMPLATE.md",
        REPO / "README.md",
        REPO / "CONTRIBUTING.md",
    ):
        text = document.read_text()
        for command in claude_md_commands():
            if command.startswith("uv run"):
                assert command in text, f"{document.relative_to(REPO)} doesn't give {command}"


def test_every_document_names_the_versions_the_workflows_use() -> None:
    pip_audit = workflow_version("dependency-audit.yml", "PIP_AUDIT_VERSION")
    for document in DOCUMENTS:
        text = document.read_text()
        name = document.relative_to(REPO)
        assert pinned("pip-audit", text) <= {pip_audit}, f"{name} names another pip-audit"


def test_each_workflow_spells_a_version_out_only_in_its_env() -> None:
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        steps = workflow.read_text().split("\njobs:\n", maxsplit=1)[1]
        assert not re.search(r"==[0-9]", steps), f"{workflow.name} pins a tool version outside env"


def test_the_tools_the_checks_need_are_development_dependencies() -> None:
    development = " ".join(PYPROJECT["dependency-groups"]["dev"])
    for tool in ("ruff", "mypy", "pytest", "pytest-cov"):
        assert re.search(rf"(^| ){re.escape(tool)}>=", development), f"{tool} is not a dev dependency"


def test_there_is_a_coverage_floor_and_it_measures_the_app() -> None:
    # A floor, not a target: CLAUDE.md says never to lower it.
    assert PYPROJECT["tool"]["coverage"]["report"]["fail_under"] >= 90
    assert "src" in PYPROJECT["tool"]["coverage"]["run"]["source"]


def test_the_python_version_is_the_same_everywhere() -> None:
    version = (REPO / ".python-version").read_text().strip()
    assert PYPROJECT["project"]["requires-python"] == f">={version},<3.{int(version.split('.')[1]) + 1}"
    assert PYPROJECT["tool"]["mypy"]["python_version"] == version
    assert PYPROJECT["tool"]["ruff"]["target-version"] == "py" + version.replace(".", "")


def test_the_checks_cover_every_python_folder() -> None:
    folders = {
        path.name
        for path in REPO.iterdir()
        if path.is_dir() and not path.name.startswith(".") and any(path.rglob("*.py"))
    }
    assert folders <= set(PYPROJECT["tool"]["mypy"]["files"]), "a folder of Python isn't type checked"
