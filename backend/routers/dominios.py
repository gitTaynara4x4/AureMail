import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.integrations.stalwart_client import (
    StalwartProvisioningError,
    get_stalwart_client,
)
from backend.models import Dominio, UsuarioPlataforma
from backend.routers.auth import get_current_user


router = APIRouter(prefix="/api/dominios", tags=["Domínios"])

DOMAIN_REGEX = re.compile(
    r"^(?=.{1,255}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


def _env_str(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def _env_lower(name: str, default: str = "") -> str:
    return _env_str(name, default).lower()


def _env_dns_ttl() -> str:
    raw = _env_str("AUREMAIL_DNS_TTL", "3600")
    try:
        value = int(raw)
    except ValueError:
        return "3600"

    if value <= 0:
        return "3600"

    return str(value)


AUREMAIL_PUBLIC_IP = _env_str("AUREMAIL_PUBLIC_IP")
AUREMAIL_PANEL_PUBLIC_HOST = _env_lower("AUREMAIL_PANEL_PUBLIC_HOST")
AUREMAIL_MAIL_SERVER_HOST = _env_lower("AUREMAIL_MAIL_SERVER_HOST")
AUREMAIL_DKIM_SELECTOR = _env_lower("AUREMAIL_DKIM_SELECTOR", "default") or "default"
AUREMAIL_DKIM_PUBLIC_KEY = _env_str("AUREMAIL_DKIM_PUBLIC_KEY")
AUREMAIL_DMARC_REPORT_LOCAL_PART = _env_lower("AUREMAIL_DMARC_REPORT_LOCAL_PART", "dmarc") or "dmarc"
AUREMAIL_DNS_TTL = _env_dns_ttl()


class DomainCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    status: str = Field(default="pending", max_length=20)
    is_primary: bool = False


class DomainUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=255)
    status: str | None = Field(default=None, max_length=20)
    is_primary: bool | None = None


class DomainProvisionRequest(BaseModel):
    generate_dkim: bool = False


def normalize_domain_name(value: str) -> str:
    domain = (value or "").strip().lower()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.split("/")[0]
    domain = domain.split("?")[0]
    domain = domain.split("#")[0]
    domain = domain.strip(".")
    return domain


def validate_domain_name(value: str) -> bool:
    return bool(DOMAIN_REGEX.match(normalize_domain_name(value)))


def normalize_status(value: str) -> str:
    status_value = (value or "").strip().lower()
    allowed = {"pending", "active", "inactive", "error"}
    return status_value if status_value in allowed else "pending"


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


def get_domain_by_name_for_company(
    db: Session,
    empresa_id: int,
    domain_name: str,
    except_id: int | None = None,
) -> Dominio | None:
    query = db.query(Dominio).filter(
        Dominio.empresa_id == empresa_id,
        Dominio.name == domain_name,
    )
    if except_id is not None:
        query = query.filter(Dominio.id != except_id)
    return query.first()


def unset_other_primary_domains(
    db: Session,
    empresa_id: int,
    except_id: int | None = None,
) -> None:
    query = db.query(Dominio).filter(Dominio.empresa_id == empresa_id)
    if except_id is not None:
        query = query.filter(Dominio.id != except_id)
    query.update({Dominio.is_primary: False}, synchronize_session=False)


def get_fallback_domain(
    db: Session,
    empresa_id: int,
    except_id: int | None = None,
) -> Dominio | None:
    query = db.query(Dominio).filter(Dominio.empresa_id == empresa_id)
    if except_id is not None:
        query = query.filter(Dominio.id != except_id)
    return query.order_by(Dominio.created_at.asc(), Dominio.id.asc()).first()


def build_spf_value() -> str:
    if not AUREMAIL_MAIL_SERVER_HOST:
        return "CONFIGURE AUREMAIL_MAIL_SERVER_HOST"
    return f"v=spf1 mx a:{AUREMAIL_MAIL_SERVER_HOST} ~all"


def build_dmarc_email(domain_name: str) -> str:
    return f"{AUREMAIL_DMARC_REPORT_LOCAL_PART}@{domain_name}"


def build_dmarc_value(domain_name: str) -> str:
    rua = build_dmarc_email(domain_name)
    return f"v=DMARC1; p=none; rua=mailto:{rua}; adkim=s; aspf=s; pct=100"


def normalize_host_value(value: str) -> str:
    return str(value or "").strip().rstrip(".").lower()


def normalize_mx_value(value: str) -> str:
    text = str(value or "").strip().lower().rstrip(".")
    return re.sub(r"\s+", " ", text)


def normalize_txt_value(value: str) -> str:
    text = str(value or "").strip()
    parts = re.findall(r'"([^"]*)"', text)
    if parts:
        text = "".join(parts)
    return text.replace('"', "").strip()


def doh_lookup(name: str, record_type: str) -> list[str]:
    query = urllib.parse.urlencode({"name": name, "type": record_type})
    url = f"https://dns.google/resolve?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AureMail/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    answers = payload.get("Answer") or []
    return [str(item.get("data", "")) for item in answers if item.get("data")]


def build_dns_records(domain_name: str) -> list[dict[str, Any]]:
    dkim_host = f"{AUREMAIL_DKIM_SELECTOR}._domainkey.{domain_name}"
    has_dkim_key = bool(AUREMAIL_DKIM_PUBLIC_KEY)

    mx_value = (
        f"10 {AUREMAIL_MAIL_SERVER_HOST}"
        if AUREMAIL_MAIL_SERVER_HOST
        else "CONFIGURE AUREMAIL_MAIL_SERVER_HOST"
    )
    spf_value = build_spf_value()
    dmarc_value = build_dmarc_value(domain_name)

    return [
        {
            "key": "mx",
            "label": "Entrada de e-mail",
            "description": "Registro MX do domínio principal apontando para o servidor central do AureMail.",
            "type": "MX",
            "host": "@",
            "fqdn": domain_name,
            "value": mx_value,
            "display_value": mx_value,
            "copy_value": "" if mx_value.startswith("CONFIGURE ") else mx_value,
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
        {
            "key": "spf",
            "label": "SPF",
            "description": "Autoriza o servidor central do AureMail a enviar pelo domínio.",
            "type": "TXT",
            "host": "@",
            "fqdn": domain_name,
            "value": spf_value,
            "display_value": spf_value,
            "copy_value": "" if spf_value.startswith("CONFIGURE ") else spf_value,
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
        {
            "key": "dmarc",
            "label": "DMARC",
            "description": "Política inicial de autenticação e relatórios.",
            "type": "TXT",
            "host": "_dmarc",
            "fqdn": f"_dmarc.{domain_name}",
            "value": dmarc_value,
            "display_value": dmarc_value,
            "copy_value": dmarc_value,
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
        {
            "key": "dkim",
            "label": "DKIM",
            "description": "Chave pública do domínio para assinatura DKIM.",
            "type": "TXT",
            "host": f"{AUREMAIL_DKIM_SELECTOR}._domainkey",
            "fqdn": dkim_host,
            "value": AUREMAIL_DKIM_PUBLIC_KEY,
            "display_value": (
                AUREMAIL_DKIM_PUBLIC_KEY
                or "GERAR CHAVE DKIM NO STALWART E PREENCHER AUREMAIL_DKIM_PUBLIC_KEY"
            ),
            "copy_value": AUREMAIL_DKIM_PUBLIC_KEY or "",
            "ttl": AUREMAIL_DNS_TTL,
            "required": has_dkim_key,
        },
    ]


def build_dns_setup_payload(domain: Dominio) -> dict[str, Any]:
    domain_name = domain.name
    warnings: list[str] = []

    if not AUREMAIL_MAIL_SERVER_HOST:
        warnings.append(
            "A variável AUREMAIL_MAIL_SERVER_HOST ainda não está configurada no backend. "
            "Sem ela, o MX e o SPF ficam incompletos."
        )

    if not AUREMAIL_PANEL_PUBLIC_HOST:
        warnings.append(
            "A variável AUREMAIL_PANEL_PUBLIC_HOST ainda não está configurada. "
            "Ela é usada apenas como referência do painel, não como registro DNS do cliente."
        )

    if not AUREMAIL_DKIM_PUBLIC_KEY:
        warnings.append(
            "A variável AUREMAIL_DKIM_PUBLIC_KEY ainda está vazia. "
            "Preencha isso depois de gerar a chave pública DKIM no Stalwart."
        )

    return {
        "success": True,
        "domain": serialize_domain(domain),
        "generated": {
            "public_ip": AUREMAIL_PUBLIC_IP or None,
            "panel_public_host": AUREMAIL_PANEL_PUBLIC_HOST or None,
            "mail_server_host": AUREMAIL_MAIL_SERVER_HOST or None,
            "app_subdomain": AUREMAIL_PANEL_PUBLIC_HOST or None,
            "mail_subdomain": AUREMAIL_MAIL_SERVER_HOST or None,
            "app_host": AUREMAIL_PANEL_PUBLIC_HOST or None,
            "mail_host": AUREMAIL_MAIL_SERVER_HOST or None,
            "dkim_selector": AUREMAIL_DKIM_SELECTOR,
            "dmarc_report_email": build_dmarc_email(domain_name),
        },
        "records": build_dns_records(domain_name),
        "warnings": warnings,
        "steps": [
            "O cliente não precisa criar mail.seu-dominio.com nem painel.seu-dominio.com.",
            "No provedor DNS do domínio, crie apenas os registros mostrados na tabela.",
            "O MX do cliente deve apontar para o servidor central do AureMail.",
            "Depois de salvar os registros, aguarde a propagação DNS e clique em Verificar DNS.",
            "Quando os registros obrigatórios estiverem corretos, siga para a criação das caixas de e-mail.",
        ],
    }


def verify_single_record(record: dict[str, Any]) -> dict[str, Any]:
    expected_value = str(record.get("value") or "").strip()
    record_type = str(record.get("type") or "").upper()
    fqdn = str(record.get("fqdn") or "").strip()
    key = str(record.get("key") or "").strip()

    if not expected_value or expected_value.startswith("CONFIGURE "):
        return {
            "key": key,
            "status": "pending_config",
            "expected_value": expected_value,
            "found_values": [],
            "message": "Valor ainda não configurado no backend.",
        }

    if record_type == "MX":
        found_values = doh_lookup(fqdn, "MX")
        expected_normalized = normalize_mx_value(expected_value)
        found_normalized = [normalize_mx_value(item) for item in found_values]
        matched = expected_normalized in found_normalized
    elif record_type == "TXT":
        found_values = doh_lookup(fqdn, "TXT")
        expected_normalized = normalize_txt_value(expected_value)
        found_normalized = [normalize_txt_value(item) for item in found_values]
        matched = expected_normalized in found_normalized
    else:
        found_values = []
        matched = False

    return {
        "key": key,
        "status": "ok" if matched else "error",
        "expected_value": expected_value,
        "found_values": found_values,
        "message": "Registro encontrado." if matched else "Registro ainda não bate com o esperado.",
    }


def maybe_provision_domain(domain_name: str) -> None:
    client = get_stalwart_client()
    if not client.enabled:
        return

    client.create_domain(
        domain_name,
        description=f"Domínio gerado pelo AureMail: {domain_name}",
    )


@router.get("")
def list_domains(
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domains = (
        db.query(Dominio)
        .filter(Dominio.empresa_id == current_user.empresa_id)
        .order_by(Dominio.is_primary.desc(), Dominio.created_at.asc(), Dominio.id.asc())
        .all()
    )

    return {
        "success": True,
        "items": [serialize_domain(item) for item in domains],
        "count": len(domains),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_domain(
    data: DomainCreateRequest,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domain_name = normalize_domain_name(data.name)
    if not validate_domain_name(domain_name):
        raise HTTPException(status_code=400, detail="Informe um domínio válido.")

    existing = get_domain_by_name_for_company(db, current_user.empresa_id, domain_name)
    if existing:
        raise HTTPException(status_code=409, detail="Esse domínio já está cadastrado.")

    status_value = normalize_status(data.status)
    has_any = (
        db.query(Dominio)
        .filter(Dominio.empresa_id == current_user.empresa_id)
        .first()
    )
    make_primary = bool(data.is_primary or not has_any)

    if make_primary:
        unset_other_primary_domains(db, current_user.empresa_id)

    domain = Dominio(
        empresa_id=current_user.empresa_id,
        name=domain_name,
        status=status_value,
        is_primary=make_primary,
    )
    db.add(domain)

    try:
        db.flush()
        maybe_provision_domain(domain_name)
        db.commit()
        db.refresh(domain)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Esse domínio já está cadastrado.")
    except StalwartProvisioningError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "Domínio cadastrado com sucesso.",
        "item": serialize_domain(domain),
    }


@router.patch("/{domain_id}")
def update_domain(
    domain_id: int,
    data: DomainUpdateRequest,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domain = get_domain_for_user(db, domain_id, current_user.empresa_id)
    old_domain_name = domain.name
    was_primary = bool(domain.is_primary)

    if data.name is not None:
        domain_name = normalize_domain_name(data.name)
        if not validate_domain_name(domain_name):
            raise HTTPException(status_code=400, detail="Informe um domínio válido.")

        existing = get_domain_by_name_for_company(
            db,
            current_user.empresa_id,
            domain_name,
            except_id=domain.id,
        )
        if existing:
            raise HTTPException(status_code=409, detail="Esse domínio já está cadastrado.")

        domain.name = domain_name

    if data.status is not None:
        domain.status = normalize_status(data.status)

    if data.is_primary is True:
        unset_other_primary_domains(db, current_user.empresa_id, except_id=domain.id)
        domain.is_primary = True
    elif data.is_primary is False and was_primary:
        fallback = get_fallback_domain(db, current_user.empresa_id, except_id=domain.id)
        if fallback:
            domain.is_primary = False
            fallback.is_primary = True
        else:
            domain.is_primary = True

    try:
        db.flush()

        client = get_stalwart_client()
        if client.enabled and old_domain_name != domain.name:
            client.rename_domain(old_domain_name, domain.name)

        db.commit()
        db.refresh(domain)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Esse domínio já está cadastrado.")
    except StalwartProvisioningError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "Domínio atualizado com sucesso.",
        "item": serialize_domain(domain),
    }


@router.post("/{domain_id}/primary")
def set_primary_domain(
    domain_id: int,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domain = get_domain_for_user(db, domain_id, current_user.empresa_id)

    unset_other_primary_domains(db, current_user.empresa_id, except_id=domain.id)
    domain.is_primary = True

    db.commit()
    db.refresh(domain)

    return {
        "success": True,
        "message": "Domínio principal definido com sucesso.",
        "item": serialize_domain(domain),
    }


@router.delete("/{domain_id}")
def delete_domain(
    domain_id: int,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domain = get_domain_for_user(db, domain_id, current_user.empresa_id)
    was_primary = bool(domain.is_primary)
    deleted_item = serialize_domain(domain)

    try:
        db.delete(domain)
        db.flush()

        if was_primary:
            fallback = get_fallback_domain(db, current_user.empresa_id)
            if fallback:
                fallback.is_primary = True

        client = get_stalwart_client()
        if client.enabled:
            client.delete_domain(domain.name)

        db.commit()
    except StalwartProvisioningError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "Domínio removido com sucesso.",
        "deleted": deleted_item,
    }


@router.get("/{domain_id}/dns-setup")
def domain_dns_setup(
    domain_id: int,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domain = get_domain_for_user(db, domain_id, current_user.empresa_id)
    return build_dns_setup_payload(domain)


@router.post("/{domain_id}/verify-dns")
def verify_domain_dns(
    domain_id: int,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domain = get_domain_for_user(db, domain_id, current_user.empresa_id)
    payload = build_dns_setup_payload(domain)
    records = payload.get("records", [])
    verification_results = [verify_single_record(record) for record in records]

    required_keys = {record["key"] for record in records if record.get("required")}
    required_ok = all(
        item.get("status") == "ok"
        for item in verification_results
        if item.get("key") in required_keys
    )

    if required_ok:
        domain.status = "active"
    elif domain.status != "inactive":
        domain.status = "pending"

    db.commit()
    db.refresh(domain)

    return {
        "success": True,
        "domain": serialize_domain(domain),
        "records": verification_results,
        "all_required_ok": required_ok,
    }


@router.post("/{domain_id}/provision")
def provision_domain_on_stalwart(
    domain_id: int,
    _: DomainProvisionRequest,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domain = get_domain_for_user(db, domain_id, current_user.empresa_id)

    try:
        maybe_provision_domain(domain.name)
    except StalwartProvisioningError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "Domínio provisionado no servidor de e-mail.",
        "item": serialize_domain(domain),
    }