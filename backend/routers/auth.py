import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import UsuarioPlataforma


def _get_required_env(name: str) -> str:
    value = (os.getenv(name, "") or "").strip()
    if not value:
        raise RuntimeError(f"{name} não configurada no .env.")
    return value


def _get_cookie_max_age() -> int:
    raw = (os.getenv("AUREMAIL_COOKIE_MAX_AGE", "") or "").strip()
    if not raw:
        return 60 * 60 * 24 * 7

    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("AUREMAIL_COOKIE_MAX_AGE inválido no .env.") from exc

    if value <= 0:
        raise RuntimeError("AUREMAIL_COOKIE_MAX_AGE deve ser maior que zero.")

    return value


def _get_cookie_samesite() -> str:
    value = (os.getenv("AUREMAIL_COOKIE_SAMESITE", "lax") or "lax").strip().lower()
    allowed = {"lax", "strict", "none"}

    if value not in allowed:
        raise RuntimeError(
            "AUREMAIL_COOKIE_SAMESITE inválido no .env. Use: lax, strict ou none."
        )

    return value


SECRET_KEY = _get_required_env("AUREMAIL_SECRET_KEY")
COOKIE_NAME = (os.getenv("AUREMAIL_COOKIE_NAME", "auremail_session") or "auremail_session").strip()
COOKIE_MAX_AGE = _get_cookie_max_age()
COOKIE_SECURE = (os.getenv("AUREMAIL_COOKIE_SECURE", "false") or "false").strip().lower() == "true"
COOKIE_SAMESITE = _get_cookie_samesite()

SHORT_SESSION_MAX_AGE = 60 * 60 * 12


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(password: str, iterations: int = 120_000) -> str:
    password = password or ""
    if not password.strip():
        raise ValueError("Senha inválida.")

    if iterations <= 0:
        raise ValueError("Número de iterações inválido.")

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()

    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        if not password or not stored_hash:
            return False

        algorithm, iterations_str, salt, digest = stored_hash.split("$", 3)

        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations_str)
        if iterations <= 0:
            return False

        computed = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()

        return hmac.compare_digest(computed, digest)
    except Exception:
        return False


def build_session_token(user: UsuarioPlataforma, max_age: int) -> str:
    now = int(time.time())

    payload = {
        "user_id": int(user.id),
        "empresa_id": int(user.empresa_id),
        "email": normalize_email(user.email),
        "name": (user.name or "").strip(),
        "iat": now,
        "exp": now + int(max_age),
        "type": "panel_session",
    }

    payload_bytes = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    payload_b64 = _b64url_encode(payload_bytes)

    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    signature_b64 = _b64url_encode(signature)
    return f"{payload_b64}.{signature_b64}"


def decode_session_token(token: str) -> Optional[dict[str, Any]]:
    try:
        if not token or "." not in token:
            return None

        payload_b64, signature_b64 = token.split(".", 1)

        expected_signature = hmac.new(
            SECRET_KEY.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        provided_signature = _b64url_decode(signature_b64)

        if not hmac.compare_digest(expected_signature, provided_signature):
            return None

        payload_raw = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_raw)

        exp = payload.get("exp")
        if exp is None or int(exp) < int(time.time()):
            return None

        if payload.get("type") != "panel_session":
            return None

        return payload
    except Exception:
        return None


def set_login_cookie(
    response: Response,
    user: UsuarioPlataforma,
    remember: bool = False,
) -> None:
    max_age = COOKIE_MAX_AGE if remember else SHORT_SESSION_MAX_AGE
    token = build_session_token(user, max_age=max_age)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_login_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
    )


def get_session_payload(request: Request) -> Optional[dict[str, Any]]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return decode_session_token(token)


def is_authenticated(request: Request) -> bool:
    payload = get_session_payload(request)
    return bool(payload and payload.get("user_id") and payload.get("email"))


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UsuarioPlataforma:
    payload = get_session_payload(request)

    if not payload:
        raise HTTPException(status_code=401, detail="Sessão inválida ou ausente.")

    user_id = payload.get("user_id")
    email = normalize_email(payload.get("email", ""))

    if not user_id or not email:
        raise HTTPException(status_code=401, detail="Sessão inválida.")

    user = (
        db.query(UsuarioPlataforma)
        .filter(
            UsuarioPlataforma.id == user_id,
            UsuarioPlataforma.email == email,
            UsuarioPlataforma.is_active.is_(True),
        )
        .first()
    )

    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado ou inativo.")

    return user


def get_current_user_optional(
    request: Request,
    db: Session,
) -> Optional[UsuarioPlataforma]:
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None