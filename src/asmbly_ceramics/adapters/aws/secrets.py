"""`Secrets` on SSM Parameter Store: SecureStrings `/asmbly-ceramics/<env>/<name>`.

Each value is 32 random bytes in base64, set by hand (`openssl rand -base64 32`, phase
5's runbook), decrypted by SSM with the AWS-managed key and cached in the process for 5
minutes. A value is never logged; a missing parameter is named, so a missed by-hand step
shows in the logs.
"""

import base64
import binascii
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from botocore.exceptions import BotoCoreError, ClientError

from asmbly_ceramics.adapters.aws.errors import aws_error_code, log_aws_error
from asmbly_ceramics.ports.errors import SecretMissing, SecretsUnavailable
from asmbly_ceramics.ports.secrets import SecretName

if TYPE_CHECKING:
    from mypy_boto3_ssm.client import SSMClient
else:
    SSMClient = Any

CACHE_SECONDS = 300
_ENV = re.compile(r"[a-z][a-z0-9]{0,15}", flags=re.ASCII)  # prod, stage


def parameter_name(env: str, name: SecretName) -> str:
    return f"/asmbly-ceramics/{env}/{name.value}"


class SsmSecrets:
    def __init__(self, client: SSMClient, env: str, clock: Callable[[], float] = time.monotonic) -> None:
        if _ENV.fullmatch(env) is None:
            raise ValueError("env is a short lowercase name: prod or stage")
        self._client = client
        self._env = env
        self._clock = clock
        self._cache: dict[SecretName, tuple[float, bytes]] = {}

    def get(self, name: SecretName) -> bytes:
        name = SecretName(name)
        cached = self._cache.get(name)
        now = self._clock()
        if cached is not None and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            response = self._client.get_parameter(Name=parameter_name(self._env, name), WithDecryption=True)
        except ClientError as error:
            if aws_error_code(error) == "ParameterNotFound":
                log_aws_error("get_parameter", error)
                raise SecretMissing(name.value) from None
            raise SecretsUnavailable(log_aws_error("get_parameter", error)) from None
        except BotoCoreError as error:
            raise SecretsUnavailable(log_aws_error("get_parameter", error)) from None
        try:
            # A value put from a file can end with a newline; nothing else is allowed.
            value = base64.b64decode(response["Parameter"]["Value"].strip(), validate=True)
        except KeyError, binascii.Error, ValueError:
            raise SecretsUnavailable("SecretNotBase64") from None
        if not value:
            raise SecretsUnavailable("SecretEmpty")
        self._cache[name] = (now, value)
        return value
