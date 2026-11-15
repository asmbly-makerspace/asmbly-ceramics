"""Checks that a built function holds the email templates: composes every email from it.

    python3 scripts/compose_check.py .aws-sam/build/MailerFunction

The functions deploy from `sam build` of `src/`, not from the wheel phase 2c checked, so
this proves the built artefact can compose `received`, `ready`, `rejected` and `test`.
It puts the build directory first on `sys.path`, refuses a package loaded from anywhere
else (it never falls back to the installed one), composes each email from made-up data
(names built in code, `example.org` addresses), and exits 1 naming the email and its
template if one fails. It prints no body and sends nothing.
"""

import importlib
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KINDS = ("received", "ready", "rejected", "test")


class CheckError(Exception):
    pass


def load_package(build_dir: Path) -> None:
    if not (build_dir / "asmbly_ceramics" / "mail" / "compose.py").is_file():
        raise CheckError(f"{build_dir} holds no asmbly_ceramics.mail.compose")
    for name in [
        name for name in sys.modules if name == "asmbly_ceramics" or name.startswith("asmbly_ceramics.")
    ]:
        del sys.modules[name]
    sys.path.insert(0, str(build_dir))
    compose = importlib.import_module("asmbly_ceramics.mail.compose")
    loaded = Path(compose.__file__ or "").resolve()
    if not loaded.is_relative_to(build_dir.resolve()):
        raise CheckError(f"asmbly_ceramics.mail.compose loaded from outside {build_dir}")


def emails() -> dict[str, Any]:
    """Each email's composer call, on made-up data, from the package just loaded."""
    compose = importlib.import_module("asmbly_ceramics.mail.compose")
    dropoff = importlib.import_module("asmbly_ceramics.domain.dropoff")
    ids = importlib.import_module("asmbly_ceramics.domain.ids")
    limits = importlib.import_module("asmbly_ceramics.domain.limits")
    photos = importlib.import_module("asmbly_ceramics.domain.photos")
    studio_module = importlib.import_module("asmbly_ceramics.domain.studio")
    composer_port = importlib.import_module("asmbly_ceramics.ports.composer")

    now = datetime(2026, 11, 13, 18, 30, tzinfo=UTC)
    studio, _ = studio_module.starting_studio("ceramics" + "@" + limits.SENDING_DOMAIN, now)
    drop_off_id = ids.DropOffId(1)
    details = dropoff.DropOffDetails.create(
        name="Made Up Person",
        email="made.up" + "@" + "example.org",
        phone=" ".join(["(512)", "555", "01" + "00"]),
        pieces="2",
        firing_type="bisque",
        glaze_type=None,
        photo_count=2,
        studio=studio,
    )
    refs = tuple(photos.PhotoRef(drop_off_id, index) for index in (1, 2))
    waiting = dropoff.new_drop_off(drop_off_id, details, refs, now)
    reason = studio.reasons[0].id
    rejected = replace(
        waiting,
        state=dropoff.DropOffState.REJECTED,
        rejection=dropoff.Rejection(reason, "Made-up message.", "kiln-tech", now),
    )
    composer = compose.JinjaComposer()
    cid = composer_port.cid
    return {
        "received": lambda: composer.received(waiting, studio, cid),
        "ready": lambda: composer.ready(waiting, studio, now, cid),
        "rejected": lambda: composer.rejected(rejected, studio, cid),
        "test": lambda: composer.test(studio),
    }


def check(build_dir: Path) -> list[str]:
    load_package(build_dir)
    failures = []
    for kind, compose_one in emails().items():
        try:
            email = compose_one()
            if not email.subject or not email.html or not email.text:
                raise CheckError("an empty part")
        except Exception as error:  # by class and template name only, never the text
            template = getattr(error, "name", None) or f"{kind}.html / {kind}.txt"
            failures.append(f"{kind}: {type(error).__name__} ({template})")
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: compose_check.py <built function directory>", file=sys.stderr)
        return 2
    try:
        failures = check(Path(argv[0]))
    except CheckError as error:
        print(f"compose check failed: {error}", file=sys.stderr)
        return 1
    for failure in failures:
        print(f"compose check failed: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("compose check passed: " + ", ".join(KINDS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
