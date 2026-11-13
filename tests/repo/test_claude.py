"""The skills, agents and settings in .claude/ are well formed and point at things that exist.

Claude Code reads a skill's name and description from its frontmatter to decide when to
use it, and spawns an agent by the name in its frontmatter. A typo there fails quietly:
the skill never triggers, or the agent is never found and the work is done inline.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.repo.files import REPO

CLAUDE = REPO / ".claude"
SKILLS = sorted((CLAUDE / "skills").glob("*/SKILL.md"))
AGENTS = sorted((CLAUDE / "agents").rglob("*.md"))
SKILL_KEYS = {"name", "description", "argument-hint", "model", "effort", "disable-model-invocation"}
AGENT_KEYS = {"name", "description", "tools", "model", "effort"}
# Skills from the repositories these were adapted from that this one doesn't have.
# A mention would send an agent to a step list that isn't there.
NOT_HERE = (
    "offshore",
    "build",
    "review",
    "bug-fix",
    "promote",
    "write-docs",
    "address-pr-comments",
    "add-tool",
    "add-server",
    "ops-check",
)


def frontmatter(path: Path) -> dict[str, Any] | None:
    text = path.read_text()
    if not text.startswith("---\n"):
        return None
    block = text.split("---\n", 2)[1]
    loaded = yaml.safe_load(block)
    assert isinstance(loaded, dict), f"{path.relative_to(REPO)}: frontmatter is not a mapping"
    return loaded


def spawned_agents() -> dict[str, Path]:
    """The agents a skill spawns by name: those whose file has frontmatter."""
    found: dict[str, Path] = {}
    for path in AGENTS:
        meta = frontmatter(path)
        if meta is not None:
            assert meta["name"] not in found, f"two agents are named {meta['name']}"
            found[meta["name"]] = path
    return found


def test_the_expected_skills_are_here() -> None:
    assert {path.parent.name for path in SKILLS} == {"plan-product", "plan-tech", "prep", "rigor", "ship"}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda path: path.parent.name)
def test_a_skills_frontmatter_names_it_and_says_when_to_use_it(skill: Path) -> None:
    meta = frontmatter(skill)
    assert meta is not None, "a skill starts with YAML frontmatter"
    assert set(meta) <= SKILL_KEYS, f"unknown keys: {set(meta) - SKILL_KEYS}"
    assert meta["name"] == skill.parent.name
    assert isinstance(meta["description"], str)
    assert 40 <= len(meta["description"]) <= 1024
    assert "Use when" in meta["description"] or "Use only when" in meta["description"]


@pytest.mark.parametrize("agent", AGENTS, ids=lambda path: path.relative_to(CLAUDE / "agents").as_posix())
def test_a_spawned_agents_frontmatter_is_complete(agent: Path) -> None:
    meta = frontmatter(agent)
    if meta is None:
        return  # adopted inline by a skill, not spawned
    assert set(meta) <= AGENT_KEYS, f"unknown keys: {set(meta) - AGENT_KEYS}"
    assert {"name", "description", "tools", "model"} <= set(meta)
    # Every spawned agent only reads: none of them may edit, write, or reach the network.
    assert set(re.split(r",\s*", meta["tools"])) <= {"Read", "Grep", "Glob", "Bash"}


def test_every_agent_a_skill_spawns_exists() -> None:
    agents = spawned_agents()
    for skill in SKILLS:
        for name in re.findall(r"subagent_type: ?`?([a-z-]+)", skill.read_text()):
            if name != "general-purpose":
                assert name in agents, f"{skill.parent.name} spawns {name}, which no agent file defines"


def test_every_file_a_skill_or_agent_names_exists() -> None:
    for document in [*SKILLS, *AGENTS]:
        for named in re.findall(r"`(\.claude/[^`*<>]+\.md)`", document.read_text()):
            assert (REPO / named).exists(), f"{document.relative_to(REPO)} names {named}, which doesn't exist"


def test_no_document_sends_anyone_to_a_skill_that_isnt_here() -> None:
    pattern = re.compile(rf"`/({'|'.join(NOT_HERE)})\b")
    documents = [*SKILLS, *AGENTS, REPO / "CLAUDE.md", REPO / "CONTRIBUTING.md", REPO / "README.md"]
    documents.append(REPO / ".implementation_plans" / "readme.md")
    for document in documents:
        found = pattern.findall(document.read_text())
        assert not found, (
            f"{document.relative_to(REPO)} mentions /{found[0]}, which this repository doesn't have"
        )


def test_the_settings_preapprove_only_checks_and_reads() -> None:
    settings = json.loads((CLAUDE / "settings.json").read_text())
    allowed = settings["permissions"]["allow"]
    read_only = re.compile(
        r"^Bash\(("
        r"uv sync|uv run (ruff|mypy|pytest)"
        r"|git (status|diff|log|show|rev-parse|ls-files|grep|merge-base|fetch origin)"
        r"|gh (pr (view|list|diff|checks)|run (list|view|watch)|issue (list|view))"
        r")( \*)?\)$"
    )
    for entry in allowed:
        assert read_only.match(entry), f"{entry} is not a check or a read-only command"
    # Anything that changes AWS, GitHub or the branch asks first.
    assert not [entry for entry in allowed if entry.startswith("Bash(aws")]
    assert "Bash(uv run pytest *)" in allowed
