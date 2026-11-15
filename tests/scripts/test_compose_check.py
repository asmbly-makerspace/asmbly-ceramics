"""`scripts/compose_check.py`, run as the deploy runs it, on copies of the package."""

import shutil
import subprocess
import sys
from pathlib import Path

from tests.repo.files import REPO

SCRIPT = REPO / "scripts" / "compose_check.py"
PACKAGE = REPO / "src" / "asmbly_ceramics"


def run(build_dir: Path) -> subprocess.CompletedProcess[str]:
    # -I: no current directory or PYTHONPATH on sys.path, as on the runner.
    return subprocess.run(  # noqa: S603 (a fixed command)
        [sys.executable, "-I", str(SCRIPT), str(build_dir)], capture_output=True, text=True, check=False
    )


def built(tmp_path: Path) -> Path:
    shutil.copytree(PACKAGE, tmp_path / "asmbly_ceramics", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def test_it_passes_on_a_directory_holding_the_package(tmp_path: Path) -> None:
    result = run(built(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "compose check passed: received, ready, rejected, test\n"


def test_it_fails_naming_the_template_when_one_is_missing(tmp_path: Path) -> None:
    build_dir = built(tmp_path)
    (build_dir / "asmbly_ceramics" / "mail" / "templates" / "ready.html").unlink()
    result = run(build_dir)
    assert result.returncode == 1
    assert result.stderr == "compose check failed: ready: TemplateNotFound (ready.html)\n"


def test_it_never_falls_back_to_the_installed_package(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.returncode == 1
    assert "holds no asmbly_ceramics.mail.compose" in result.stderr


def test_it_prints_no_body(tmp_path: Path) -> None:
    result = run(built(tmp_path))
    assert "Made Up Person" not in result.stdout + result.stderr
    assert "example.org" not in result.stdout + result.stderr


def test_it_needs_a_directory() -> None:
    result = subprocess.run(  # noqa: S603 (a fixed command)
        [sys.executable, "-I", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
