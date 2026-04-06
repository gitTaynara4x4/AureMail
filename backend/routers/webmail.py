from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.integrations.smtp_client import SmtpDeliveryError, get_smtp_client
from backend.models import (
    CaixaEmail,
    CaixaMensagem,
    Dominio,
    Empresa,
    Mensagem,
    Pasta,
)
from backend.routers.webmail_auth import get_current_mail_actor
from backend.utils.crypto import SecretCryptoError, decrypt_secret


router = APIRouter(prefix="/api/webmail", tags=["Webmail"])


DEFAULT_FOLDERS = {
    "inbox": "Caixa de entrada",
    "sent": "Enviados",
    "drafts": "Rascunhos",
    "trash": "Lixeira",
}


class ComposeRequest(BaseModel):
    to: str = Field(..., min_length=3, max_length=320)
    subject: str | None = Field(default=None, max_length=255)
    body: str | None = Field(default=None, max_length=100_000)
    save_as_draft: bool = False


class MoveMessageRequest(BaseModel):
    target_folder: str = Field(..., min_length=2, max_length=50)


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def preview_from_body(body: str | None, max_len: int = 180) -> str | None:
    if not body:
        return None
    text = " ".join(body.split())
    if not text:
        return None
    return text[:max_len]


def actor_empresa_id(actor: dict[str, Any]) -> int:
    return int(actor["empresa_id"])


def actor_kind(actor: dict[str, Any]) -> str:
    return str(actor.get("kind") or "").strip().lower()


def actor_mailbox(actor: dict[str, Any]) -> CaixaEmail | None:
    mailbox = actor.get("mailbox")
    return mailbox if isinstance(mailbox, CaixaEmail) else None


def get_company(db: Session, empresa_id: int) -> Empresa | None:
    return (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id)
        .first()
    )


def serialize_domain(domain: Dominio) -> dict:
    return {
        "id": domain.id,
        "empresa_id": domain.empresa_id,
        "name": domain.name,
        "status": domain.status,
        "is_primary": bool(domain.is_primary),
        "created_at": domain.created_at.isoformat() if domain.created_at else None,
        "updated_at": domain.updated_at.isoformat() if domain.updated_at else None,
    }


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


def serialize_message_summary(link: CaixaMensagem) -> dict:
    msg = link.mensagem
    folder_slug = link.pasta.slug if link.pasta else None

    return {
        "id": msg.id,
        "folder": folder_slug,
        "is_read": bool(link.is_read),
        "is_starred": bool(link.is_starred),
        "is_deleted": bool(link.is_deleted),
        "direction": msg.direction,
        "from_name": msg.from_name,
        "from_email": msg.from_email,
        "to_email": msg.to_email,
        "cc_email": msg.cc_email,
        "subject": msg.subject,
        "preview": msg.preview,
        "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def serialize_message_detail(link: CaixaMensagem) -> dict:
    data = serialize_message_summary(link)
    msg = link.mensagem
    data.update(
        {
            "message_id_header": msg.message_id_header,
            "body_text": msg.body_text,
            "body_html": msg.body_html,
            "raw_source": msg.raw_source,
        }
    )
    return data


def ensure_default_folders(db: Session, mailbox: CaixaEmail) -> bool:
    existing = {
        row.slug
        for row in db.query(Pasta.slug).filter(Pasta.caixa_email_id == mailbox.id).all()
    }

    changed = False

    for slug, name in DEFAULT_FOLDERS.items():
        if slug not in existing:
            db.add(
                Pasta(
                    caixa_email_id=mailbox.id,
                    name=name,
                    slug=slug,
                    system_flag=True,
                )
            )
            changed = True

    if changed:
        db.flush()

    return changed


def build_folder_counts(db: Session, mailbox_id: int) -> dict[str, int]:
    counts = {slug: 0 for slug in DEFAULT_FOLDERS.keys()}

    rows = (
        db.query(Pasta.slug, func.count(CaixaMensagem.id))
        .outerjoin(CaixaMensagem, CaixaMensagem.pasta_id == Pasta.id)
        .filter(Pasta.caixa_email_id == mailbox_id)
        .group_by(Pasta.slug)
        .all()
    )

    for slug, total in rows:
        if slug in counts:
            counts[slug] = int(total or 0)

    return counts


def get_folder_map(db: Session, mailbox_id: int) -> dict[str, Pasta]:
    rows = db.query(Pasta).filter(Pasta.caixa_email_id == mailbox_id).all()
    return {row.slug: row for row in rows}


def get_mailbox_for_company(
    db: Session,
    empresa_id: int,
    mailbox_id: int,
    only_active: bool = False,
) -> CaixaEmail | None:
    query = (
        db.query(CaixaEmail)
        .options(joinedload(CaixaEmail.dominio))
        .filter(
            CaixaEmail.id == mailbox_id,
            CaixaEmail.empresa_id == empresa_id,
        )
    )

    if only_active:
        query = query.filter(CaixaEmail.is_active.is_(True))

    return query.first()


def get_required_mailbox_for_company(
    db: Session,
    empresa_id: int,
    mailbox_id: int,
    only_active: bool = False,
) -> CaixaEmail:
    mailbox = get_mailbox_for_company(db, empresa_id, mailbox_id, only_active=only_active)
    if not mailbox:
        raise HTTPException(status_code=404, detail="Caixa de e-mail não encontrada.")
    return mailbox


def get_accessible_mailbox(
    db: Session,
    actor: dict[str, Any],
    mailbox_id: int,
    only_active: bool = False,
) -> CaixaEmail:
    mailbox = get_required_mailbox_for_company(
        db,
        empresa_id=actor_empresa_id(actor),
        mailbox_id=mailbox_id,
        only_active=only_active,
    )

    if actor_kind(actor) == "mailbox_user":
        own_mailbox = actor_mailbox(actor)
        if not own_mailbox or int(mailbox.id) != int(own_mailbox.id):
            raise HTTPException(status_code=403, detail="Acesso negado para esta caixa.")

    return mailbox


def resolve_selected_context(
    domains: list[Dominio],
    mailboxes: list[CaixaEmail],
    requested_domain_id: int | None,
    requested_mailbox_id: int | None,
) -> tuple[Dominio | None, CaixaEmail | None]:
    domain_map = {item.id: item for item in domains}
    mailbox_map = {item.id: item for item in mailboxes}

    selected_domain = domain_map.get(requested_domain_id) if requested_domain_id else None
    selected_mailbox = mailbox_map.get(requested_mailbox_id) if requested_mailbox_id else None

    if selected_mailbox:
        selected_domain = domain_map.get(selected_mailbox.dominio_id)

    if not selected_domain:
        selected_domain = next((item for item in domains if item.is_primary), None)
    if not selected_domain and domains:
        selected_domain = domains[0]

    domain_mailboxes = [
        item for item in mailboxes
        if selected_domain and item.dominio_id == selected_domain.id
    ]

    if selected_mailbox and selected_domain and selected_mailbox.dominio_id != selected_domain.id:
        selected_mailbox = None

    if not selected_mailbox:
        selected_mailbox = next((item for item in domain_mailboxes if item.is_active), None)

    if not selected_mailbox and domain_mailboxes:
        selected_mailbox = domain_mailboxes[0]

    if not selected_domain and selected_mailbox:
        selected_domain = domain_map.get(selected_mailbox.dominio_id)

    return selected_domain, selected_mailbox


def get_link_for_mailbox(db: Session, mailbox_id: int, message_id: int) -> CaixaMensagem:
    link = (
        db.query(CaixaMensagem)
        .options(
            joinedload(CaixaMensagem.mensagem),
            joinedload(CaixaMensagem.pasta),
        )
        .filter(
            CaixaMensagem.caixa_email_id == mailbox_id,
            CaixaMensagem.mensagem_id == message_id,
        )
        .first()
    )

    if not link:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")

    return link


def save_outbound_message(
    *,
    db: Session,
    empresa_id: int,
    mailbox: CaixaEmail,
    folder: Pasta,
    to_email: str,
    subject: str | None,
    body: str | None,
    message_id_header: str,
    sent_at: datetime | None,
) -> CaixaMensagem:
    mensagem = Mensagem(
        empresa_id=empresa_id,
        direction="outbound",
        message_id_header=message_id_header,
        from_name=mailbox.display_name or mailbox.local_part,
        from_email=mailbox.email,
        to_email=to_email,
        subject=subject,
        preview=preview_from_body(body),
        body_text=body,
        body_html=None,
        raw_source=None,
        sent_at=sent_at,
    )

    db.add(mensagem)
    db.flush()

    link = CaixaMensagem(
        caixa_email_id=mailbox.id,
        mensagem_id=mensagem.id,
        pasta_id=folder.id,
        is_read=True,
        is_starred=False,
        is_deleted=(folder.slug == "trash"),
    )
    db.add(link)
    db.flush()
    return link


@router.get("/context")
def webmail_context(
    dominio_id: int | None = Query(default=None),
    caixa_id: int | None = Query(default=None),
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    empresa_id = actor_empresa_id(actor)
    company = get_company(db, empresa_id)

    if actor_kind(actor) == "mailbox_user":
        mailbox = get_accessible_mailbox(
            db,
            actor=actor,
            mailbox_id=int(actor_mailbox(actor).id),
            only_active=True,
        )
        changed = ensure_default_folders(db, mailbox)
        if changed:
            db.commit()

        domain = mailbox.dominio
        domains = [domain] if domain else []
        mailboxes = [mailbox]

        return {
            "success": True,
            "auth_mode": "mailbox",
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
                "id": company.id if company else None,
                "name": company.name if company else None,
                "status": company.status if company else None,
                "cnpj_cpf": company.cnpj_cpf if company else None,
            },
            "domains": [serialize_domain(item) for item in domains],
            "mailboxes": [serialize_mailbox(item) for item in mailboxes],
            "selected_domain_id": domain.id if domain else None,
            "selected_mailbox_id": mailbox.id,
        }

    current_user = actor["platform_user"]

    domains = (
        db.query(Dominio)
        .filter(Dominio.empresa_id == empresa_id)
        .order_by(Dominio.is_primary.desc(), Dominio.created_at.asc(), Dominio.id.asc())
        .all()
    )

    mailboxes = (
        db.query(CaixaEmail)
        .options(joinedload(CaixaEmail.dominio))
        .filter(CaixaEmail.empresa_id == empresa_id)
        .order_by(
            CaixaEmail.is_active.desc(),
            CaixaEmail.dominio_id.asc(),
            CaixaEmail.created_at.asc(),
            CaixaEmail.id.asc(),
        )
        .all()
    )

    selected_domain, selected_mailbox = resolve_selected_context(
        domains=domains,
        mailboxes=mailboxes,
        requested_domain_id=dominio_id,
        requested_mailbox_id=caixa_id,
    )

    return {
        "success": True,
        "auth_mode": "platform",
        "user": {
            "id": current_user.id,
            "empresa_id": current_user.empresa_id,
            "name": current_user.name,
            "email": current_user.email,
            "is_owner": bool(current_user.is_owner),
            "is_active": bool(current_user.is_active),
            "account_type": "platform_user",
        },
        "company": {
            "id": company.id if company else None,
            "name": company.name if company else None,
            "status": company.status if company else None,
            "cnpj_cpf": company.cnpj_cpf if company else None,
        },
        "domains": [serialize_domain(item) for item in domains],
        "mailboxes": [serialize_mailbox(item) for item in mailboxes],
        "selected_domain_id": selected_domain.id if selected_domain else None,
        "selected_mailbox_id": selected_mailbox.id if selected_mailbox else None,
    }


@router.get("/mailboxes/{mailbox_id}/messages")
def list_messages(
    mailbox_id: int,
    folder: str = Query(default="inbox"),
    q: str | None = Query(default=None),
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    folder_slug = (folder or "inbox").strip().lower()
    if folder_slug not in DEFAULT_FOLDERS:
        raise HTTPException(status_code=400, detail="Pasta inválida.")

    mailbox = get_accessible_mailbox(
        db,
        actor=actor,
        mailbox_id=mailbox_id,
        only_active=False,
    )

    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    query = (
        db.query(CaixaMensagem)
        .options(
            joinedload(CaixaMensagem.mensagem),
            joinedload(CaixaMensagem.pasta),
        )
        .join(Mensagem, CaixaMensagem.mensagem_id == Mensagem.id)
        .join(Pasta, CaixaMensagem.pasta_id == Pasta.id)
        .filter(
            CaixaMensagem.caixa_email_id == mailbox.id,
            Pasta.slug == folder_slug,
        )
    )

    search = normalize_text(q)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Mensagem.subject.ilike(pattern),
                Mensagem.preview.ilike(pattern),
                Mensagem.from_email.ilike(pattern),
                Mensagem.to_email.ilike(pattern),
                Mensagem.body_text.ilike(pattern),
            )
        )

    items = (
        query.order_by(
            desc(func.coalesce(Mensagem.sent_at, Mensagem.created_at)),
            desc(CaixaMensagem.id),
        )
        .all()
    )

    return {
        "success": True,
        "mailbox": serialize_mailbox(mailbox),
        "folder": folder_slug,
        "folder_counts": build_folder_counts(db, mailbox.id),
        "items": [serialize_message_summary(item) for item in items],
        "count": len(items),
    }


@router.get("/mailboxes/{mailbox_id}/messages/{message_id}")
def message_detail(
    mailbox_id: int,
    message_id: int,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(
        db,
        actor=actor,
        mailbox_id=mailbox_id,
        only_active=False,
    )

    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)

    return {
        "success": True,
        "mailbox": serialize_mailbox(mailbox),
        "item": serialize_message_detail(link),
    }


@router.post("/mailboxes/{mailbox_id}/messages/{message_id}/read")
def mark_message_as_read(
    mailbox_id: int,
    message_id: int,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(
        db,
        actor=actor,
        mailbox_id=mailbox_id,
        only_active=False,
    )

    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)

    if not link.is_read:
        link.is_read = True
        db.commit()
        db.refresh(link)

    return {
        "success": True,
        "message": "Mensagem marcada como lida.",
        "item": serialize_message_detail(link),
    }


@router.post("/mailboxes/{mailbox_id}/messages/{message_id}/move")
def move_message(
    mailbox_id: int,
    message_id: int,
    data: MoveMessageRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(
        db,
        actor=actor,
        mailbox_id=mailbox_id,
        only_active=False,
    )

    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    folder_map = get_folder_map(db, mailbox.id)

    target_slug = (data.target_folder or "").strip().lower()
    if target_slug not in folder_map:
        raise HTTPException(status_code=400, detail="Pasta de destino inválida.")

    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)
    link.pasta_id = folder_map[target_slug].id
    link.is_deleted = target_slug == "trash"

    db.commit()
    db.refresh(link)

    return {
        "success": True,
        "message": "Mensagem movida com sucesso.",
        "item": serialize_message_detail(link),
        "folder_counts": build_folder_counts(db, mailbox.id),
    }


@router.post("/mailboxes/{mailbox_id}/compose", status_code=status.HTTP_201_CREATED)
def compose_message(
    mailbox_id: int,
    data: ComposeRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(
        db,
        actor=actor,
        mailbox_id=mailbox_id,
        only_active=True,
    )

    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    folder_map = get_folder_map(db, mailbox.id)

    to_email = normalize_text(data.to)
    subject = normalize_text(data.subject)
    body = normalize_text(data.body)

    if not to_email:
        raise HTTPException(status_code=400, detail="Informe o destinatário.")

    folder_slug = "drafts" if data.save_as_draft else "sent"
    folder = folder_map.get(folder_slug)

    if not folder:
        raise HTTPException(status_code=400, detail="Pasta de envio não encontrada.")

    try:
        if data.save_as_draft:
            message_id_header = f"<auremail-draft-{uuid4().hex}@local>"

            link = save_outbound_message(
                db=db,
                empresa_id=actor_empresa_id(actor),
                mailbox=mailbox,
                folder=folder,
                to_email=to_email,
                subject=subject,
                body=body,
                message_id_header=message_id_header,
                sent_at=None,
            )

            db.commit()
            db.refresh(link)

            return {
                "success": True,
                "message": "Rascunho salvo com sucesso.",
                "item": serialize_message_detail(link),
                "folder_counts": build_folder_counts(db, mailbox.id),
            }

        smtp_password = decrypt_secret(mailbox.smtp_password_enc)
        smtp_client = get_smtp_client()

        message_id_header = smtp_client.send_message(
            username=mailbox.email,
            password=smtp_password,
            from_email=mailbox.email,
            to_email=to_email,
            subject=subject,
            body_text=body,
            from_name=mailbox.display_name or mailbox.local_part,
        )

        now = datetime.now(timezone.utc)

        link = save_outbound_message(
            db=db,
            empresa_id=actor_empresa_id(actor),
            mailbox=mailbox,
            folder=folder,
            to_email=to_email,
            subject=subject,
            body=body,
            message_id_header=message_id_header,
            sent_at=now,
        )

        db.commit()
        db.refresh(link)

        return {
            "success": True,
            "message": "E-mail enviado com sucesso.",
            "item": serialize_message_detail(link),
            "folder_counts": build_folder_counts(db, mailbox.id),
        }

    except SecretCryptoError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except SmtpDeliveryError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc