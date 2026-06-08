import base64

import pytest

from agent_cloud_backend.crypto import decrypt, encrypt, load_credential_key, mask

KEY = base64.b64encode(b"\x01" * 32).decode()


def test_encrypt_decrypt_roundtrip():
    k = load_credential_key(KEY)
    blob = encrypt("sk-secret-123", k)
    assert isinstance(blob, bytes) and blob != b"sk-secret-123"
    assert decrypt(blob, k) == "sk-secret-123"


def test_each_encrypt_uses_fresh_nonce():
    k = load_credential_key(KEY)
    assert encrypt("same", k) != encrypt("same", k)  # 随机 nonce → 密文不同


def test_decrypt_with_wrong_key_fails():
    k = load_credential_key(KEY)
    other = load_credential_key(base64.b64encode(b"\x02" * 32).decode())
    blob = encrypt("x", k)
    with pytest.raises(Exception):
        decrypt(blob, other)


def test_load_key_rejects_bad_length():
    with pytest.raises(ValueError):
        load_credential_key(base64.b64encode(b"short").decode())
    with pytest.raises(ValueError):
        load_credential_key("")


def test_mask_keeps_only_prefix_and_suffix():
    assert mask("sk-abcdefgh1234") == "sk-…1234"
    assert mask("short") == "…"  # 太短不暴露
