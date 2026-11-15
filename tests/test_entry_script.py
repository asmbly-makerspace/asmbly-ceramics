"""`entry/run.sh`, what the Lambda Web Adapter starts: executable in git, the factory, no access log."""

import subprocess
from pathlib import Path

from tests.repo.files import REPO

RUN = REPO / "src" / "asmbly_ceramics" / "entry" / "run.sh"


def test_run_sh_is_executable_in_git() -> None:
    staged = subprocess.run(  # noqa: S603 (a fixed command)
        ["git", "ls-files", "-s", str(RUN.relative_to(REPO))],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert staged.startswith("100755 "), "run.sh must be committed with its executable bit"


def test_run_sh_starts_the_factory_without_an_access_log_or_proxy_headers() -> None:
    text = RUN.read_text()
    assert text.startswith("#!/bin/sh\n")
    command = " ".join(text.split("exec ", 1)[1].replace("\\\n", " ").split())
    assert command == (
        "python -m uvicorn asmbly_ceramics.web.app:create_from_environment --factory "
        '--host 0.0.0.0 --port "$PORT" --no-access-log --no-proxy-headers'
    )
    assert "web.local" not in text


def test_the_template_starts_it_through_the_web_adapter() -> None:
    template = (REPO / "infra" / "app.yaml").read_text()
    assert "Handler: asmbly_ceramics/entry/run.sh" in template
    assert Path(REPO / "src" / "asmbly_ceramics" / "entry" / "mailer.py").exists()
