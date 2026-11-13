"""Made-up test data, built in code.

The repository is public and `tests/repo/test_personal_data.py` fails on a literal email
address or phone number, so addresses are put together from parts here.
"""

from datetime import UTC, datetime

from asmbly_ceramics.domain.limits import SENDING_DOMAIN
from asmbly_ceramics.domain.studio import Studio, starting_studio

STAFF = "kiln-tech"
NOW = datetime(2026, 11, 13, 18, 30, tzinfo=UTC)


def an_address(local: str, domain: str = "example.org") -> str:
    return local + "@" + domain


def a_sending_address(local: str = "ceramics") -> str:
    return an_address(local, SENDING_DOMAIN)


def a_studio() -> Studio:
    studio, _ = starting_studio(a_sending_address(), NOW)
    return studio
