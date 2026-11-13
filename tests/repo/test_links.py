"""Every relative link in the Markdown resolves, down to the heading it points at.

The documents send people and agents to each other ("read decision 0001", "follow
the runbook"). A link that leads nowhere is an instruction that can't be followed.
"""

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from tests.repo.files import REPO, markdown_files

FENCED = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def prose(text: str) -> str:
    """The text without code and comments, where a link is only an example."""
    return INLINE_CODE.sub("", FENCED.sub("", COMMENT.sub("", text)))


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces to hyphens."""
    text = heading.strip().lower().replace("`", "")
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(document: Path) -> set[str]:
    seen: dict[str, int] = {}
    found = set()
    for heading in HEADING.findall(FENCED.sub("", document.read_text())):
        base = slug(heading)
        count = seen.get(base, 0)
        found.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    return found


def relative_links(document: Path) -> list[str]:
    return [
        target
        for target in LINK.findall(prose(document.read_text()))
        if not re.match(r"^[a-z][a-z0-9+.-]*:", target)  # https:, mailto:
    ]


def test_there_is_markdown_to_check() -> None:
    names = {path.relative_to(REPO).as_posix() for path in markdown_files()}
    assert {"README.md", "CLAUDE.md", "CONTRIBUTING.md", "docs/README.md"} <= names


@pytest.mark.parametrize("document", markdown_files(), ids=lambda path: path.relative_to(REPO).as_posix())
def test_every_relative_link_resolves(document: Path) -> None:
    broken = []
    for target in relative_links(document):
        path_part, _, anchor = target.partition("#")
        destination = (document.parent / unquote(path_part)).resolve() if path_part else document
        if not destination.is_relative_to(REPO):
            broken.append(f"{target}: outside the repository")
        elif not destination.exists():
            broken.append(f"{target}: no such file")
        elif anchor and destination.suffix == ".md" and anchor not in anchors(destination):
            broken.append(f"{target}: no heading with that anchor")
    assert not broken, f"{document.relative_to(REPO)}: " + "; ".join(broken)


def test_the_slug_matches_githubs() -> None:
    assert slug("How changes reach production") == "how-changes-reach-production"
    assert slug("Who can merge to `main`") == "who-can-merge-to-main"
    assert slug("Step 2: Research what exists") == "step-2-research-what-exists"
