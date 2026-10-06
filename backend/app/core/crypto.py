"""Sensitive value encryption helpers."""

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


class SecretCipherError(ValueError):
    """Raised when encrypted secret data cannot be processed."""


class SecretCipher:
    """AES-256-GCM cipher for reversible API key storage."""

    VERSION = "v1"

    def __init__(self) -> None:
        self.key_id = settings.AI_MODEL_CONFIG_ENCRYPTION_KEY_ID or "default"
        self.key = self._load_key()

    def encrypt(self, plaintext: str, aad: str) -> str:
        if not plaintext:
            raise SecretCipherError("待加密内容不能为空")

        nonce = os.urandom(12)
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        return ":".join(
            [
                self.VERSION,
                self.key_id,
                self._b64encode(nonce),
                self._b64encode(ciphertext),
            ]
        )

    def decrypt(self, token: str, aad: str) -> str:
        try:
            version, key_id, nonce_b64, ciphertext_b64 = token.split(":", maxsplit=3)
        except ValueError as exc:
            raise SecretCipherError("密钥密文格式不正确") from exc

        if version != self.VERSION:
            raise SecretCipherError("不支持的密钥密文版本")
        if key_id != self.key_id:
            raise SecretCipherError("密钥版本不匹配")

        try:
            plaintext = AESGCM(self.key).decrypt(
                self._b64decode(nonce_b64),
                self._b64decode(ciphertext_b64),
                aad.encode("utf-8"),
            )
        except (InvalidTag, ValueError) as exc:
            raise SecretCipherError("密钥密文校验失败") from exc

        return plaintext.decode("utf-8")

    @staticmethod
    def build_hint(secret: str) -> str | None:
        """Return a short non-sensitive display hint for a configured secret."""
        if not secret:
            return None
        if len(secret) <= 8:
            return "***"
        return f"{secret[:4]}...{secret[-4:]}"

    def _load_key(self) -> bytes:
        key_material = settings.AI_MODEL_CONFIG_ENCRYPTION_KEY.strip()
        if not key_material:
            if not settings.DEBUG:
                raise SecretCipherError("AI_MODEL_CONFIG_ENCRYPTION_KEY 环境变量必须设置")
            key_material = "debug-only-stockmate-ai-model-config-key"

        decoded = self._try_b64decode(key_material)
        if decoded and len(decoded) == 32:
            return decoded

        raw = key_material.encode("utf-8")
        if len(raw) == 32:
            return raw

        if settings.DEBUG:
            return hashlib.sha256(raw).digest()

        raise SecretCipherError("AI_MODEL_CONFIG_ENCRYPTION_KEY 必须是 32 字节明文或 base64 编码的 32 字节密钥")

    @staticmethod
    def _b64encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def _b64decode(data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))

    def _try_b64decode(self, data: str) -> bytes | None:
        try:
            return self._b64decode(data)
        except ValueError:
            return None
