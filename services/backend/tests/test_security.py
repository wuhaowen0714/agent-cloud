import uuid

from agent_cloud_backend.auth import security


def test_password_hash_roundtrip():
    h = security.hash_password("hunter2")
    assert h != "hunter2"
    assert security.verify_password("hunter2", h) is True
    assert security.verify_password("wrong", h) is False


def test_verify_password_tolerates_garbage_hash():
    # 空/坏哈希(如旧 dev 用户的 server_default="")不应抛,只返回 False
    assert security.verify_password("anything", "") is False
    assert security.verify_password("anything", "not-a-hash") is False


def test_access_token_roundtrip():
    uid = str(uuid.uuid4())
    tok = security.create_access_token(uid, secret="s", ttl_seconds=60)
    assert security.decode_access_token(tok, secret="s") == uid


def test_access_token_expired_returns_none():
    tok = security.create_access_token("u", secret="s", ttl_seconds=-1)
    assert security.decode_access_token(tok, secret="s") is None


def test_access_token_bad_signature_returns_none():
    tok = security.create_access_token("u", secret="s", ttl_seconds=60)
    assert security.decode_access_token(tok, secret="other") is None


def test_decode_garbage_returns_none():
    assert security.decode_access_token("not.a.jwt", secret="s") is None


def test_refresh_token_gen_and_hash():
    plain, h = security.new_refresh_token()
    assert plain and h and h != plain
    assert security.hash_refresh(plain) == h
    # 两次生成不同
    assert security.new_refresh_token()[0] != plain
