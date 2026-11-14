"""`KeyHasher` and `is_form_token`: no raw cookie, address or token gets past them."""

import pytest

from asmbly_ceramics.adapters.memory.secrets import MemorySecrets
from asmbly_ceramics.ports.errors import SecretMissing, SecretsUnavailable
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.use_cases.keys import KeyHasher, is_form_token, is_submission_hash

COOKIE = "made-up-device-cookie-0123456789"
TOKEN = "made-up-submission-token-abcdefgh"
ADDRESS = "203.0.113.7"  # TEST-NET-3, a documentation address


class CountingSecrets(MemorySecrets):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def get(self, name: SecretName) -> bytes:
        self.calls += 1
        return super().get(name)


class ShortSecrets(CountingSecrets):
    def __init__(self) -> None:
        super().__init__()
        self.short = True

    def get(self, name: SecretName) -> bytes:
        value = super().get(name)
        return value[:31] if self.short else value


def test_is_form_token_takes_22_to_64_url_safe_characters() -> None:
    assert is_form_token("a" * 22)
    assert is_form_token("A-z_9" * 12 + "abcd")  # 64
    assert not is_form_token("a" * 21)
    assert not is_form_token("a" * 65)
    assert not is_form_token("a" * 22 + "\n")
    assert not is_form_token("a" * 21 + "é")
    assert not is_form_token("a" * 21 + "=")
    assert not is_form_token("")
    assert not is_form_token(None)  # type: ignore[arg-type]  # a hostile caller can pass anything


def test_each_hash_has_its_prefix_and_differs_by_purpose() -> None:
    hasher = KeyHasher(MemorySecrets())
    hashes = {
        "device#": hasher.device(COOKIE),
        "slots-device#": hasher.slots_device(COOKIE),
        "address#": hasher.address(COOKIE),
        "slots-address#": hasher.slots_address(COOKIE),
        "submission#": hasher.submission(COOKIE),
    }
    for prefix, value in hashes.items():
        assert value.startswith(prefix)
        assert len(value) == len(prefix) + 64
    digests = {value.split("#", 1)[1] for value in hashes.values()}
    assert len(digests) == len(hashes)  # the prefix is in the HMAC's input, not only the output
    assert hasher.device(COOKIE) == hashes["device#"]  # stable
    assert hasher.device(COOKIE + "x") != hashes["device#"]


def test_is_submission_hash_takes_only_the_submission_hashs_shape() -> None:
    hasher = KeyHasher(MemorySecrets())
    assert is_submission_hash(hasher.submission(TOKEN))
    digest = hasher.submission(TOKEN).removeprefix("submission#")
    for other in [hasher.device(COOKIE), hasher.address(ADDRESS), hasher.slots_device(COOKIE)]:
        assert not is_submission_hash(other)
    for value in [
        TOKEN,
        digest,
        "submission#" + digest[:-1],
        "submission#" + digest.upper(),
        "submission#" + digest + "\n",
        "",
        None,
    ]:
        assert not is_submission_hash(value)  # type: ignore[arg-type]  # the page may pass anything


def test_hashes_hold_no_raw_value() -> None:
    hasher = KeyHasher(MemorySecrets())
    for raw, value in [
        (COOKIE, hasher.device(COOKIE)),
        (COOKIE, hasher.slots_device(COOKIE)),
        (ADDRESS, hasher.address(ADDRESS)),
        (ADDRESS, hasher.slots_address(ADDRESS)),
        (TOKEN, hasher.submission(TOKEN)),
    ]:
        assert raw not in value


def test_a_different_key_gives_different_hashes() -> None:
    other = MemorySecrets()
    other.set(SecretName.HASH_KEY, b"k" * 32)
    assert KeyHasher(other).device(COOKIE) != KeyHasher(MemorySecrets()).device(COOKIE)


def test_an_ipv6_address_hashes_by_its_64_network_and_a_mapped_ipv4_as_ipv4() -> None:
    hasher = KeyHasher(MemorySecrets())
    one = hasher.address("2001:db8:1:2::1")
    assert hasher.address("2001:db8:1:2:ffff:ffff:ffff:ffff") == one
    assert hasher.address("2001:DB8:1:2:0:0:0:abcd") == one
    assert hasher.address("2001:db8:1:3::1") != one
    assert hasher.slots_address("2001:db8:1:2::9") == hasher.slots_address("2001:db8:1:2::1")
    assert hasher.address("::ffff:203.0.113.7") == hasher.address(ADDRESS)
    assert hasher.address("203.0.113.8") != hasher.address(ADDRESS)
    assert hasher.address(" 203.0.113.7 ") == hasher.address(ADDRESS)
    assert hasher.address("not an address") != hasher.address("not an address either")


def test_the_key_is_read_once() -> None:
    secrets = CountingSecrets()
    hasher = KeyHasher(secrets)
    assert secrets.calls == 0  # lazily
    hasher.device(COOKIE)
    hasher.address(ADDRESS)
    hasher.submission(TOKEN)
    assert secrets.calls == 1


def test_a_missing_key_raises_and_is_not_cached() -> None:
    secrets = CountingSecrets()
    secrets.remove(SecretName.HASH_KEY)
    hasher = KeyHasher(secrets)
    with pytest.raises(SecretMissing):
        hasher.device(COOKIE)
    secrets.fail_with = SecretsUnavailable("ThrottlingException")
    with pytest.raises(SecretsUnavailable):
        hasher.device(COOKIE)
    secrets.fail_with = None
    secrets.set(SecretName.HASH_KEY, b"k" * 32)
    assert hasher.device(COOKIE).startswith("device#")
    assert secrets.calls == 3


def test_a_short_key_raises_and_is_not_cached() -> None:
    secrets = ShortSecrets()
    hasher = KeyHasher(secrets)
    with pytest.raises(ValueError, match="hash-key is too short"):
        hasher.device(COOKIE)
    secrets.short = False
    assert hasher.device(COOKIE).startswith("device#")
    assert secrets.calls == 2
