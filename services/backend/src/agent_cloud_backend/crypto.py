"""凭据加密:AES-256-GCM(随机 96-bit nonce,nonce 前置于密文)。主密钥来自 env
(base64 的 32 字节),接口 KMS-ready(后续把 encrypt/decrypt 换成 KMS 调用即可)。"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12


def load_credential_key(b64: str) -> bytes:
    """解码 env 里的 base64 主密钥,校验为 32 字节(AES-256)。"""
    if not b64:
        raise ValueError("credential key not configured (set AGENT_CLOUD_CREDENTIAL_KEY)")
    raw = base64.b64decode(b64)
    if len(raw) != 32:
        raise ValueError(f"credential key must be 32 bytes (got {len(raw)})")
    return raw


def encrypt(plain: str, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plain.encode(), None)
    return nonce + ct


def decrypt(blob: bytes, key: bytes) -> str:
    nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def mask(plain: str) -> str:
    """展示用掩码:前 3 + … + 后 4;太短(≤8)只显 …,绝不暴露明文。"""
    return f"{plain[:3]}…{plain[-4:]}" if len(plain) > 8 else "…"
