"""`ReceivedSummary`: the ID page reads only the submission and shows no contact detail."""

import dataclasses
from datetime import timedelta

import pytest

from asmbly_ceramics.domain.ids import DropOffId
from asmbly_ceramics.domain.limits import SUBMISSION_LIFETIME
from asmbly_ceramics.ports.errors import RecordsUnavailable
from asmbly_ceramics.ports.records import Put, Submission
from asmbly_ceramics.use_cases.received import ReceivedView, SubmissionNotFound, received_view
from tests.domain.builders import NOW
from tests.use_cases.conftest import World

TOKEN = "made-up-submission-token-abcdefgh"


def store_submission(world: World, glaze_type: str | None = "House dip glaze") -> str:
    token_hash = world.hasher.submission(TOKEN)
    world.records.commit(
        [
            Put(
                Submission(
                    token_hash=token_hash,
                    drop_off_id=DropOffId(12),
                    pieces=3,
                    firing_type="Glaze",
                    glaze_type=glaze_type,
                    created_at=NOW,
                    expires_at=NOW + SUBMISSION_LIFETIME,
                )
            )
        ]
    )
    world.records.reads.clear()
    return token_hash


def test_received_view_has_no_contact_fields() -> None:
    assert [f.name for f in dataclasses.fields(ReceivedView)] == [
        "id",
        "pieces",
        "firing_type",
        "glaze_type",
        "created_at",
    ]


def test_received_summary_returns_the_submissions_summary(world: World) -> None:
    token_hash = store_submission(world)
    view = world.received(token_hash)
    assert view == ReceivedView(DropOffId(12), 3, "Glaze", "House dip glaze", NOW)
    stored = world.records.submission(token_hash)
    assert stored is not None
    assert received_view(stored) == view
    assert str(view.id) == "AC-12"


def test_received_summary_reads_only_the_submission(world: World) -> None:
    token_hash = store_submission(world)
    world.received(token_hash)
    assert world.records.reads == ["submission"]


def test_an_unknown_submission_raises_submission_not_found(world: World) -> None:
    store_submission(world)
    with pytest.raises(SubmissionNotFound) as raised:
        world.received(world.hasher.submission("another-made-up-token-0123"))
    assert raised.value.message == "That page has expired."


def test_a_value_that_isnt_a_submission_hash_is_not_looked_up(world: World) -> None:
    store_submission(world)
    for value in [TOKEN, "submission#" + "0" * 63, "device#" + "0" * 64, ""]:
        with pytest.raises(SubmissionNotFound):
            world.received(value)
    assert world.records.reads == []


def test_an_expired_submission_raises_submission_not_found(world: World) -> None:
    token_hash = store_submission(world, glaze_type=None)
    world.clock.advance(SUBMISSION_LIFETIME - timedelta(microseconds=1))
    assert world.received(token_hash).glaze_type is None
    world.clock.advance(timedelta(microseconds=1))  # exactly expires_at
    with pytest.raises(SubmissionNotFound):
        world.received(token_hash)


def test_records_unavailable_goes_up(world: World) -> None:
    token_hash = store_submission(world)
    world.records.fail_reads_with = RecordsUnavailable("InternalServerError")
    with pytest.raises(RecordsUnavailable):
        world.received(token_hash)
