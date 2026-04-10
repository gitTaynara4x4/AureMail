from __future__ import annotations

import logging
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.integrations.stalwart_client import (
    StalwartProvisioningError,
    get_stalwart_client,
)
from backend.models import CaixaEmail, Dominio, Pasta, UsuarioPlataforma
from backend.routers.auth import get_current_user, hash_password
from backend.utils.crypto import SecretCryptoError, encrypt_secret


router = APIRouter(prefix="/api/caixas-email", tags=["Caixas de e-mail"])
logger = logging.getLogger("auremail.caixas_email")

LOCAL_PART_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,118}[a-z0-9])?$")
DEFAULT_FOLDERS = (
    ("Caixa de entrada", "inbox"),
    ("Enviados", "sent"),
    ("Rascunhos", "drafts"),
    ("Lixeira", "trash"),
)


class MailboxCreateRequest(BaseModel):
    dominio_id: int
    local_part: str = Field(..., min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=150)
    password: str | None = Field(default=None, min_length=8, max_length=255)
    quota_mb: int = Field(default=2048, ge=128, le=102400)
    is_active: bool = True
    is_admin: bool = False


class MailboxUpdateRequest(BaseModel):
    dominio_id: int | None = None
    local_part: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=150)
    quota_mb: int | None = Field(default=None, ge=128, le=102400)
    is_active: bool | None = None
    is_admin: bool | None = None


class MailboxPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=255)


def normalize_local_part(value: str) -> str:
    local = (value or "").strip().lower()
    return re.sub(r"\s+", "", local)


def validate_local_part(value: str) -> bool:
    return bool(LOCAL_PART_REGEX.match(normalize_local_part(value)))


def normalize_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text[:150] if text else None


def build_mailbox_password(raw_password: str | None = None) -> tuple[str, str]:
    password = raw_password or secrets.token_urlsafe(12)
    return password, hash_password(password)


def serialize_mailbox(mailbox: CaixaEmail) -> dict:
    domain_name = mailbox.dominio.name if mailbox.dominio else None
    return {
        "id": int(mailbox.id),
        "empresa_id": int(mailbox.empresa_id),
        "dominio_id": int(mailbox.dominio_id),
        "domain_name": domain_name,
        "local_part": mailbox.local_part,
        "email": mailbox.email,
        "display_name": mailbox.display_name,
        "quota_mb": mailbox.quota_mb,
        "is_admin": bool(mailbox.is_admin),
        "is_active": bool(mailbox.is_active),
        "created_at": mailbox.created_at.isoformat() if mailbox.created_at else None,
        "updated_at": mailbox.updated_at.isoformat() if mailbox.updated_at else None,
    }


def get_client_debug_snapshot(client) -> dict:
    return {
        "enabled": bool(getattr(client, "enabled", False)),
        "base_url": getattr(client, "base_url", None),
        "verify_ssl": getattr(client, "verify_ssl", None),
        "timeout": getattr(client, "timeout", None),
        "auth_mode": getattr(client, "auth_mode", None),
        "default_role": getattr(client, "default_role", None),
    }


def get_domain_for_user(db: Session, domain_id: int, empresa_id: int) -> Dominio:
    domain = (
        db.query(Dominio)
        .filter(
            Dominio.id == domain_id,
            Dominio.empresa_id == empresa_id,
        )
        .first()
    )
    if not domain:
        logger.warning(
            "Domínio não encontrado para usuário | domain_id=%s | empresa_id=%s",
            domain_id,
            empresa_id,
        )
        raise HTTPException(status_code=404, detail="Domínio não encontrado.")
    return domain


def get_mailbox_for_user(db: Session, mailbox_id: int, empresa_id: int) -> CaixaEmail:
    mailbox = (
        db.query(CaixaEmail)
        .options(joinedload(CaixaEmail.dominio))
        .filter(
            CaixaEmail.id == mailbox_id,
            CaixaEmail.empresa_id == empresa_id,
        )
        .first()
    )
    if not mailbox:
        logger.warning(
            "Caixa não encontrada para usuário | mailbox_id=%s | empresa_id=%s",
            mailbox_id,
            empresa_id,
        )
        raise HTTPException(status_code=404, detail="Caixa de e-mail não encontrada.")
    return mailbox


def get_mailbox_by_email_for_company(
    db: Session,
    empresa_id: int,
    email: str,
    except_id: int | None = None,
) -> CaixaEmail | None:
    query = db.query(CaixaEmail).filter(
        CaixaEmail.empresa_id == empresa_id,
        CaixaEmail.email == email,
    )

    if except_id is not None:
        query = query.filter(CaixaEmail.id != except_id)

    return query.first()


def ensure_default_folders(db: Session, mailbox: CaixaEmail) -> None:
    existing = {
        row[0]
        for row in db.query(Pasta.slug)
        .filter(Pasta.caixa_email_id == mailbox.id)
        .all()
    }

    changed = False

    for folder_name, slug in DEFAULT_FOLDERS:
        if slug not in existing:
            logger.warning(
                "Criando pasta padrão | mailbox_id=%s | email=%s | slug=%s | name=%s",
                mailbox.id,
                mailbox.email,
                slug,
                folder_name,
            )
            db.add(
                Pasta(
                    caixa_email_id=mailbox.id,
                    name=folder_name,
                    slug=slug,
                    system_flag=True,
                )
            )
            changed = True

    if changed:
        db.flush()
        logger.warning(
            "Pastas padrão garantidas | mailbox_id=%s | email=%s",
            mailbox.id,
            mailbox.email,
        )


def quota_mb_to_bytes(value: int) -> int:
    return int(value) * 1024 * 1024


def is_remote_absent_error(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False

    keywords = (
        "not found",
        "não encontrado",
        "não encontrada",
        "não foi encontrado",
        "não foi encontrada",
        "does not exist",
        "doesn't exist",
        "already absent",
        "principal not found",
        "mailbox not found",
        "account not found",
        "unknown account",
        "não existe no servidor de e-mail",
    )
    return any(keyword in text for keyword in keywords)


@router.get("")
def list_mailboxes(
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.warning(
        "Listando caixas | empresa_id=%s | user_id=%s",
        current_user.empresa_id,
        current_user.id,
    )

    items = (
        db.query(CaixaEmail)
        .options(joinedload(CaixaEmail.dominio))
        .filter(CaixaEmail.empresa_id == current_user.empresa_id)
        .order_by(
            CaixaEmail.is_active.desc(),
            CaixaEmail.created_at.asc(),
            CaixaEmail.id.asc(),
        )
        .all()
    )

    logger.warning(
        "Caixas listadas | empresa_id=%s | total=%s",
        current_user.empresa_id,
        len(items),
    )

    return {
        "success": True,
        "items": [serialize_mailbox(item) for item in items],
        "count": len(items),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_mailbox(
    data: MailboxCreateRequest,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.warning(
        "Solicitação para criar caixa | empresa_id=%s | user_id=%s | dominio_id=%s | local_part=%s | display_name=%s | quota_mb=%s | is_active=%s | is_admin=%s | password_sent=%s",
        current_user.empresa_id,
        current_user.id,
        data.dominio_id,
        data.local_part,
        data.display_name,
        data.quota_mb,
        data.is_active,
        data.is_admin,
        data.password is not None,
    )

    domain = get_domain_for_user(db, data.dominio_id, current_user.empresa_id)

    local_part = normalize_local_part(data.local_part)
    logger.warning("Local part normalizado | input=%s | normalized=%s", data.local_part, local_part)

    if not validate_local_part(local_part):
        logger.warning("Local part inválido | normalized=%s", local_part)
        raise HTTPException(
            status_code=400,
            detail="Local part inválido. Use letras, números, ponto, hífen ou underline.",
        )

    email = f"{local_part}@{domain.name}"
    logger.warning("E-mail calculado para nova caixa | email=%s | domain=%s", email, domain.name)

    existing = get_mailbox_by_email_for_company(
        db,
        empresa_id=current_user.empresa_id,
        email=email,
    )
    if existing:
        logger.warning(
            "Tentativa de criar caixa já existente no banco | email=%s | existing_id=%s",
            email,
            existing.id,
        )
        raise HTTPException(status_code=409, detail="Essa caixa já está cadastrada.")

    display_name = normalize_display_name(data.display_name)
    plain_password, password_hash = build_mailbox_password(data.password)

    logger.warning(
        "Senha da caixa preparada | email=%s | generated_password=%s | display_name=%s",
        email,
        data.password is None,
        display_name,
    )

    try:
        smtp_password_enc = encrypt_secret(plain_password)
        logger.warning("Senha criptografada com sucesso | email=%s", email)
    except SecretCryptoError as exc:
        logger.exception("Erro ao criptografar senha | email=%s", email)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    mailbox = CaixaEmail(
        empresa_id=current_user.empresa_id,
        dominio_id=domain.id,
        local_part=local_part,
        email=email,
        display_name=display_name,
        password_hash=password_hash,
        smtp_password_enc=smtp_password_enc,
        quota_mb=data.quota_mb,
        is_admin=bool(data.is_admin),
        is_active=bool(data.is_active),
    )
    db.add(mailbox)

    try:
        db.flush()
        logger.warning(
            "Caixa criada localmente com flush | mailbox_id=%s | email=%s",
            mailbox.id,
            mailbox.email,
        )

        ensure_default_folders(db, mailbox)

        client = get_stalwart_client()
        logger.warning(
            "Snapshot do client antes do create remoto | email=%s | client=%s",
            email,
            get_client_debug_snapshot(client),
        )

        if client.enabled:
            client.create_mailbox(
                login_name=email,
                email=email,
                password=plain_password,
                display_name=display_name,
                quota_bytes=quota_mb_to_bytes(data.quota_mb),
                is_enabled=bool(data.is_active),
            )
            logger.warning("Create remoto concluído | email=%s", email)
        else:
            logger.warning("Client Stalwart desativado; create apenas local | email=%s", email)

        db.commit()
        logger.warning(
            "Commit concluído no create de caixa | mailbox_id=%s | email=%s",
            mailbox.id,
            mailbox.email,
        )
        db.refresh(mailbox)

    except IntegrityError:
        logger.exception("IntegrityError ao criar caixa | email=%s", email)
        db.rollback()
        raise HTTPException(status_code=409, detail="Essa caixa já está cadastrada.")
    except StalwartProvisioningError as exc:
        logger.exception("Erro Stalwart ao criar caixa | email=%s | error=%s", email, exc)
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "Caixa criada com sucesso.",
        "item": serialize_mailbox(mailbox),
        "generated_password": plain_password if data.password is None else None,
    }


@router.patch("/{mailbox_id}")
def update_mailbox(
    mailbox_id: int,
    data: MailboxUpdateRequest,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.warning(
        "Solicitação para atualizar caixa | mailbox_id=%s | empresa_id=%s | user_id=%s | payload=%s",
        mailbox_id,
        current_user.empresa_id,
        current_user.id,
        {
            "dominio_id": data.dominio_id,
            "local_part": data.local_part,
            "display_name": data.display_name,
            "quota_mb": data.quota_mb,
            "is_active": data.is_active,
            "is_admin": data.is_admin,
        },
    )

    mailbox = get_mailbox_for_user(db, mailbox_id, current_user.empresa_id)
    old_email = mailbox.email

    logger.warning(
        "Caixa carregada para update | mailbox_id=%s | old_email=%s | dominio_id=%s | local_part=%s",
        mailbox.id,
        old_email,
        mailbox.dominio_id,
        mailbox.local_part,
    )

    if data.dominio_id is not None and int(data.dominio_id) != int(mailbox.dominio_id):
        new_domain = get_domain_for_user(db, data.dominio_id, current_user.empresa_id)
        logger.warning(
            "Alterando domínio da caixa | mailbox_id=%s | old_domain_id=%s | new_domain_id=%s | new_domain_name=%s",
            mailbox.id,
            mailbox.dominio_id,
            new_domain.id,
            new_domain.name,
        )
        mailbox.dominio_id = new_domain.id
        mailbox.dominio = new_domain

    if data.local_part is not None:
        new_local_part = normalize_local_part(data.local_part)
        logger.warning(
            "Novo local_part recebido | mailbox_id=%s | input=%s | normalized=%s",
            mailbox.id,
            data.local_part,
            new_local_part,
        )
        if not validate_local_part(new_local_part):
            logger.warning("Local part inválido no update | mailbox_id=%s | normalized=%s", mailbox.id, new_local_part)
            raise HTTPException(
                status_code=400,
                detail="Local part inválido. Use letras, números, ponto, hífen ou underline.",
            )
        mailbox.local_part = new_local_part

    if mailbox.dominio is None:
        mailbox.dominio = get_domain_for_user(db, mailbox.dominio_id, current_user.empresa_id)

    new_email = f"{mailbox.local_part}@{mailbox.dominio.name}"
    logger.warning(
        "Novo e-mail calculado para update | mailbox_id=%s | old_email=%s | new_email=%s",
        mailbox.id,
        old_email,
        new_email,
    )

    existing = get_mailbox_by_email_for_company(
        db,
        empresa_id=current_user.empresa_id,
        email=new_email,
        except_id=mailbox.id,
    )
    if existing:
        logger.warning(
            "Conflito de e-mail no update | mailbox_id=%s | new_email=%s | conflict_id=%s",
            mailbox.id,
            new_email,
            existing.id,
        )
        raise HTTPException(status_code=409, detail="Já existe uma caixa com esse endereço.")

    mailbox.email = new_email

    if data.display_name is not None:
        mailbox.display_name = normalize_display_name(data.display_name)
    if data.quota_mb is not None:
        mailbox.quota_mb = data.quota_mb
    if data.is_active is not None:
        mailbox.is_active = bool(data.is_active)
    if data.is_admin is not None:
        mailbox.is_admin = bool(data.is_admin)

    logger.warning(
        "Estado final local antes do flush no update | mailbox_id=%s | email=%s | display_name=%s | quota_mb=%s | is_active=%s | is_admin=%s",
        mailbox.id,
        mailbox.email,
        mailbox.display_name,
        mailbox.quota_mb,
        mailbox.is_active,
        mailbox.is_admin,
    )

    try:
        db.flush()
        logger.warning(
            "Flush concluído no update local | mailbox_id=%s | old_email=%s | new_email=%s",
            mailbox.id,
            old_email,
            mailbox.email,
        )

        client = get_stalwart_client()
        logger.warning(
            "Snapshot do client antes do update remoto | mailbox_id=%s | email=%s | client=%s",
            mailbox.id,
            mailbox.email,
            get_client_debug_snapshot(client),
        )

        if client.enabled:
            client.update_mailbox_by_email(
                old_email,
                new_login_name=mailbox.email,
                new_email=mailbox.email if mailbox.email != old_email else None,
                display_name=mailbox.display_name,
                quota_bytes=quota_mb_to_bytes(mailbox.quota_mb),
                is_active=bool(mailbox.is_active),
            )
            logger.warning(
                "Update remoto concluído | mailbox_id=%s | old_email=%s | new_email=%s",
                mailbox.id,
                old_email,
                mailbox.email,
            )
        else:
            logger.warning(
                "Client Stalwart desativado; update apenas local | mailbox_id=%s | email=%s",
                mailbox.id,
                mailbox.email,
            )

        db.commit()
        logger.warning(
            "Commit concluído no update | mailbox_id=%s | email=%s",
            mailbox.id,
            mailbox.email,
        )
        db.refresh(mailbox)

    except IntegrityError:
        logger.exception(
            "IntegrityError no update de caixa | mailbox_id=%s | old_email=%s | new_email=%s",
            mailbox_id,
            old_email,
            mailbox.email,
        )
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existe uma caixa com esse endereço.")
    except StalwartProvisioningError as exc:
        logger.exception(
            "Erro Stalwart no update de caixa | mailbox_id=%s | old_email=%s | new_email=%s | error=%s",
            mailbox_id,
            old_email,
            mailbox.email,
            exc,
        )
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "Caixa atualizada com sucesso.",
        "item": serialize_mailbox(mailbox),
    }


@router.post("/{mailbox_id}/set-password")
def set_mailbox_password(
    mailbox_id: int,
    data: MailboxPasswordRequest,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.warning(
        "Solicitação para trocar senha da caixa | mailbox_id=%s | empresa_id=%s | user_id=%s | password_len=%s",
        mailbox_id,
        current_user.empresa_id,
        current_user.id,
        len((data.password or "").strip()),
    )

    mailbox = get_mailbox_for_user(db, mailbox_id, current_user.empresa_id)
    new_password = (data.password or "").strip()

    if len(new_password) < 8:
        logger.warning("Senha curta demais no set-password | mailbox_id=%s", mailbox_id)
        raise HTTPException(status_code=400, detail="A senha precisa ter pelo menos 8 caracteres.")

    try:
        mailbox.password_hash = hash_password(new_password)
        mailbox.smtp_password_enc = encrypt_secret(new_password)

        logger.warning(
            "Senha atualizada localmente | mailbox_id=%s | email=%s",
            mailbox.id,
            mailbox.email,
        )

        client = get_stalwart_client()
        logger.warning(
            "Snapshot do client antes do update remoto de senha | mailbox_id=%s | email=%s | client=%s",
            mailbox.id,
            mailbox.email,
            get_client_debug_snapshot(client),
        )

        if client.enabled:
            client.update_mailbox_by_email(
                mailbox.email,
                new_login_name=mailbox.email,
                password=new_password,
            )
            logger.warning(
                "Senha atualizada remotamente | mailbox_id=%s | email=%s",
                mailbox.id,
                mailbox.email,
            )
        else:
            logger.warning(
                "Client Stalwart desativado; troca de senha apenas local | mailbox_id=%s | email=%s",
                mailbox.id,
                mailbox.email,
            )

        db.commit()
        logger.warning(
            "Commit concluído no set-password | mailbox_id=%s | email=%s",
            mailbox.id,
            mailbox.email,
        )
        db.refresh(mailbox)

    except SecretCryptoError as exc:
        logger.exception("Erro ao criptografar senha no set-password | mailbox_id=%s", mailbox_id)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except StalwartProvisioningError as exc:
        logger.exception(
            "Erro Stalwart no set-password | mailbox_id=%s | email=%s | error=%s",
            mailbox_id,
            mailbox.email,
            exc,
        )
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "Senha da caixa atualizada com sucesso.",
        "item": serialize_mailbox(mailbox),
    }


@router.delete("/{mailbox_id}")
def delete_mailbox(
    mailbox_id: int,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mailbox = get_mailbox_for_user(db, mailbox_id, current_user.empresa_id)
    deleted_item = serialize_mailbox(mailbox)
    mailbox_email = mailbox.email

    logger.warning(
        "Solicitação para excluir caixa | mailbox_id=%s | empresa_id=%s | user_id=%s | email=%s | deleted_item=%s",
        mailbox_id,
        current_user.empresa_id,
        current_user.id,
        mailbox_email,
        deleted_item,
    )

    try:
        db.delete(mailbox)
        db.flush()

        logger.warning(
            "Caixa removida localmente com flush | mailbox_id=%s | email=%s",
            mailbox_id,
            mailbox_email,
        )

        client = get_stalwart_client()
        logger.warning(
            "Snapshot do client antes do delete remoto | mailbox_id=%s | email=%s | client=%s",
            mailbox_id,
            mailbox_email,
            get_client_debug_snapshot(client),
        )

        if client.enabled:
            logger.warning(
                "Iniciando delete remoto da caixa | mailbox_id=%s | email=%s | base_url=%s",
                mailbox_id,
                mailbox_email,
                getattr(client, "base_url", None),
            )
            client.delete_mailbox_by_email(mailbox_email)
            logger.warning(
                "Delete remoto concluído sem exceção | mailbox_id=%s | email=%s",
                mailbox_id,
                mailbox_email,
            )
        else:
            logger.warning(
                "Cliente do servidor de e-mail está desativado; exclusão só local | mailbox_id=%s | email=%s",
                mailbox_id,
                mailbox_email,
            )

        db.commit()

        logger.warning(
            "Commit concluído no delete | mailbox_id=%s | empresa_id=%s | email=%s",
            mailbox_id,
            current_user.empresa_id,
            mailbox_email,
        )

    except StalwartProvisioningError as exc:
        detail = str(exc)

        logger.error(
            "Erro Stalwart durante delete | mailbox_id=%s | email=%s | detail=%s | remote_absent=%s",
            mailbox_id,
            mailbox_email,
            detail,
            is_remote_absent_error(detail),
        )

        if is_remote_absent_error(detail):
            logger.warning(
                "Caixa ausente remotamente; mantendo exclusão local | mailbox_id=%s | email=%s | detail=%s",
                mailbox_id,
                mailbox_email,
                detail,
            )
            db.commit()
            logger.warning(
                "Commit concluído após tolerar ausência remota | mailbox_id=%s | email=%s",
                mailbox_id,
                mailbox_email,
            )
            return {
                "success": True,
                "message": "Caixa removida com sucesso.",
                "deleted": deleted_item,
            }

        logger.error(
            "Rollback do delete por falha remota | mailbox_id=%s | email=%s | detail=%s",
            mailbox_id,
            mailbox_email,
            detail,
        )
        db.rollback()
        raise HTTPException(status_code=502, detail=detail) from exc

    except Exception:
        logger.exception(
            "Erro inesperado ao excluir caixa | mailbox_id=%s | empresa_id=%s | email=%s",
            mailbox_id,
            current_user.empresa_id,
            mailbox_email,
        )
        db.rollback()
        raise

    return {
        "success": True,
        "message": "Caixa removida com sucesso.",
        "deleted": deleted_item,
    }