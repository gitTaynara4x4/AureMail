from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class SecretCryptoError(RuntimeError):
    pass


def _get_fernet() -> Fernet:
    key = (os.getenv("AUREMAIL_CREDENTIALS_KEY", "") or "").strip()
    if not key:
        raise SecretCryptoError(
            "AUREMAIL_CREDENTIALS_KEY não configurada no .env."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise SecretCryptoError(
            "AUREMAIL_CREDENTIALS_KEY inválida. Gere uma chave Fernet válida."
        ) from exc


def encrypt_secret(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise SecretCryptoError("Não é possível criptografar um segredo vazio.")
    token = _get_fernet().encrypt(text.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        raise SecretCryptoError("Segredo criptografado ausente.")
    try:
        raw = _get_fernet().decrypt(text.encode("utf-8"))
        return raw.decode("utf-8")
    except InvalidToken as exc:
        raise SecretCryptoError("Não foi possível descriptografar o segredo.") from exc