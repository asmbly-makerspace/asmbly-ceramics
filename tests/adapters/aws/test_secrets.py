"""`SsmSecrets`, on `Stubber`."""

import base64
import logging

import pytest
from botocore.stub import Stubber

from asmbly_ceramics.adapters.aws.secrets import CACHE_SECONDS, SsmSecrets
from asmbly_ceramics.ports.errors import SecretMissing, SecretsUnavailable
from asmbly_ceramics.ports.secrets import SecretName
from tests.adapters.conftest import a_client, assert_nothing_holds

VALUE = bytes(range(32))
ENCODED = base64.b64encode(VALUE).decode()


def a_parameter(value: str = ENCODED) -> dict[str, object]:
    return {"Parameter": {"Name": "/asmbly-ceramics/stage/hash-key", "Type": "SecureString", "Value": value}}


def test_secret_is_read_with_decryption_and_cached(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="asmbly_ceramics")
    client = a_client("ssm")
    now = [1000.0]
    with Stubber(client) as stubber:
        for _ in range(2):
            stubber.add_response(
                "get_parameter",
                a_parameter(),
                {"Name": "/asmbly-ceramics/stage/hash-key", "WithDecryption": True},
            )
        secrets = SsmSecrets(client, "stage", clock=lambda: now[0])
        assert secrets.get(SecretName.HASH_KEY) == VALUE
        now[0] += CACHE_SECONDS - 1
        assert secrets.get(SecretName.HASH_KEY) == VALUE  # cached: one call so far
        now[0] += 2
        assert secrets.get(SecretName.HASH_KEY) == VALUE  # read again after 5 minutes
        stubber.assert_no_pending_responses()
    assert_nothing_holds(caplog.records, ENCODED)


def test_missing_parameter_names_it_without_a_value(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="asmbly_ceramics")
    client = a_client("ssm")
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "get_parameter", service_error_code="ParameterNotFound", http_status_code=400
        )
        with pytest.raises(SecretMissing) as raised:
            SsmSecrets(client, "prod").get(SecretName.SESSION_KEY)
    assert str(raised.value) == "secret session-key is not set"


@pytest.mark.parametrize("value", ["not base64!", "", "QUJD\n" + "=" * 3])
def test_a_value_that_isnt_base64_is_unavailable_without_naming_it(value: str) -> None:
    client = a_client("ssm")
    with Stubber(client) as stubber:
        stubber.add_response("get_parameter", a_parameter(value))
        with pytest.raises(SecretsUnavailable) as raised:
            SsmSecrets(client, "stage").get(SecretName.FORM_KEY)
    assert raised.value.code in ("SecretNotBase64", "SecretEmpty")


def test_an_outage_is_secrets_unavailable_with_the_code() -> None:
    client = a_client("ssm")
    with Stubber(client) as stubber:
        stubber.add_client_error("get_parameter", service_error_code="ThrottlingException")
        with pytest.raises(SecretsUnavailable) as raised:
            SsmSecrets(client, "stage").get(SecretName.FORM_KEY)
    assert raised.value.code == "ThrottlingException"


@pytest.mark.parametrize("env", ["", "Prod", "prod/../x", "a" * 17])
def test_env_is_a_short_lowercase_name(env: str) -> None:
    with pytest.raises(ValueError, match="env"):
        SsmSecrets(a_client("ssm"), env)


def test_a_trailing_newline_from_a_file_is_allowed() -> None:
    client = a_client("ssm")
    with Stubber(client) as stubber:
        stubber.add_response("get_parameter", a_parameter(ENCODED + "\n"))
        assert SsmSecrets(client, "stage").get(SecretName.FORM_KEY) == VALUE
