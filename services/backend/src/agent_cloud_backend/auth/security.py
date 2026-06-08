from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    # 坏/空哈希(如旧 dev 用户 server_default="")不抛,只返回 False。
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: str, *, secret: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(seconds=ttl_seconds)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str) -> str | None:
    """验签 + 验期;成功返回 sub(user_id),失败返回 None。"""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def new_refresh_token() -> tuple[str, str]:
    """返回 (明文 refresh, 其哈希)。明文只下发给客户端 cookie;库里只存哈希。"""
    plain = secrets.token_urlsafe(32)
    return plain, hash_refresh(plain)


def hash_refresh(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()
