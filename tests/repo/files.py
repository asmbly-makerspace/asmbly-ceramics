"""Where the repository's own files are, for the tests in this folder."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Folders that hold tools' output or other people's code, never the repository's own text.
SKIPPED = {".git", ".venv", ".mypy_cache", ".ruff_cache", ".pytest_cache", "node_modules", "worktrees"}


def repository_files(pattern: str) -> list[Path]:
    """Files under the repository matching `pattern`, outside tool and cache folders."""
    return sorted(
        path
        for path in REPO.rglob(pattern)
        if path.is_file() and not SKIPPED.intersection(path.relative_to(REPO).parts)
    )


def markdown_files() -> list[Path]:
    return repository_files("*.md")
