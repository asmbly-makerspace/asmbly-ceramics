"""Keyed hashes of the raw values the public form sends (decision 0002).

The use cases get the raw device cookie, source address and submission token from the
page and hash them here, so no raw value reaches `Records`, `RateLimiter` or a log.
Every output starts with its purpose's prefix, and the prefix is part of the HMAC's
input too, so one raw value hashed for two purposes gives two unrelated digests.
"""

import hashlib
import hmac
import ipaddress
import re

from asmbly_ceramics.ports.secrets import SecretName, Secrets

HASH_KEY_MIN_BYTES = 32
IPV6_NETWORK_PREFIX = 64  # one IPv6 caller usually holds a whole /64
_FORM_TOKEN = re.compile(r"[A-Za-z0-9_-]{22,64}", flags=re.ASCII)
SUBMISSION_PREFIX = "submission#"
_SUBMISSION_HASH = re.compile(re.escape(SUBMISSION_PREFIX) + r"[0-9a-f]{64}", flags=re.ASCII)


def is_form_token(value: str) -> bool:
    """22 to 64 of `[A-Za-z0-9_-]`: the shape of the form's submission token and of the
    device cookie (`secrets.token_urlsafe`). Anything else, a trailing newline included,
    is refused."""
    return isinstance(value, str) and _FORM_TOKEN.fullmatch(value) is not None


def is_submission_hash(value: str) -> bool:
    """`KeyHasher.submission`'s shape: `submission#` and 64 lowercase hex digits (an
    HMAC-SHA256), so no raw token, and no other purpose's hash, passes."""
    return isinstance(value, str) and _SUBMISSION_HASH.fullmatch(value) is not None


def _address_key(source_address: str) -> str:
    """What the address limit counts: an IPv4 address as itself (an IPv4-mapped IPv6
    address too), any other IPv6 address by its /64, other text as given."""
    try:
        address = ipaddress.ip_address(source_address.strip())
    except ValueError:
        return source_address
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, IPV6_NETWORK_PREFIX), strict=False))
    return str(address)


class KeyHasher:
    def __init__(self, secrets: Secrets) -> None:
        self._secrets = secrets
        self._key: bytes | None = None  # read once, on first use; a failed read isn't kept

    def device(self, cookie: str) -> str:
        return self._hash("device#", cookie)

    def address(self, source_address: str) -> str:
        return self._hash("address#", _address_key(source_address))

    def slots_device(self, cookie: str) -> str:
        return self._hash("slots-device#", cookie)

    def slots_address(self, source_address: str) -> str:
        return self._hash("slots-address#", _address_key(source_address))

    def submission(self, token: str) -> str:
        return self._hash(SUBMISSION_PREFIX, token)

    def _hash(self, prefix: str, value: str) -> str:
        digest = hmac.new(self._load_key(), (prefix + value).encode(), hashlib.sha256).hexdigest()
        return prefix + digest

    def _load_key(self) -> bytes:
        if self._key is None:
            key = self._secrets.get(SecretName.HASH_KEY)  # SecretMissing, SecretsUnavailable go up
            if len(key) < HASH_KEY_MIN_BYTES:
                raise ValueError("hash-key is too short")
            self._key = key
        return self._key
