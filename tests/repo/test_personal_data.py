"""No personal detail, photo or account number is committed to the repository.

The repository is public, and the app holds the contact details and photos of people
who drop off ceramics. CLAUDE.md says none of that is ever committed: not in code, test
data, docs or examples. Staff are referred to by username, drop-offs by ID (`AC-12`).
"""

import re

from tests.repo.files import REPO, repository_files

TEXT = ("*.md", "*.py", "*.yml", "*.yaml", "*.json", "*.toml", "*.sh", "*.txt", "*.html", "CODEOWNERS")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A North American phone number, written the usual ways (dashes, dots, spaces, brackets, +1).
PHONE = re.compile(r"(?<![\w.])(?:\+?1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}(?![\w.])")
# An AWS account ID is twelve digits. Nothing here needs one: a deploy will take it
# from the GitHub environment, not from a file.
ACCOUNT_ID = re.compile(r"(?<![\w.])\d{12}(?![\w.])")
IMAGES = ("*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.heic", "*.heif", "*.tif", "*.tiff", "*.bmp")
# Where the app's own artwork (the Asmbly logo) may live, once it has some.
ARTWORK = "branding"


def text_files() -> list[tuple[str, str]]:
    return [
        (path.relative_to(REPO).as_posix(), path.read_text())
        for pattern in TEXT
        for path in repository_files(pattern)
        if path.name != "uv.lock"
    ]


def matches(pattern: re.Pattern[str]) -> dict[str, list[str]]:
    """Each file that holds something `pattern` matches, with what it matched."""
    return {name: sorted(set(pattern.findall(text))) for name, text in text_files() if pattern.search(text)}


def test_no_file_holds_an_email_address() -> None:
    assert not matches(EMAIL)


def test_no_file_holds_a_phone_number() -> None:
    assert not matches(PHONE)


def test_no_file_holds_an_aws_account_id() -> None:
    assert not matches(ACCOUNT_ID)


def test_no_photo_is_committed() -> None:
    images = [
        path.relative_to(REPO).as_posix()
        for pattern in IMAGES
        for path in [*repository_files(pattern), *repository_files(pattern.upper())]
        if ARTWORK not in path.relative_to(REPO).parts
    ]
    assert not images, f"images outside {ARTWORK}/: {images}"


def test_the_patterns_catch_what_they_are_for() -> None:
    # The checks above pass on a clean repository whether or not the patterns work,
    # so each one is shown a made-up example here, built from pieces so that this
    # file doesn't hold one itself.
    assert EMAIL.search("write to " + "someone" + "@" + "example.org")
    assert PHONE.search("call 512-555-" + "0100")
    assert PHONE.search("call (512) 555 " + "0100")
    assert PHONE.search("call +1 512.555." + "0100")
    assert not PHONE.search("types-pyyaml>=6.0.12.20260906")
    assert ACCOUNT_ID.search("account 1234567" + "89012 in us-east-2")
    assert not ACCOUNT_ID.search("types-pyyaml>=6.0.12.20260906")
