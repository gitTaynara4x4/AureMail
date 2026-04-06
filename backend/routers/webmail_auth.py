from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import CaixaEmail, Dominio, Empresa, UsuarioPlataforma
from backend.routers.auth import (
    get_current_user_optional,
    normalize_email,
    verify_password,
)

SECRET_KEY = os.getenv("AUREMAIL_SECRET_KEY", "troque-essa-chave-em-producao")
COOKIE_SECURE = os.getenv("AUREMAIL_COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("AUREMAIL_COOKIE_SAMESITE", "lax")
WEBMAIL_COOKIE_NAME = os.getenv("AUREMAIL_WEBMAIL_COOKIE_NAME", "auremail_webmail_session")
WEBMAIL_COOKIE_MAX_AGE = int(
    os.getenv("AUREMAIL_WEBMAIL_COOKIE_MAX_AGE", str(60 * 60 * 24 * 7))
)

router = APIRouter(prefix="/api/webmail-auth", tags=["Webmail Auth"])


class WebmailActor(TypedDict):
    kind: str
    empresa_id: int
    platform_user: UsuarioPlataforma | None
    mailbox: CaixaEmail | None


class WebmailLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=255)
    remember: bool = False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def serialize_mailbox(mailbox: CaixaEmail) -> dict:
    return {
        "id": mailbox.id,
        "empresa_id": mailbox.empresa_id,
        "dominio_id": mailbox.dominio_id,
        "email": mailbox.email,
        "display_name": mailbox.display_name,
        "local_part": mailbox.local_part,
        "quota_mb": mailbox.quota_mb,
        "is_active": bool(mailbox.is_active),
        "domain": mailbox.dominio.name if mailbox.dominio else None,
        "account_type": "mailbox_user",
    }


def build_webmail_session_token(mailbox: CaixaEmail, max_age: int) -> str:
    now = int(time.time())

    payload = {
        "mailbox_id": mailbox.id,
        "empresa_id": mailbox.empresa_id,
        "email": mailbox.email,
        "iat": now,
        "exp": now + int(max_age),
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


def decode_webmail_session_token(token: str) -> Optional[dict]:
    try:
        payload_b64, signature_b64 = token.split(".", 1)

        expected_signature = hmac.new(
            SECRET_KEY.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        provided_signature = _b64url_decode(signature_b64)

        if not hmac.compare_digest(expected_signature, provided_signature):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))

        exp = payload.get("exp")
        if exp is not None and int(exp) < int(time.time()):
            return None

        return payload
    except Exception:
        return None


def set_webmail_login_cookie(
    response: Response,
    mailbox: CaixaEmail,
    remember: bool = False,
) -> None:
    max_age = WEBMAIL_COOKIE_MAX_AGE if remember else 60 * 60 * 12
    token = build_webmail_session_token(mailbox, max_age=max_age)

    response.set_cookie(
        key=WEBMAIL_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_webmail_login_cookie(response: Response) -> None:
    response.delete_cookie(
        key=WEBMAIL_COOKIE_NAME,
        path="/",
    )


def get_webmail_session_payload(request: Request) -> Optional[dict]:
    token = request.cookies.get(WEBMAIL_COOKIE_NAME)
    if not token:
        return None
    return decode_webmail_session_token(token)


def is_webmail_authenticated(request: Request) -> bool:
    payload = get_webmail_session_payload(request)
    return bool(payload and payload.get("mailbox_id") and payload.get("email"))


def get_company(db: Session, empresa_id: int) -> Empresa | None:
    return (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id)
        .first()
    )


def get_primary_domain(db: Session, empresa_id: int) -> str | None:
    primary = (
        db.query(Dominio)
        .filter(
            Dominio.empresa_id == empresa_id,
            Dominio.is_primary.is_(True),
        )
        .first()
    )
    if primary:
        return primary.name

    fallback = (
        db.query(Dominio)
        .filter(Dominio.empresa_id == empresa_id)
        .first()
    )
    return fallback.name if fallback else None


def get_current_webmail_mailbox(
    request: Request,
    db: Session = Depends(get_db),
) -> CaixaEmail:
    payload = get_webmail_session_payload(request)
    if not payload:
        raise HTTPException(status_code=401, detail="Sessão do webmail inválida ou ausente.")

    mailbox_id = payload.get("mailbox_id")
    email = normalize_email(payload.get("email", ""))

    if not mailbox_id or not email:
        raise HTTPException(status_code=401, detail="Sessão do webmail inválida.")

    mailbox = (
        db.query(CaixaEmail)
        .options(joinedload(CaixaEmail.dominio))
        .filter(
            CaixaEmail.id == mailbox_id,
            CaixaEmail.email == email,
            CaixaEmail.is_active.is_(True),
        )
        .first()
    )

    if not mailbox:
        raise HTTPException(status_code=401, detail="Caixa não encontrada ou inativa.")

    empresa = get_company(db, mailbox.empresa_id)
    if not empresa or (empresa.status or "").lower() != "active":
        raise HTTPException(status_code=403, detail="A empresa vinculada está inativa.")

    return mailbox


def get_current_webmail_mailbox_optional(
    request: Request,
    db: Session,
) -> CaixaEmail | None:
    try:
        return get_current_webmail_mailbox(request, db)
    except HTTPException:
        return None


def get_current_mail_actor(
    request: Request,
    db: Session = Depends(get_db),
) -> WebmailActor:
    platform_user = get_current_user_optional(request, db)
    if platform_user:
        return WebmailActor(
            kind="platform_user",
            empresa_id=int(platform_user.empresa_id),
            platform_user=platform_user,
            mailbox=None,
        )

    mailbox = get_current_webmail_mailbox_optional(request, db)
    if mailbox:
        return WebmailActor(
            kind="mailbox_user",
            empresa_id=int(mailbox.empresa_id),
            platform_user=None,
            mailbox=mailbox,
        )

    raise HTTPException(status_code=401, detail="Acesso ao webmail não autorizado.")


@router.post("/login")
def login_webmail(
    data: WebmailLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    email = normalize_email(data.email)
    password = data.password or ""

    mailbox = (
        db.query(CaixaEmail)
        .options(joinedload(CaixaEmail.dominio))
        .filter(CaixaEmail.email == email)
        .first()
    )

    if not mailbox:
        raise HTTPException(status_code=401, detail="E-mail da caixa ou senha inválidos.")

    if not mailbox.is_active:
        raise HTTPException(status_code=403, detail="Essa caixa de e-mail está inativa.")

    empresa = get_company(db, mailbox.empresa_id)
    if not empresa:
        raise HTTPException(status_code=401, detail="Empresa vinculada não encontrada.")

    if (empresa.status or "").lower() != "active":
        raise HTTPException(status_code=403, detail="A empresa está inativa.")

    if not verify_password(password, mailbox.password_hash):
        raise HTTPException(status_code=401, detail="E-mail da caixa ou senha inválidos.")

    set_webmail_login_cookie(response, mailbox, remember=data.remember)

    return {
        "success": True,
        "message": "Login do webmail realizado com sucesso.",
        "mailbox": serialize_mailbox(mailbox),
        "company": {
            "id": empresa.id,
            "name": empresa.name,
            "status": empresa.status,
        },
    }


@router.post("/logout")
def logout_webmail(response: Response):
    clear_webmail_login_cookie(response)
    return {
        "success": True,
        "message": "Logout do webmail realizado com sucesso.",
    }


@router.get("/me")
def webmail_me(
    mailbox: CaixaEmail = Depends(get_current_webmail_mailbox),
    db: Session = Depends(get_db),
):
    empresa = get_company(db, mailbox.empresa_id)
    domain = mailbox.dominio.name if mailbox.dominio else get_primary_domain(db, mailbox.empresa_id)

    return {
        "success": True,
        "user": {
            "id": mailbox.id,
            "empresa_id": mailbox.empresa_id,
            "name": mailbox.display_name or mailbox.local_part,
            "email": mailbox.email,
            "is_owner": False,
            "is_active": bool(mailbox.is_active),
            "account_type": "mailbox_user",
        },
        "company": {
            "id": empresa.id if empresa else None,
            "name": empresa.name if empresa else None,
            "status": empresa.status if empresa else None,
        },
        "mailbox": {
            "id": mailbox.id,
            "empresa_id": mailbox.empresa_id,
            "dominio_id": mailbox.dominio_id,
            "email": mailbox.email,
            "display_name": mailbox.display_name,
            "local_part": mailbox.local_part,
            "quota_mb": mailbox.quota_mb,
            "is_active": bool(mailbox.is_active),
            "domain": domain,
            "account_type": "mailbox_user",
        },
    }