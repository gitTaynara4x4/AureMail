from __future__ import annotations

import logging
import math
import os
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session, joinedload

from backend.database import SessionLocal, get_db
from backend.integrations.imap_client import ImapSyncError, RemoteMessage, get_imap_client
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
logger = logging.getLogger("auremail.webmail")

REAL_FOLDERS = {
    "inbox": "Caixa de entrada",
    "sent": "Enviados",
    "drafts": "Rascunhos",
    "junk": "Spam",
    "trash": "Lixeira",
}

VIRTUAL_FOLDERS = {
    "starred": "Com estrela",
    "snoozed": "Adiados",
    "important": "Importante",
    "scheduled": "Programados",
    "all_mail": "Todos os e-mails",
    "purchases": "Compras",
}

ALL_FOLDERS = {**REAL_FOLDERS, **VIRTUAL_FOLDERS}
INBOX_CATEGORIES = {"primary", "promotions", "social", "updates"}

_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()


class ComposeRequest(BaseModel):
    to: str = Field(..., min_length=3, max_length=320)
    subject: str | None = Field(default=None, max_length=255)
    body: str | None = Field(default=None, max_length=100_000)
    save_as_draft: bool = False
    save_as_scheduled: bool = False
    scheduled_for: datetime | None = None


class MoveMessageRequest(BaseModel):
    target_folder: str = Field(..., min_length=2, max_length=50)


class BulkMoveMessagesRequest(BaseModel):
    message_ids: list[int] = Field(default_factory=list)
    target_folder: str = Field(..., min_length=2, max_length=50)


class BulkDeleteMessagesRequest(BaseModel):
    message_ids: list[int] = Field(default_factory=list)


class ToggleFlagRequest(BaseModel):
    value: bool = True


class SnoozeMessageRequest(BaseModel):
    snoozed_until: datetime | None = None


def _env_bool(name: str, default: bool = True) -> bool:
    raw = (os.getenv(name, "true" if default else "false") or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name, str(default)) or "").strip()
    try:
        value = int(raw)
    except Exception:
        return default
    return value if value > 0 else default


def is_scheduler_enabled() -> bool:
    return _env_bool("AUREMAIL_ENABLE_SCHEDULED_SENDER", True)


def get_scheduler_poll_seconds() -> int:
    return _env_int("AUREMAIL_SCHEDULED_SENDER_POLL_SECONDS", 20)


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def normalize_email_address(value: str | None) -> str | None:
    text = normalize_text(value)
    return text.lower() if text else None


def normalize_message_id_header(value: str | None) -> str | None:
    text = normalize_text(value)
    return text.lower() if text else None


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
    return db.query(Empresa).filter(Empresa.id == empresa_id).first()


def is_real_folder(folder_slug: str) -> bool:
    return folder_slug in REAL_FOLDERS


def classify_message_bucket(
    subject: str | None,
    preview: str | None,
    from_email: str | None,
    from_name: str | None,
    body_text: str | None,
) -> str:
    text = " ".join(
        part
        for part in [
            subject or "",
            preview or "",
            from_email or "",
            from_name or "",
            body_text or "",
        ]
        if part
    ).lower()

    if any(
        word in text
        for word in [
            "facebook",
            "instagram",
            "linkedin",
            "twitter",
            "x.com",
            "tiktok",
            "youtube",
            "discord",
            "telegram",
            "curtiu",
            "comentou",
            "social",
        ]
    ):
        return "social"

    if any(
        word in text
        for word in [
            "promo",
            "promoção",
            "promocao",
            "oferta",
            "cupom",
            "desconto",
            "sale",
            "novidades",
            "frete",
            "compre",
            "pedido",
            "checkout",
            "amazon",
            "mercado livre",
            "mercadolivre",
            "shopee",
            "shein",
            "magalu",
        ]
    ):
        return "promotions"

    if any(
        word in text
        for word in [
            "segurança",
            "seguranca",
            "security",
            "alerta",
            "login",
            "acesso",
            "senha",
            "verificação",
            "verificacao",
            "código",
            "codigo",
            "invoice",
            "fatura",
            "configuração",
            "configuracao",
            "notificação",
            "notificacao",
            "update",
            "apple",
            "google",
        ]
    ):
        return "updates"

    return "primary"


def serialize_domain(domain: Dominio) -> dict[str, Any]:
    return {
        "id": int(domain.id),
        "empresa_id": int(domain.empresa_id),
        "name": domain.name,
        "status": domain.status,
        "is_primary": bool(domain.is_primary),
        "created_at": domain.created_at.isoformat() if domain.created_at else None,
        "updated_at": domain.updated_at.isoformat() if domain.updated_at else None,
    }


def serialize_mailbox(mailbox: CaixaEmail) -> dict[str, Any]:
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


def serialize_message_summary(link: CaixaMensagem) -> dict[str, Any]:
    msg = link.mensagem
    folder_slug = link.pasta.slug if link.pasta else None
    category = classify_message_bucket(
        subject=msg.subject,
        preview=msg.preview,
        from_email=msg.from_email,
        from_name=msg.from_name,
        body_text=msg.body_text,
    )
    return {
        "id": int(msg.id),
        "folder": folder_slug,
        "category": category,
        "is_read": bool(link.is_read),
        "is_starred": bool(link.is_starred),
        "is_important": bool(getattr(link, "is_important", False)),
        "snoozed_until": link.snoozed_until.isoformat() if getattr(link, "snoozed_until", None) else None,
        "is_deleted": bool(link.is_deleted),
        "direction": msg.direction,
        "from_name": msg.from_name,
        "from_email": msg.from_email,
        "to_email": msg.to_email,
        "cc_email": msg.cc_email,
        "subject": msg.subject,
        "preview": msg.preview,
        "scheduled_for": msg.scheduled_for.isoformat() if getattr(msg, "scheduled_for", None) else None,
        "schedule_status": getattr(msg, "schedule_status", None),
        "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def serialize_message_detail(link: CaixaMensagem) -> dict[str, Any]:
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
        row[0]
        for row in db.query(Pasta.slug).filter(Pasta.caixa_email_id == mailbox.id).all()
    }
    changed = False
    for slug, name in REAL_FOLDERS.items():
        if slug not in existing:
            db.add(Pasta(caixa_email_id=mailbox.id, name=name, slug=slug, system_flag=True))
            changed = True
    if changed:
        db.flush()
    return changed


def get_folder_map(db: Session, mailbox_id: int) -> dict[str, Pasta]:
    rows = db.query(Pasta).filter(Pasta.caixa_email_id == mailbox_id).all()
    return {row.slug: row for row in rows}


def _purchase_filter():
    return or_(
        Mensagem.subject.ilike("%pedido%"),
        Mensagem.subject.ilike("%compra%"),
        Mensagem.subject.ilike("%pagamento%"),
        Mensagem.subject.ilike("%nota fiscal%"),
        Mensagem.subject.ilike("%recibo%"),
        Mensagem.from_email.ilike("%mercadolivre%"),
        Mensagem.from_email.ilike("%amazon%"),
        Mensagem.from_email.ilike("%shopee%"),
        Mensagem.from_email.ilike("%magazineluiza%"),
        Mensagem.from_email.ilike("%americanas%"),
    )


def apply_folder_filter(query, folder_slug: str):
    now = datetime.now(timezone.utc)
    folder_slug = (folder_slug or "inbox").strip().lower()

    if folder_slug == "inbox":
        return query.filter(
            Pasta.slug == "inbox",
            or_(CaixaMensagem.snoozed_until.is_(None), CaixaMensagem.snoozed_until <= now),
        )

    if folder_slug == "sent":
        return query.filter(Pasta.slug == "sent")

    if folder_slug == "drafts":
        return query.filter(
            Pasta.slug == "drafts",
            or_(Mensagem.schedule_status.is_(None), Mensagem.schedule_status != "scheduled"),
        )

    if folder_slug == "junk":
        return query.filter(Pasta.slug == "junk")

    if folder_slug == "trash":
        return query.filter(Pasta.slug == "trash")

    if folder_slug == "starred":
        return query.filter(CaixaMensagem.is_starred.is_(True))

    if folder_slug == "important":
        return query.filter(CaixaMensagem.is_important.is_(True))

    if folder_slug == "snoozed":
        return query.filter(
            CaixaMensagem.snoozed_until.is_not(None),
            CaixaMensagem.snoozed_until > now,
        )

    if folder_slug == "scheduled":
        return query.filter(
            Mensagem.direction == "outbound",
            Mensagem.schedule_status == "scheduled",
            Mensagem.scheduled_for.is_not(None),
        )

    if folder_slug == "all_mail":
        return query.filter(~Pasta.slug.in_(["junk", "trash"]))

    if folder_slug == "purchases":
        return query.filter(
            ~Pasta.slug.in_(["junk", "trash"]),
            _purchase_filter(),
        )

    raise HTTPException(status_code=400, detail="Pasta inválida.")


def apply_category_filter(items: list[CaixaMensagem], category: str | None) -> list[CaixaMensagem]:
    normalized = (category or "").strip().lower()
    if not normalized:
        return items
    if normalized not in INBOX_CATEGORIES:
        raise HTTPException(status_code=400, detail="Categoria inválida.")
    return [
        item
        for item in items
        if classify_message_bucket(
            subject=item.mensagem.subject if item.mensagem else None,
            preview=item.mensagem.preview if item.mensagem else None,
            from_email=item.mensagem.from_email if item.mensagem else None,
            from_name=item.mensagem.from_name if item.mensagem else None,
            body_text=item.mensagem.body_text if item.mensagem else None,
        )
        == normalized
    ]


def paginate_items(items: list[Any], page: int, page_size: int) -> tuple[list[Any], dict[str, Any]]:
    total = len(items)
    total_pages = max(1, math.ceil(total / page_size)) if total else 1
    current_page = min(max(1, page), total_pages)
    start = (current_page - 1) * page_size
    end = start + page_size
    sliced = items[start:end]

    return sliced, {
        "page": current_page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": current_page < total_pages,
        "has_prev": current_page > 1,
        "start_index": (start + 1) if total else 0,
        "end_index": min(end, total) if total else 0,
    }


def count_messages_for_folder(db: Session, mailbox_id: int, folder_slug: str) -> int:
    query = (
        db.query(func.count(CaixaMensagem.id))
        .join(Mensagem, CaixaMensagem.mensagem_id == Mensagem.id)
        .join(Pasta, CaixaMensagem.pasta_id == Pasta.id)
        .filter(CaixaMensagem.caixa_email_id == mailbox_id)
    )
    query = apply_folder_filter(query, folder_slug)
    return int(query.scalar() or 0)


def build_folder_counts(db: Session, mailbox_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slug in ALL_FOLDERS.keys():
        counts[slug] = count_messages_for_folder(db, mailbox_id, slug)
    return counts


def get_mailbox_for_company(db: Session, empresa_id: int, mailbox_id: int, only_active: bool = False) -> CaixaEmail | None:
    query = (
        db.query(CaixaEmail)
        .options(joinedload(CaixaEmail.dominio))
        .filter(CaixaEmail.id == mailbox_id, CaixaEmail.empresa_id == empresa_id)
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
    mailbox = get_mailbox_for_company(db, empresa_id=empresa_id, mailbox_id=mailbox_id, only_active=only_active)
    if not mailbox:
        raise HTTPException(status_code=404, detail="Caixa de e-mail não encontrada.")
    return mailbox


def get_accessible_mailbox(db: Session, actor: dict[str, Any], mailbox_id: int, only_active: bool = False) -> CaixaEmail:
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
    domain_map = {int(item.id): item for item in domains}
    mailbox_map = {int(item.id): item for item in mailboxes}

    selected_domain = domain_map.get(int(requested_domain_id)) if requested_domain_id else None
    selected_mailbox = mailbox_map.get(int(requested_mailbox_id)) if requested_mailbox_id else None

    if selected_mailbox:
        selected_domain = domain_map.get(int(selected_mailbox.dominio_id))

    if not selected_domain:
        selected_domain = next((item for item in domains if item.is_primary), None)

    if not selected_domain and domains:
        selected_domain = domains[0]

    domain_mailboxes = [item for item in mailboxes if selected_domain and int(item.dominio_id) == int(selected_domain.id)]

    if selected_mailbox and selected_domain and int(selected_mailbox.dominio_id) != int(selected_domain.id):
        selected_mailbox = None

    if not selected_mailbox:
        selected_mailbox = next((item for item in domain_mailboxes if item.is_active), None)

    if not selected_mailbox and domain_mailboxes:
        selected_mailbox = domain_mailboxes[0]

    if not selected_domain and selected_mailbox:
        selected_domain = domain_map.get(int(selected_mailbox.dominio_id))

    return selected_domain, selected_mailbox


def get_link_for_mailbox(db: Session, mailbox_id: int, message_id: int) -> CaixaMensagem:
    link = (
        db.query(CaixaMensagem)
        .options(joinedload(CaixaMensagem.mensagem), joinedload(CaixaMensagem.pasta))
        .filter(CaixaMensagem.caixa_email_id == mailbox_id, CaixaMensagem.mensagem_id == message_id)
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")
    return link


def get_links_for_mailbox_message_ids(db: Session, mailbox_id: int, message_ids: list[int]) -> list[CaixaMensagem]:
    clean_ids = [int(item) for item in message_ids if int(item) > 0]
    if not clean_ids:
        return []
    return (
        db.query(CaixaMensagem)
        .options(joinedload(CaixaMensagem.mensagem), joinedload(CaixaMensagem.pasta))
        .filter(CaixaMensagem.caixa_email_id == mailbox_id, CaixaMensagem.mensagem_id.in_(clean_ids))
        .all()
    )


def get_required_mailbox_secret(mailbox: CaixaEmail) -> str:
    smtp_password_enc = getattr(mailbox, "smtp_password_enc", None)
    logger.warning(
        "Recuperando segredo da caixa para IMAP/SMTP | mailbox_id=%s | email=%s | has_encrypted_secret=%s",
        mailbox.id,
        mailbox.email,
        bool(smtp_password_enc),
    )
    if not smtp_password_enc:
        raise HTTPException(
            status_code=500,
            detail="A caixa não possui senha criptografada para sincronização/envio. Redefina a senha da caixa.",
        )
    secret = decrypt_secret(smtp_password_enc)
    logger.warning(
        "Segredo descriptografado com sucesso | mailbox_id=%s | email=%s | secret_len=%s",
        mailbox.id,
        mailbox.email,
        len(secret or ""),
    )
    return secret


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
    scheduled_for: datetime | None = None,
    schedule_status: str = "none",
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
        scheduled_for=scheduled_for,
        schedule_status=schedule_status,
    )
    db.add(mensagem)
    db.flush()

    link = CaixaMensagem(
        caixa_email_id=mailbox.id,
        mensagem_id=mensagem.id,
        pasta_id=folder.id,
        is_read=True,
        is_starred=False,
        is_important=False,
        snoozed_until=None,
        is_deleted=(folder.slug == "trash"),
    )
    db.add(link)
    db.flush()
    return link


def get_existing_link_by_message_id(db: Session, *, mailbox_id: int, message_id_header: str) -> CaixaMensagem | None:
    normalized = normalize_message_id_header(message_id_header)
    if not normalized:
        return None
    return (
        db.query(CaixaMensagem)
        .options(joinedload(CaixaMensagem.mensagem), joinedload(CaixaMensagem.pasta))
        .join(Mensagem, CaixaMensagem.mensagem_id == Mensagem.id)
        .filter(
            CaixaMensagem.caixa_email_id == mailbox_id,
            func.lower(Mensagem.message_id_header) == normalized,
        )
        .first()
    )


def _merge_remote_data_into_message(*, mensagem: Mensagem, remote: RemoteMessage) -> bool:
    changed = False
    updates = [
        ("from_name", remote.from_name),
        ("from_email", remote.from_email),
        ("to_email", remote.to_email),
        ("cc_email", remote.cc_email),
        ("subject", remote.subject),
        ("preview", remote.preview),
        ("body_text", remote.body_text),
        ("body_html", remote.body_html),
        ("raw_source", remote.raw_source),
        ("sent_at", remote.sent_at),
    ]
    for attr, value in updates:
        current = getattr(mensagem, attr, None)
        if value is not None and current != value:
            setattr(mensagem, attr, value)
            changed = True
    return changed


def reconcile_existing_inbound_message(
    *,
    existing_link: CaixaMensagem,
    target_folder: Pasta,
    remote: RemoteMessage,
) -> tuple[bool, str | None]:
    changed = False
    previous_folder = existing_link.pasta.slug if existing_link.pasta else None

    preserve_local_folder = bool(
        previous_folder in {"trash", "junk"}
        and target_folder.slug in {"inbox", "junk"}
        and previous_folder != target_folder.slug
    )

    if not preserve_local_folder and int(existing_link.pasta_id) != int(target_folder.id):
        existing_link.pasta_id = target_folder.id
        changed = True

    desired_deleted = bool(existing_link.is_deleted) if preserve_local_folder else (target_folder.slug == "trash")
    if bool(existing_link.is_deleted) != desired_deleted:
        existing_link.is_deleted = desired_deleted
        changed = True

    desired_read = bool(remote.is_read)
    if bool(existing_link.is_read) != desired_read:
        existing_link.is_read = desired_read
        changed = True

    if existing_link.mensagem is not None and _merge_remote_data_into_message(mensagem=existing_link.mensagem, remote=remote):
        changed = True

    return changed, previous_folder


def save_inbound_message(*, db: Session, mailbox: CaixaEmail, target_folder: Pasta, remote: RemoteMessage) -> dict[str, Any]:
    normalized_message_id = normalize_message_id_header(remote.message_id_header)
    existing_link = get_existing_link_by_message_id(
        db,
        mailbox_id=mailbox.id,
        message_id_header=normalized_message_id or "",
    )
    if existing_link:
        changed, previous_folder = reconcile_existing_inbound_message(
            existing_link=existing_link,
            target_folder=target_folder,
            remote=remote,
        )
        return {"created": False, "updated": changed, "previous_folder": previous_folder}

    mensagem = Mensagem(
        empresa_id=mailbox.empresa_id,
        direction="inbound",
        message_id_header=normalized_message_id,
        from_name=remote.from_name,
        from_email=remote.from_email,
        to_email=remote.to_email,
        cc_email=remote.cc_email,
        subject=remote.subject,
        preview=remote.preview,
        body_text=remote.body_text,
        body_html=remote.body_html,
        raw_source=remote.raw_source,
        sent_at=remote.sent_at,
        scheduled_for=None,
        schedule_status="none",
    )
    db.add(mensagem)
    db.flush()

    link = CaixaMensagem(
        caixa_email_id=mailbox.id,
        mensagem_id=mensagem.id,
        pasta_id=target_folder.id,
        is_read=bool(remote.is_read),
        is_starred=False,
        is_important=False,
        snoozed_until=None,
        is_deleted=(target_folder.slug == "trash"),
    )
    db.add(link)
    db.flush()

    return {"created": True, "updated": False, "previous_folder": None}


def fetch_remote_messages_for_folder(*, imap_client: Any, email_address: str, password: str, folder_slug: str) -> list[RemoteMessage]:
    if hasattr(imap_client, "fetch_folder_messages"):
        return imap_client.fetch_folder_messages(email_address=email_address, password=password, folder_slug=folder_slug)
    if folder_slug == "inbox" and hasattr(imap_client, "fetch_inbox_messages"):
        return imap_client.fetch_inbox_messages(email_address=email_address, password=password)
    if folder_slug == "junk" and hasattr(imap_client, "fetch_junk_messages"):
        return imap_client.fetch_junk_messages(email_address=email_address, password=password)
    raise ImapSyncError(f"O cliente IMAP atual não suporta sincronização da pasta '{folder_slug}'.")


def sync_mailbox_folder(*, db: Session, mailbox: CaixaEmail, folder_slug: str) -> dict[str, int]:
    folder_slug = (folder_slug or "inbox").strip().lower()
    if not is_real_folder(folder_slug):
        raise HTTPException(status_code=400, detail="Só pastas reais podem ser sincronizadas.")

    logger.warning(
        "Iniciando sync IMAP | mailbox_id=%s | email=%s | folder=%s | is_active=%s",
        mailbox.id,
        mailbox.email,
        folder_slug,
        mailbox.is_active,
    )

    changed = ensure_default_folders(db, mailbox)
    logger.warning(
        "Pastas padrão verificadas | mailbox_id=%s | email=%s | changed=%s",
        mailbox.id,
        mailbox.email,
        changed,
    )

    folder_map = get_folder_map(db, mailbox.id)
    logger.warning(
        "Mapa de pastas carregado | mailbox_id=%s | email=%s | folders=%s",
        mailbox.id,
        mailbox.email,
        list(folder_map.keys()),
    )

    target_folder = folder_map.get(folder_slug)
    if not target_folder:
        raise HTTPException(status_code=500, detail=f"Pasta '{folder_slug}' não encontrada.")

    password = get_required_mailbox_secret(mailbox)
    imap_client = get_imap_client()

    logger.warning(
        "Cliente IMAP pronto para sync | mailbox_id=%s | email=%s | host=%s | port=%s | folder=%s | use_ssl=%s | use_starttls=%s | verify_ssl=%s | password_len=%s",
        mailbox.id,
        mailbox.email,
        getattr(imap_client, "host", None),
        getattr(imap_client, "port", None),
        folder_slug,
        getattr(imap_client, "use_ssl", None),
        getattr(imap_client, "use_starttls", None),
        getattr(imap_client, "verify_ssl", None),
        len(password or ""),
    )

    remote_messages = fetch_remote_messages_for_folder(
        imap_client=imap_client,
        email_address=mailbox.email,
        password=password,
        folder_slug=folder_slug,
    )

    logger.warning(
        "Mensagens remotas retornadas pelo IMAP | mailbox_id=%s | email=%s | folder=%s | total=%s",
        mailbox.id,
        mailbox.email,
        folder_slug,
        len(remote_messages),
    )

    created = 0
    updated = 0
    skipped = 0

    for remote in remote_messages:
        result = save_inbound_message(db=db, mailbox=mailbox, target_folder=target_folder, remote=remote)
        if result["created"]:
            created += 1
        elif result["updated"]:
            updated += 1
        else:
            skipped += 1

    if changed or created or updated:
        db.commit()

    return {
        "synced": len(remote_messages),
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def try_sync_mailbox_folder(*, db: Session, mailbox: CaixaEmail, folder_slug: str) -> tuple[dict[str, int] | None, str | None]:
    try:
        result = sync_mailbox_folder(db=db, mailbox=mailbox, folder_slug=folder_slug)
        return result, None
    except SecretCryptoError as exc:
        db.rollback()
        logger.exception("Erro de criptografia ao sincronizar IMAP | mailbox_id=%s | email=%s | folder=%s", mailbox.id, mailbox.email, folder_slug)
        return None, str(exc)
    except ImapSyncError as exc:
        db.rollback()
        logger.exception("Erro IMAP ao sincronizar pasta | mailbox_id=%s | email=%s | folder=%s", mailbox.id, mailbox.email, folder_slug)
        return None, f"Erro IMAP: {exc}"
    except HTTPException as exc:
        db.rollback()
        logger.exception(
            "HTTPException durante sync da pasta | mailbox_id=%s | email=%s | folder=%s | detail=%s",
            mailbox.id,
            mailbox.email,
            folder_slug,
            exc.detail,
        )
        return None, exc.detail if isinstance(exc.detail, str) else "Erro na sincronização."
    except Exception:
        db.rollback()
        logger.exception("Erro inesperado ao sincronizar pasta | mailbox_id=%s | email=%s | folder=%s", mailbox.id, mailbox.email, folder_slug)
        return None, "Erro inesperado ao sincronizar pasta."


def _link_message_id_header(link: CaixaMensagem) -> str | None:
    mensagem = getattr(link, "mensagem", None)
    if not mensagem:
        return None
    return normalize_message_id_header(getattr(mensagem, "message_id_header", None))


def move_links_on_remote_server(*, mailbox: CaixaEmail, links: list[CaixaMensagem], target_folder_slug: str) -> dict[str, int]:
    target_slug = (target_folder_slug or "inbox").strip().lower()
    if not is_real_folder(target_slug):
        raise ImapSyncError("Não é possível mover no servidor para uma pasta virtual.")

    password = get_required_mailbox_secret(mailbox)
    imap_client = get_imap_client()

    moved_total = 0
    skipped_missing = 0
    seen_message_ids: set[str] = set()

    for link in links:
        message_id_header = _link_message_id_header(link)
        if not message_id_header or message_id_header in seen_message_ids:
            continue
        seen_message_ids.add(message_id_header)

        result = imap_client.move_message_by_message_id(
            email_address=mailbox.email,
            password=password,
            message_id_header=message_id_header,
            target_folder=target_slug,
            preferred_source_folder=(link.pasta.slug if link.pasta else None),
        )

        if result.get("not_found"):
            skipped_missing += 1
            logger.warning(
                "Mensagem não encontrada remotamente para mover | mailbox_id=%s | email=%s | target_folder=%s | message_id=%s",
                mailbox.id,
                mailbox.email,
                target_slug,
                message_id_header,
            )
            if target_slug == "inbox":
                raise ImapSyncError("Não consegui localizar a mensagem no servidor IMAP para restaurar para a Entrada.")
            continue

        moved_total += int(result.get("moved_total") or 0)

    return {"moved_total": moved_total, "skipped_missing": skipped_missing}


def delete_links_on_remote_server(*, mailbox: CaixaEmail, links: list[CaixaMensagem]) -> dict[str, int]:
    password = get_required_mailbox_secret(mailbox)
    imap_client = get_imap_client()

    deleted_total = 0
    skipped_missing = 0
    seen_message_ids: set[str] = set()

    for link in links:
        message_id_header = _link_message_id_header(link)
        if not message_id_header or message_id_header in seen_message_ids:
            continue
        seen_message_ids.add(message_id_header)

        result = imap_client.delete_message_by_message_id(
            email_address=mailbox.email,
            password=password,
            message_id_header=message_id_header,
            preferred_folder=(link.pasta.slug if link.pasta else None),
        )

        if result.get("not_found"):
            skipped_missing += 1
            logger.warning(
                "Mensagem já não existia remotamente para exclusão definitiva | mailbox_id=%s | email=%s | message_id=%s",
                mailbox.id,
                mailbox.email,
                message_id_header,
            )
            continue

        deleted_total += int(result.get("deleted_total") or 0)

    return {"deleted_total": deleted_total, "skipped_missing": skipped_missing}


def delete_links_forever(db: Session, mailbox: CaixaEmail, links: list[CaixaMensagem]) -> tuple[int, int]:
    deleted_links = 0
    deleted_messages = 0

    for link in links:
        mensagem_id = int(link.mensagem_id)
        db.delete(link)
        db.flush()
        deleted_links += 1

        remaining_links = db.query(func.count(CaixaMensagem.id)).filter(CaixaMensagem.mensagem_id == mensagem_id).scalar() or 0
        if int(remaining_links) == 0:
            mensagem = db.query(Mensagem).filter(Mensagem.id == mensagem_id).first()
            if mensagem:
                db.delete(mensagem)
                db.flush()
                deleted_messages += 1

    return deleted_links, deleted_messages


def _fetch_due_scheduled_links(db: Session, limit: int) -> list[CaixaMensagem]:
    now = datetime.now(timezone.utc)
    return (
        db.query(CaixaMensagem)
        .options(
            joinedload(CaixaMensagem.mensagem),
            joinedload(CaixaMensagem.pasta),
            joinedload(CaixaMensagem.caixa_email).joinedload(CaixaEmail.dominio),
        )
        .join(Mensagem, CaixaMensagem.mensagem_id == Mensagem.id)
        .join(CaixaEmail, CaixaMensagem.caixa_email_id == CaixaEmail.id)
        .join(Empresa, Mensagem.empresa_id == Empresa.id)
        .filter(
            Mensagem.direction == "outbound",
            Mensagem.schedule_status == "scheduled",
            Mensagem.scheduled_for.is_not(None),
            Mensagem.scheduled_for <= now,
            CaixaEmail.is_active.is_(True),
            func.lower(Empresa.status) == "active",
        )
        .order_by(Mensagem.scheduled_for.asc(), CaixaMensagem.id.asc())
        .limit(limit)
        .all()
    )


def _dispatch_scheduled_link(db: Session, link: CaixaMensagem) -> None:
    mailbox = link.caixa_email
    mensagem = link.mensagem

    if mailbox is None or mensagem is None:
        raise RuntimeError("Mensagem agendada inválida.")

    ensure_default_folders(db, mailbox)
    folder_map = get_folder_map(db, mailbox.id)
    sent_folder = folder_map.get("sent")
    if sent_folder is None:
        raise RuntimeError(f"Pasta 'sent' não encontrada para {mailbox.email}.")

    smtp_password = get_required_mailbox_secret(mailbox)
    smtp_client = get_smtp_client()

    message_id_header = smtp_client.send_message(
        username=mailbox.email,
        password=smtp_password,
        from_email=mailbox.email,
        to_email=mensagem.to_email,
        subject=mensagem.subject,
        body_text=mensagem.body_text,
        from_name=mailbox.display_name or mailbox.local_part,
    )

    now = datetime.now(timezone.utc)

    mensagem.message_id_header = message_id_header or mensagem.message_id_header
    mensagem.sent_at = now
    mensagem.schedule_status = "sent"

    link.pasta_id = sent_folder.id
    link.is_deleted = False
    link.is_read = True


def run_due_scheduled_messages_once(limit: int = 25) -> dict[str, int]:
    db = SessionLocal()
    dispatched = 0
    failed = 0
    scanned = 0

    try:
        due_links = _fetch_due_scheduled_links(db, limit=limit)
        scanned = len(due_links)

        for link in due_links:
            try:
                _dispatch_scheduled_link(db, link)
                db.commit()
                dispatched += 1
                logger.warning(
                    "E-mail agendado enviado | mailbox_id=%s | email=%s | mensagem_id=%s",
                    getattr(link, "caixa_email_id", None),
                    getattr(getattr(link, "caixa_email", None), "email", None),
                    getattr(link, "mensagem_id", None),
                )
            except (SecretCryptoError, SmtpDeliveryError, RuntimeError) as exc:
                db.rollback()
                failed += 1
                logger.exception(
                    "Falha ao enviar e-mail agendado | mailbox_id=%s | email=%s | mensagem_id=%s | error=%s",
                    getattr(link, "caixa_email_id", None),
                    getattr(getattr(link, "caixa_email", None), "email", None),
                    getattr(link, "mensagem_id", None),
                    exc,
                )
            except Exception as exc:
                db.rollback()
                failed += 1
                logger.exception(
                    "Erro inesperado ao enviar e-mail agendado | mailbox_id=%s | email=%s | mensagem_id=%s | error=%s",
                    getattr(link, "caixa_email_id", None),
                    getattr(getattr(link, "caixa_email", None), "email", None),
                    getattr(link, "mensagem_id", None),
                    exc,
                )

        return {
            "scanned": scanned,
            "dispatched": dispatched,
            "failed": failed,
        }
    finally:
        db.close()


def _scheduled_sender_loop() -> None:
    poll_seconds = get_scheduler_poll_seconds()
    logger.warning("Worker de e-mails agendados iniciado | poll_seconds=%s", poll_seconds)

    while not _stop_event.is_set():
        try:
            result = run_due_scheduled_messages_once(limit=50)
            if result["scanned"] > 0:
                logger.warning(
                    "Ciclo do scheduler concluído | scanned=%s | dispatched=%s | failed=%s",
                    result["scanned"],
                    result["dispatched"],
                    result["failed"],
                )
        except Exception as exc:
            logger.exception("Erro no worker de e-mails agendados | error=%s", exc)

        _stop_event.wait(poll_seconds)

    logger.warning("Worker de e-mails agendados finalizado.")


def start_scheduled_sender() -> None:
    global _worker_thread

    if not is_scheduler_enabled():
        logger.warning("Worker de e-mails agendados desabilitado por variável de ambiente.")
        return

    if _worker_thread and _worker_thread.is_alive():
        return

    _stop_event.clear()
    _worker_thread = threading.Thread(
        target=_scheduled_sender_loop,
        name="auremail-scheduled-sender",
        daemon=True,
    )
    _worker_thread.start()


def stop_scheduled_sender() -> None:
    _stop_event.set()


@router.get("/context")
def webmail_context(
    dominio_id: int | None = Query(default=None),
    caixa_id: int | None = Query(default=None),
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    logger.warning(
        "ROTA /api/webmail/context EXECUTADA | dominio_id=%s | caixa_id=%s | actor_kind=%s",
        dominio_id,
        caixa_id,
        actor_kind(actor),
    )

    empresa_id = actor_empresa_id(actor)
    company = get_company(db, empresa_id)

    if actor_kind(actor) == "mailbox_user":
        current_actor_mailbox = actor_mailbox(actor)
        if not current_actor_mailbox:
            raise HTTPException(status_code=401, detail="Sessão de caixa inválida.")

        selected_mailbox = get_required_mailbox_for_company(
            db,
            empresa_id=empresa_id,
            mailbox_id=int(current_actor_mailbox.id),
            only_active=True,
        )
        selected_domain = selected_mailbox.dominio

        domains = [selected_domain] if selected_domain else []
        mailboxes = [selected_mailbox]

        return {
            "success": True,
            "auth_mode": "mailbox",
            "company": {
                "id": int(company.id) if company else None,
                "name": company.name if company else None,
                "status": company.status if company else None,
            },
            "user": None,
            "domains": [serialize_domain(item) for item in domains if item],
            "mailboxes": [serialize_mailbox(item) for item in mailboxes],
            "selected_domain_id": int(selected_domain.id) if selected_domain else None,
            "selected_mailbox_id": int(selected_mailbox.id),
        }

    domains = (
        db.query(Dominio)
        .filter(Dominio.empresa_id == empresa_id)
        .order_by(Dominio.is_primary.desc(), Dominio.id.asc())
        .all()
    )

    mailboxes = (
        db.query(CaixaEmail)
        .options(joinedload(CaixaEmail.dominio))
        .filter(CaixaEmail.empresa_id == empresa_id)
        .order_by(CaixaEmail.is_active.desc(), CaixaEmail.id.asc())
        .all()
    )

    selected_domain, selected_mailbox = resolve_selected_context(
        domains=domains,
        mailboxes=mailboxes,
        requested_domain_id=dominio_id,
        requested_mailbox_id=caixa_id,
    )

    platform_user = actor.get("platform_user")

    return {
        "success": True,
        "auth_mode": "platform",
        "company": {
            "id": int(company.id) if company else None,
            "name": company.name if company else None,
            "status": company.status if company else None,
        },
        "user": {
            "id": int(platform_user.id) if platform_user else None,
            "name": platform_user.name if platform_user else None,
            "email": platform_user.email if platform_user else None,
        },
        "domains": [serialize_domain(item) for item in domains],
        "mailboxes": [serialize_mailbox(item) for item in mailboxes],
        "selected_domain_id": int(selected_domain.id) if selected_domain else None,
        "selected_mailbox_id": int(selected_mailbox.id) if selected_mailbox else None,
    }


@router.post("/scheduled/run-now")
def run_scheduled_sender_now(actor: dict[str, Any] = Depends(get_current_mail_actor)):
    if actor_kind(actor) != "platform_user":
        raise HTTPException(
            status_code=403,
            detail="Somente usuário da plataforma pode disparar o envio programado manualmente.",
        )

    result = run_due_scheduled_messages_once(limit=100)
    return {
        "success": True,
        "message": "Fila de e-mails programados processada.",
        "result": result,
    }


@router.post("/mailboxes/{mailbox_id}/sync")
def sync_inbox_endpoint(
    mailbox_id: int,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    logger.warning(
        "Endpoint manual de sync chamado | mailbox_id=%s | actor_kind=%s | empresa_id=%s",
        mailbox_id,
        actor_kind(actor),
        actor_empresa_id(actor),
    )

    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=True)

    sync_results: dict[str, dict[str, int]] = {}
    sync_errors: dict[str, str] = {}

    for folder_slug in ("inbox", "junk"):
        stats, error = try_sync_mailbox_folder(db=db, mailbox=mailbox, folder_slug=folder_slug)
        if stats:
            sync_results[folder_slug] = stats
        if error:
            sync_errors[folder_slug] = error

    counts = build_folder_counts(db, mailbox.id)

    return {
        "success": True,
        "message": "Pastas sincronizadas.",
        "mailbox": serialize_mailbox(mailbox),
        "stats": sync_results,
        "sync_errors": sync_errors,
        "folder_counts": counts,
    }


@router.get("/mailboxes/{mailbox_id}/messages")
def list_messages(
    mailbox_id: int,
    folder: str = Query(default="inbox"),
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    sync: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    folder_slug = (folder or "inbox").strip().lower()
    if folder_slug not in ALL_FOLDERS:
        raise HTTPException(status_code=400, detail="Pasta inválida.")

    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)

    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    sync_stats: dict[str, int] | None = None
    sync_error: str | None = None

    if folder_slug in {"inbox", "junk"} and sync:
        logger.warning(
            "Listagem vai tentar sync automática da pasta | mailbox_id=%s | email=%s | folder=%s | sync=%s",
            mailbox.id,
            mailbox.email,
            folder_slug,
            sync,
        )
        sync_stats, sync_error = try_sync_mailbox_folder(db=db, mailbox=mailbox, folder_slug=folder_slug)

    query = (
        db.query(CaixaMensagem)
        .options(joinedload(CaixaMensagem.mensagem), joinedload(CaixaMensagem.pasta))
        .join(Mensagem, CaixaMensagem.mensagem_id == Mensagem.id)
        .join(Pasta, CaixaMensagem.pasta_id == Pasta.id)
        .filter(CaixaMensagem.caixa_email_id == mailbox.id)
    )

    query = apply_folder_filter(query, folder_slug)

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

    if folder_slug == "scheduled":
        items = query.order_by(
            desc(func.coalesce(Mensagem.scheduled_for, Mensagem.created_at)),
            desc(CaixaMensagem.id),
        ).all()
    else:
        items = query.order_by(
            desc(func.coalesce(Mensagem.sent_at, Mensagem.created_at)),
            desc(CaixaMensagem.id),
        ).all()

    if folder_slug == "inbox" and category:
        items = apply_category_filter(items, category)

    paged_items, page_meta = paginate_items(items, page=page, page_size=page_size)

    return {
        "success": True,
        "mailbox": serialize_mailbox(mailbox),
        "folder": folder_slug,
        "category": (category or "").strip().lower() or None,
        "folder_counts": build_folder_counts(db, mailbox.id),
        "items": [serialize_message_summary(item) for item in paged_items],
        "count": len(paged_items),
        "total": page_meta["total"],
        "page": page_meta["page"],
        "page_size": page_meta["page_size"],
        "total_pages": page_meta["total_pages"],
        "has_next": page_meta["has_next"],
        "has_prev": page_meta["has_prev"],
        "start_index": page_meta["start_index"],
        "end_index": page_meta["end_index"],
        "sync_stats": sync_stats,
        "sync_error": sync_error,
    }


@router.get("/mailboxes/{mailbox_id}/messages/{message_id}")
def message_detail(
    mailbox_id: int,
    message_id: int,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)
    return {"success": True, "mailbox": serialize_mailbox(mailbox), "item": serialize_message_detail(link)}


@router.post("/mailboxes/{mailbox_id}/messages/{message_id}/read")
def mark_message_as_read(
    mailbox_id: int,
    message_id: int,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)

    if not link.is_read:
        link.is_read = True
        db.commit()
        db.refresh(link)

    return {"success": True, "message": "Mensagem marcada como lida.", "item": serialize_message_detail(link)}


@router.post("/mailboxes/{mailbox_id}/messages/{message_id}/star")
def toggle_message_star(
    mailbox_id: int,
    message_id: int,
    data: ToggleFlagRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)

    link.is_starred = bool(data.value)
    db.commit()
    db.refresh(link)

    return {
        "success": True,
        "message": "Estrela atualizada com sucesso.",
        "item": serialize_message_detail(link),
        "folder_counts": build_folder_counts(db, mailbox.id),
    }


@router.post("/mailboxes/{mailbox_id}/messages/{message_id}/important")
def toggle_message_important(
    mailbox_id: int,
    message_id: int,
    data: ToggleFlagRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)

    link.is_important = bool(data.value)
    db.commit()
    db.refresh(link)

    return {
        "success": True,
        "message": "Importância atualizada com sucesso.",
        "item": serialize_message_detail(link),
        "folder_counts": build_folder_counts(db, mailbox.id),
    }


@router.post("/mailboxes/{mailbox_id}/messages/{message_id}/snooze")
def snooze_message(
    mailbox_id: int,
    message_id: int,
    data: SnoozeMessageRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)

    snoozed_until = data.snoozed_until
    if snoozed_until is not None and snoozed_until.tzinfo is None:
        snoozed_until = snoozed_until.replace(tzinfo=timezone.utc)

    link.snoozed_until = snoozed_until
    db.commit()
    db.refresh(link)

    return {
        "success": True,
        "message": "Adiamento atualizado com sucesso.",
        "item": serialize_message_detail(link),
        "folder_counts": build_folder_counts(db, mailbox.id),
    }


@router.post("/mailboxes/{mailbox_id}/messages/{message_id}/move")
def move_message(
    mailbox_id: int,
    message_id: int,
    data: MoveMessageRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    folder_map = get_folder_map(db, mailbox.id)
    target_slug = (data.target_folder or "").strip().lower()

    if target_slug not in REAL_FOLDERS:
        raise HTTPException(status_code=400, detail="Só é permitido mover para pastas reais.")

    if target_slug not in folder_map:
        raise HTTPException(status_code=400, detail="Pasta de destino inválida.")

    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)

    try:
        move_links_on_remote_server(mailbox=mailbox, links=[link], target_folder_slug=target_slug)
    except SecretCryptoError as exc:
        db.rollback()
        logger.exception("Erro de criptografia ao mover mensagem no IMAP | mailbox_id=%s | email=%s", mailbox.id, mailbox.email)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ImapSyncError as exc:
        db.rollback()
        logger.exception(
            "Falha ao mover mensagem no servidor IMAP | mailbox_id=%s | email=%s | message_id=%s | target_folder=%s",
            mailbox.id,
            mailbox.email,
            message_id,
            target_slug,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    link.pasta_id = folder_map[target_slug].id
    link.is_deleted = target_slug == "trash"

    if target_slug == "inbox":
        link.snoozed_until = None

    db.commit()
    db.refresh(link)

    return {
        "success": True,
        "message": "Mensagem movida com sucesso.",
        "item": serialize_message_detail(link),
        "folder_counts": build_folder_counts(db, mailbox.id),
    }


@router.post("/mailboxes/{mailbox_id}/messages/bulk-move")
def bulk_move_messages(
    mailbox_id: int,
    data: BulkMoveMessagesRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    folder_map = get_folder_map(db, mailbox.id)
    target_slug = (data.target_folder or "").strip().lower()

    if target_slug not in REAL_FOLDERS:
        raise HTTPException(status_code=400, detail="Só é permitido mover para pastas reais.")

    if target_slug not in folder_map:
        raise HTTPException(status_code=400, detail="Pasta de destino inválida.")

    links = get_links_for_mailbox_message_ids(db, mailbox.id, data.message_ids)
    if not links:
        raise HTTPException(status_code=404, detail="Nenhuma mensagem encontrada para mover.")

    try:
        move_links_on_remote_server(mailbox=mailbox, links=links, target_folder_slug=target_slug)
    except SecretCryptoError as exc:
        db.rollback()
        logger.exception("Erro de criptografia ao mover mensagens no IMAP | mailbox_id=%s | email=%s", mailbox.id, mailbox.email)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ImapSyncError as exc:
        db.rollback()
        logger.exception(
            "Falha ao mover mensagens no servidor IMAP | mailbox_id=%s | email=%s | target_folder=%s",
            mailbox.id,
            mailbox.email,
            target_slug,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    moved = 0
    for link in links:
        if int(link.pasta_id) != int(folder_map[target_slug].id) or bool(link.is_deleted) != (target_slug == "trash"):
            link.pasta_id = folder_map[target_slug].id
            link.is_deleted = target_slug == "trash"
            if target_slug == "inbox":
                link.snoozed_until = None
            moved += 1

    db.commit()

    return {
        "success": True,
        "message": "Mensagens movidas com sucesso.",
        "moved": moved,
        "found": len(links),
        "folder_counts": build_folder_counts(db, mailbox.id),
    }


@router.delete("/mailboxes/{mailbox_id}/messages/{message_id}")
def delete_message_forever(
    mailbox_id: int,
    message_id: int,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    link = get_link_for_mailbox(db, mailbox_id=mailbox.id, message_id=message_id)

    try:
        delete_links_on_remote_server(mailbox=mailbox, links=[link])
    except SecretCryptoError as exc:
        db.rollback()
        logger.exception("Erro de criptografia ao excluir mensagem no IMAP | mailbox_id=%s | email=%s", mailbox.id, mailbox.email)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ImapSyncError as exc:
        db.rollback()
        logger.exception(
            "Falha ao excluir mensagem no servidor IMAP | mailbox_id=%s | email=%s | message_id=%s",
            mailbox.id,
            mailbox.email,
            message_id,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    deleted_links, deleted_messages = delete_links_forever(db, mailbox, [link])
    db.commit()

    return {
        "success": True,
        "message": "Mensagem excluída permanentemente.",
        "deleted_links": deleted_links,
        "deleted_messages": deleted_messages,
        "folder_counts": build_folder_counts(db, mailbox.id),
    }


@router.post("/mailboxes/{mailbox_id}/messages/bulk-delete")
def bulk_delete_messages(
    mailbox_id: int,
    data: BulkDeleteMessagesRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=False)
    links = get_links_for_mailbox_message_ids(db, mailbox.id, data.message_ids)
    if not links:
        raise HTTPException(status_code=404, detail="Nenhuma mensagem encontrada para excluir.")

    try:
        delete_links_on_remote_server(mailbox=mailbox, links=links)
    except SecretCryptoError as exc:
        db.rollback()
        logger.exception("Erro de criptografia ao excluir mensagens no IMAP | mailbox_id=%s | email=%s", mailbox.id, mailbox.email)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ImapSyncError as exc:
        db.rollback()
        logger.exception("Falha ao excluir mensagem no servidor IMAP | mailbox_id=%s | email=%s", mailbox.id, mailbox.email)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    deleted_links, deleted_messages = delete_links_forever(db, mailbox, links)
    db.commit()

    return {
        "success": True,
        "message": "Mensagens excluídas permanentemente.",
        "deleted_links": deleted_links,
        "deleted_messages": deleted_messages,
        "folder_counts": build_folder_counts(db, mailbox.id),
    }


@router.post("/mailboxes/{mailbox_id}/compose", status_code=status.HTTP_201_CREATED)
def compose_message(
    mailbox_id: int,
    data: ComposeRequest,
    actor: dict[str, Any] = Depends(get_current_mail_actor),
    db: Session = Depends(get_db),
):
    mailbox = get_accessible_mailbox(db, actor=actor, mailbox_id=mailbox_id, only_active=True)
    changed = ensure_default_folders(db, mailbox)
    if changed:
        db.commit()

    folder_map = get_folder_map(db, mailbox.id)

    to_email = normalize_email_address(data.to)
    subject = normalize_text(data.subject)
    body = normalize_text(data.body)

    if not to_email:
        raise HTTPException(status_code=400, detail="Informe o destinatário.")

    if data.save_as_draft and data.save_as_scheduled:
        raise HTTPException(status_code=400, detail="Escolha apenas um modo: rascunho ou programado.")

    try:
        if data.save_as_scheduled:
            if not data.scheduled_for:
                raise HTTPException(status_code=400, detail="Informe a data/hora do agendamento.")

            scheduled_for = data.scheduled_for
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

            folder = folder_map.get("drafts")
            if not folder:
                raise HTTPException(status_code=400, detail="Pasta de rascunhos não encontrada.")

            message_id_header = f"<auremail-scheduled-{uuid4().hex}@local>"
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
                scheduled_for=scheduled_for,
                schedule_status="scheduled",
            )
            db.commit()
            db.refresh(link)

            return {
                "success": True,
                "message": "E-mail programado salvo com sucesso.",
                "item": serialize_message_detail(link),
                "folder_counts": build_folder_counts(db, mailbox.id),
            }

        if data.save_as_draft:
            folder = folder_map.get("drafts")
            if not folder:
                raise HTTPException(status_code=400, detail="Pasta de rascunhos não encontrada.")

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
                scheduled_for=None,
                schedule_status="none",
            )
            db.commit()
            db.refresh(link)

            return {
                "success": True,
                "message": "Rascunho salvo com sucesso.",
                "item": serialize_message_detail(link),
                "folder_counts": build_folder_counts(db, mailbox.id),
            }

        folder = folder_map.get("sent")
        if not folder:
            raise HTTPException(status_code=400, detail="Pasta de envio não encontrada.")

        smtp_password = get_required_mailbox_secret(mailbox)
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
            scheduled_for=None,
            schedule_status="sent",
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
        logger.exception("Erro de criptografia ao enviar e-mail | mailbox_id=%s | email=%s", mailbox.id, mailbox.email)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except SmtpDeliveryError as exc:
        db.rollback()
        logger.exception("Erro SMTP ao enviar e-mail | mailbox_id=%s | email=%s", mailbox.id, mailbox.email)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Erro inesperado ao enviar e-mail | mailbox_id=%s | email=%s", mailbox.id, mailbox.email)
        raise HTTPException(status_code=500, detail="Erro inesperado ao enviar e-mail.") from exc