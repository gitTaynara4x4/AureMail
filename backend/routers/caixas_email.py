import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import CaixaEmail, Dominio, Pasta, UsuarioPlataforma
from backend.routers.auth import get_current_user, hash_password


router = APIRouter(prefix="/api/caixas-email", tags=["Caixas de e-mail"])


LOCAL_PART_REGEX = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]{0,118}[a-z0-9])?$"
)

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
    quota_mb: int = Field(default=2048, ge=128, le=102400)
    is_active: bool = True


class MailboxUpdateRequest(BaseModel):
    dominio_id: int | None = None
    local_part: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=150)
    quota_mb: int | None = Field(default=None, ge=128, le=102400)
    is_active: bool | None = None


def normalize_local_part(value: str) -> str:
    local = (value or "").strip().lower()
    local = re.sub(r"\s+", "", local)
    return local


def validate_local_part(value: str) -> bool:
    return bool(LOCAL_PART_REGEX.match(normalize_local_part(value)))


def normalize_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text[:150] if text else None


def build_mailbox_placeholder_hash(email: str) -> str:
    return hash_password(f"{email}::pending_mailbox_setup")


def serialize_mailbox(mailbox: CaixaEmail) -> dict:
    domain_name = mailbox.dominio.name if mailbox.dominio else None
    return {
        "id": mailbox.id,
        "empresa_id": mailbox.empresa_id,
        "dominio_id": mailbox.dominio_id,
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
        raise HTTPException(status_code=404, detail="Domínio não encontrado.")
    return domain


def get_mailbox_for_user(db: Session, mailbox_id: int, empresa_id: int) -> CaixaEmail:
    mailbox = (
        db.query(CaixaEmail)
        .filter(
            CaixaEmail.id == mailbox_id,
            CaixaEmail.empresa_id == empresa_id,
        )
        .first()
    )
    if not mailbox:
        raise HTTPException(status_code=404, detail="Caixa de e-mail não encontrada.")
    return mailbox


def ensure_default_folders(db: Session, mailbox: CaixaEmail) -> None:
    for folder_name, slug in DEFAULT_FOLDERS:
        db.add(
            Pasta(
                caixa_email_id=mailbox.id,
                name=folder_name,
                slug=slug,
                system_flag=True,
            )
        )


@router.get("")
def list_mailboxes(
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = (
        db.query(CaixaEmail)
        .filter(CaixaEmail.empresa_id == current_user.empresa_id)
        .order_by(CaixaEmail.is_active.desc(), CaixaEmail.created_at.asc(), CaixaEmail.id.asc())
        .all()
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
    domain = get_domain_for_user(db, data.dominio_id, current_user.empresa_id)

    local_part = normalize_local_part(data.local_part)
    if not validate_local_part(local_part):
        raise HTTPException(
            status_code=400,
            detail="Local part inválido. Use letras, números, ponto, hífen ou underline.",
        )

    display_name = normalize_display_name(data.display_name)
    email = f"{local_part}@{domain.name}"

    mailbox = CaixaEmail(
        empresa_id=current_user.empresa_id,
        dominio_id=domain.id,
        local_part=local_part,
        email=email,
        display_name=display_name,
        password_hash=build_mailbox_placeholder_hash(email),
        quota_mb=int(data.quota_mb),
        is_admin=False,
        is_active=bool(data.is_active),
    )

    db.add(mailbox)

    try:
        db.flush()
        ensure_default_folders(db, mailbox)
        db.commit()
        db.refresh(mailbox)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Já existe uma caixa com esse endereço nesse domínio.",
        )

    return {
        "success": True,
        "message": "Caixa de e-mail criada com sucesso.",
        "item": serialize_mailbox(mailbox),
    }


@router.patch("/{mailbox_id}")
def update_mailbox(
    mailbox_id: int,
    data: MailboxUpdateRequest,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mailbox = get_mailbox_for_user(db, mailbox_id, current_user.empresa_id)

    target_domain = mailbox.dominio
    if data.dominio_id is not None:
        target_domain = get_domain_for_user(db, data.dominio_id, current_user.empresa_id)
        mailbox.dominio_id = target_domain.id

    if data.local_part is not None:
        local_part = normalize_local_part(data.local_part)
        if not validate_local_part(local_part):
            raise HTTPException(
                status_code=400,
                detail="Local part inválido. Use letras, números, ponto, hífen ou underline.",
            )
        mailbox.local_part = local_part

    if data.display_name is not None:
        mailbox.display_name = normalize_display_name(data.display_name)

    if data.quota_mb is not None:
        mailbox.quota_mb = int(data.quota_mb)

    if data.is_active is not None:
        mailbox.is_active = bool(data.is_active)

    domain_name = target_domain.name if target_domain else mailbox.dominio.name
    mailbox.email = f"{mailbox.local_part}@{domain_name}"

    try:
        db.commit()
        db.refresh(mailbox)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Já existe uma caixa com esse endereço nesse domínio.",
        )

    return {
        "success": True,
        "message": "Caixa de e-mail atualizada com sucesso.",
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

    db.delete(mailbox)
    db.commit()

    return {
        "success": True,
        "message": "Caixa de e-mail removida com sucesso.",
        "deleted": deleted_item,
    }