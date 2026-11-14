"""`SesMailer`'s request and its failures, on `Stubber`."""

import logging
from typing import Any

import pytest
from botocore.exceptions import ReadTimeoutError
from botocore.stub import Stubber

from asmbly_ceramics.adapters.aws.mailer import (
    MAX_ENCODED_BYTES,
    SES_CLIENT_CONFIG,
    SES_READ_TIMEOUT_SECONDS,
    TRIES,
    SesMailer,
    encoded_size,
)
from asmbly_ceramics.adapters.memory.mailer import MemoryMailer
from asmbly_ceramics.ports.mailer import REFUSED_CODES, InlineImage, Mailer, OutgoingEmail, SendFailed
from tests.adapters.conftest import a_client, assert_nothing_holds
from tests.domain.builders import TEST_EMAIL, TEST_NAME, a_sending_address, an_address

PHOTO = b"\xff\xd8\xff\xe0MADE-UP-PIXELS"
SUBJECT = "AC-12: we received your drop-off"
AWS_TEXT = "Email address is not verified: " + TEST_EMAIL


def an_email(**overrides: Any) -> OutgoingEmail:
    fields: dict[str, Any] = {
        "from_address": a_sending_address(),
        "from_name": "Asmbly Ceramics",
        "reply_to": a_sending_address(),
        "to": TEST_EMAIL,
        "subject": SUBJECT,
        "html": f'<p>Hello {TEST_NAME}</p><img src="cid:photo-1"><img src="cid:photo-2">',
        "text": f"Hello {TEST_NAME}",
        "inline": (
            InlineImage("photo-1", "AC-12-1.jpg", PHOTO),
            InlineImage("photo-2", "AC-12-2.jpg", PHOTO + b"2"),
        ),
    }
    fields.update(overrides)
    return OutgoingEmail(**fields)


def no_sleep(_: float) -> None:
    pass


def expected_request(message: OutgoingEmail) -> dict[str, Any]:
    return {
        "FromEmailAddress": f"Asmbly Ceramics <{message.from_address}>",
        "Destination": {"ToAddresses": [message.to]},
        "ReplyToAddresses": [message.reply_to],
        "Content": {
            "Simple": {
                "Subject": {"Data": SUBJECT, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": message.html, "Charset": "UTF-8"},
                    "Text": {"Data": message.text, "Charset": "UTF-8"},
                },
                "Attachments": [
                    {
                        "FileName": image.filename,
                        "RawContent": image.data,
                        "ContentDisposition": "INLINE",
                        "ContentId": image.content_id,
                        "ContentType": "image/jpeg",
                        "ContentTransferEncoding": "BASE64",
                    }
                    for image in message.inline
                ],
            }
        },
    }


def test_send_builds_simple_content_with_inline_attachments() -> None:
    client = a_client("sesv2")
    message = an_email()
    with Stubber(client) as stubber:
        stubber.add_response("send_email", {"MessageId": "made-up"}, expected_request(message))
        SesMailer(client).send(message)
    for image in message.inline:
        assert f"cid:{image.content_id}" in message.html


def test_from_has_display_name_and_reply_to_is_the_sender() -> None:
    client = a_client("sesv2")
    message = an_email(from_name='Asmbly "Ceramics", Austin')
    seen: list[dict[str, Any]] = []
    with Stubber(client) as stubber:
        stubber.add_response("send_email", {"MessageId": "made-up"})
        client.meta.events.register(
            "provide-client-params.sesv2.SendEmail", lambda params, **_: seen.append(params)
        )
        SesMailer(client).send(message)
    assert seen[0]["FromEmailAddress"] == f'"Asmbly \\"Ceramics\\", Austin" <{message.from_address}>'
    assert seen[0]["ReplyToAddresses"] == [a_sending_address()]


@pytest.mark.parametrize("field", ["from_address", "reply_to"])
def test_a_sender_outside_asmbly_org_is_refused_before_calling_ses(field: str) -> None:
    client = a_client("sesv2")
    with Stubber(client), pytest.raises(ValueError, match=r"asmbly\.org"):
        SesMailer(client).send(an_email(**{field: an_address("ceramics")}))


@pytest.mark.parametrize("code", sorted(REFUSED_CODES - {"MessageTooLarge"}))
def test_each_ses_error_code_becomes_send_failed_with_that_code(code: str) -> None:
    client = a_client("sesv2")
    with Stubber(client) as stubber:
        for _ in range(TRIES):  # a throttle is tried again; the rest are not
            stubber.add_client_error("send_email", service_error_code=code, service_message=AWS_TEXT)
        with pytest.raises(SendFailed) as raised:
            SesMailer(client, sleep=no_sleep).send(an_email())
    assert raised.value.code == code
    assert AWS_TEXT not in str(raised.value)


def test_a_throttle_is_retried_then_sent() -> None:
    client = a_client("sesv2")
    waits: list[float] = []
    with Stubber(client) as stubber:
        stubber.add_client_error("send_email", service_error_code="TooManyRequestsException")
        stubber.add_client_error("send_email", service_error_code="Throttling")
        stubber.add_response("send_email", {"MessageId": "made-up"})
        SesMailer(client, sleep=waits.append).send(an_email())
        stubber.assert_no_pending_responses()
    assert waits == [1.0, 2.0]


def test_message_rejected_is_not_retried() -> None:
    client = a_client("sesv2")
    with Stubber(client) as stubber:
        stubber.add_client_error("send_email", service_error_code="MessageRejected")
        with pytest.raises(SendFailed, match="MessageRejected"):
            SesMailer(client, sleep=no_sleep).send(an_email())
        stubber.assert_no_pending_responses()


def test_a_refusal_after_botocores_retries_is_unknown() -> None:
    # An earlier try may have timed out after SES took the message: not a refused code.
    client = a_client("sesv2")
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "send_email", service_error_code="MessageRejected", response_meta={"RetryAttempts": 1}
        )
        with pytest.raises(SendFailed) as raised:
            SesMailer(client).send(an_email())
    assert raised.value.code == "unknown"
    assert raised.value.code not in REFUSED_CODES


def test_a_timeout_may_have_sent_so_its_code_is_not_a_refusal() -> None:
    client = a_client("sesv2")

    def time_out(**_: Any) -> None:
        raise ReadTimeoutError(endpoint_url="https://email.us-east-2.amazonaws.com")

    client.meta.events.register("before-send.sesv2.SendEmail", time_out)
    with pytest.raises(SendFailed) as raised:
        SesMailer(client).send(an_email())
    assert raised.value.code == "ReadTimeoutError"
    assert raised.value.code not in REFUSED_CODES


def test_the_client_config_makes_one_attempt() -> None:
    assert vars(SES_CLIENT_CONFIG)["retries"] == {"total_max_attempts": 1, "mode": "standard"}
    assert vars(SES_CLIENT_CONFIG)["read_timeout"] == SES_READ_TIMEOUT_SECONDS


def test_oversized_message_is_refused_before_calling_ses() -> None:
    client = a_client("sesv2")
    big = InlineImage("photo-1", "AC-12-1.jpg", b"x" * (MAX_ENCODED_BYTES * 3 // 4 + 3))
    message = an_email(inline=(big,))
    assert encoded_size(message) > MAX_ENCODED_BYTES
    with Stubber(client), pytest.raises(SendFailed, match="MessageTooLarge"):
        SesMailer(client).send(message)
    assert "MessageTooLarge" in REFUSED_CODES  # certainly not sent


def test_six_full_photos_fit() -> None:
    photos = tuple(InlineImage(f"photo-{n}", f"AC-12-{n}.jpg", b"x" * 1_500_000) for n in range(1, 7))
    assert encoded_size(an_email(inline=photos)) < MAX_ENCODED_BYTES


def test_nothing_logged_holds_the_address_subject_or_body(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="asmbly_ceramics")
    client = a_client("sesv2")
    with Stubber(client) as stubber:
        stubber.add_client_error("send_email", service_error_code="MessageRejected", service_message=AWS_TEXT)
        with pytest.raises(SendFailed):
            SesMailer(client).send(an_email())
    [record] = caplog.records
    assert (vars(record)["kind"], vars(record)["error_code"]) == ("send_email", "MessageRejected")
    assert_nothing_holds(caplog.records, TEST_EMAIL, TEST_NAME, SUBJECT, AWS_TEXT, a_sending_address())


@pytest.mark.parametrize("which", ["fake", "adapter"])
def test_mailer_sends_one_message(which: str) -> None:
    # The contract: one send of the message, or `SendFailed`; the fake records it, the
    # adapter makes one `send_email` call.
    message = an_email()
    if which == "fake":
        fake = MemoryMailer()
        mailer: Mailer = fake
        mailer.send(message)
        assert fake.sent == [message]
        return
    client = a_client("sesv2")
    with Stubber(client) as stubber:
        stubber.add_response("send_email", {"MessageId": "made-up"}, expected_request(message))
        SesMailer(client).send(message)
        stubber.assert_no_pending_responses()


def test_a_recipient_that_isnt_one_address_is_refused_before_calling_ses() -> None:
    client = a_client("sesv2")
    two = TEST_EMAIL + ", " + an_address("someone.else")
    with Stubber(client), pytest.raises(ValueError, match="recipient"):
        SesMailer(client).send(an_email(to=two))


@pytest.mark.parametrize(
    "overrides",
    [{"reply_to": an_address("ceramics")}, {"to": "not an address"}, {"from_address": an_address("x")}],
)
def test_the_fake_and_the_adapter_refuse_the_same_messages(overrides: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"asmbly\.org|recipient"):
        MemoryMailer().send(an_email(**overrides))
    client = a_client("sesv2")
    with Stubber(client), pytest.raises(ValueError, match=r"asmbly\.org|recipient"):
        SesMailer(client).send(an_email(**overrides))
