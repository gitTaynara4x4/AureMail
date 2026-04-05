import json
import os
import re
import urllib.parse
import urllib.request

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

AUREMAIL_PUBLIC_IP = os.getenv("AUREMAIL_PUBLIC_IP", "").strip()
AUREMAIL_PANEL_PUBLIC_HOST = os.getenv("AUREMAIL_PANEL_PUBLIC_HOST", "").strip().lower()
AUREMAIL_MAIL_SERVER_HOST = os.getenv("AUREMAIL_MAIL_SERVER_HOST", "").strip().lower()
AUREMAIL_DKIM_SELECTOR = os.getenv("AUREMAIL_DKIM_SELECTOR", "default").strip().lower()
AUREMAIL_DKIM_PUBLIC_KEY = os.getenv("AUREMAIL_DKIM_PUBLIC_KEY", "").strip()
AUREMAIL_DMARC_REPORT_LOCAL_PART = os.getenv("AUREMAIL_DMARC_REPORT_LOCAL_PART", "dmarc").strip().lower()
AUREMAIL_DNS_TTL = os.getenv("AUREMAIL_DNS_TTL", "3600").strip() or "3600"


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
    domain = domain.strip(".")
    return domain


def validate_domain_name(value: str) -> bool:
    return bool(DOMAIN_REGEX.match(normalize_domain_name(value)))


def normalize_status(value: str) -> str:
    status_value = (value or "").strip().lower()
    allowed = {"pending", "active", "inactive", "error"}
    return status_value if status_value in allowed else "pending"


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


def unset_other_primary_domains(db: Session, empresa_id: int, except_id: int | None = None) -> None:
    query = db.query(Dominio).filter(Dominio.empresa_id == empresa_id)
    if except_id is not None:
        query = query.filter(Dominio.id != except_id)
    query.update({Dominio.is_primary: False}, synchronize_session=False)


def get_fallback_domain(db: Session, empresa_id: int, except_id: int | None = None) -> Dominio | None:
    query = db.query(Dominio).filter(Dominio.empresa_id == empresa_id)
    if except_id is not None:
        query = query.filter(Dominio.id != except_id)
    return query.order_by(Dominio.created_at.asc(), Dominio.id.asc()).first()


def build_spf_value() -> str:
    if not AUREMAIL_MAIL_SERVER_HOST:
        return "CONFIGURE AUREMAIL_MAIL_SERVER_HOST"
    return f"v=spf1 mx a:{AUREMAIL_MAIL_SERVER_HOST} ~all"


def build_dmarc_email(domain_name: str) -> str:
    local_part = AUREMAIL_DMARC_REPORT_LOCAL_PART or "dmarc"
    return f"{local_part}@{domain_name}"


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
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    answers = payload.get("Answer") or []
    return [str(item.get("data", "")) for item in answers]


def build_dns_records(domain_name: str) -> list[dict]:
    dkim_host = f"{AUREMAIL_DKIM_SELECTOR}._domainkey.{domain_name}"
    has_dkim_key = bool(AUREMAIL_DKIM_PUBLIC_KEY)
    records = [
        {
            "key": "mx",
            "label": "Entrada de e-mail",
            "description": "Registro MX do domínio principal apontando para o servidor central do AureMail",
            "type": "MX",
            "host": "@",
            "fqdn": domain_name,
            "value": f"10 {AUREMAIL_MAIL_SERVER_HOST}",
            "display_value": f"10 {AUREMAIL_MAIL_SERVER_HOST}" if AUREMAIL_MAIL_SERVER_HOST else "CONFIGURE AUREMAIL_MAIL_SERVER_HOST",
            "copy_value": f"10 {AUREMAIL_MAIL_SERVER_HOST}" if AUREMAIL_MAIL_SERVER_HOST else "",
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
        {
            "key": "spf",
            "label": "SPF",
            "description": "Autoriza o servidor central do AureMail a enviar pelo domínio",
            "type": "TXT",
            "host": "@",
            "fqdn": domain_name,
            "value": build_spf_value(),
            "display_value": build_spf_value(),
            "copy_value": build_spf_value() if AUREMAIL_MAIL_SERVER_HOST else "",
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
        {
            "key": "dmarc",
            "label": "DMARC",
            "description": "Política inicial de autenticação e relatórios",
            "type": "TXT",
            "host": "_dmarc",
            "fqdn": f"_dmarc.{domain_name}",
            "value": build_dmarc_value(domain_name),
            "display_value": build_dmarc_value(domain_name),
            "copy_value": build_dmarc_value(domain_name),
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
        {
            "key": "dkim",
            "label": "DKIM",
            "description": "Chave pública do domínio para assinatura DKIM",
            "type": "TXT",
            "host": f"{AUREMAIL_DKIM_SELECTOR}._domainkey",
            "fqdn": dkim_host,
            "value": AUREMAIL_DKIM_PUBLIC_KEY,
            "display_value": AUREMAIL_DKIM_PUBLIC_KEY or "GERAR CHAVE DKIM NO STALWART E PREENCHER AUREMAIL_DKIM_PUBLIC_KEY",
            "copy_value": AUREMAIL_DKIM_PUBLIC_KEY or "",
            "ttl": AUREMAIL_DNS_TTL,
            "required": has_dkim_key,
        },
    ]
    return records


def build_dns_setup_payload(domain: Dominio) -> dict:
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
            "Ela é usada só como referência do painel web, não como registro DNS do cliente."
        )
    if not AUREMAIL_DKIM_PUBLIC_KEY:
        warnings.append(
            "A variável AUREMAIL_DKIM_PUBLIC_KEY ainda está vazia. "
            "Você vai preencher isso depois de gerar a chave pública DKIM no Stalwart."
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
            "O cliente não precisa criar mail.cliente.com nem painel.cliente.com.",
            "No provedor DNS do domínio, crie apenas os registros mostrados na tabela.",
            "O MX do cliente deve apontar para o servidor central do AureMail.",
            "Depois de salvar os registros, aguarde a propagação DNS e clique em Verificar DNS.",
            "Quando os registros obrigatórios estiverem corretos, siga para a criação das caixas de e-mail.",
        ],
    }


def verify_single_record(record: dict) -> dict:
    expected_value = record.get("value") or ""
    record_type = (record.get("type") or "").upper()
    fqdn = record.get("fqdn") or ""
    key = record.get("key") or ""

    if not expected_value or str(expected_value).startswith("CONFIGURE "):
        return {
            "key": key,
            "status": "pending_config",
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
        "found_values": found_values,
        "message": "Registro encontrado." if matched else "Registro ainda não bate com o esperado.",
    }


def maybe_provision_domain(domain_name: str) -> None:
    client = get_stalwart_client()
    if not client.enabled:
        return
    client.create_domain(domain_name, description=f"Domínio gerado pelo AureMail: {domain_name}")


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
    return {"success": True, "items": [serialize_domain(item) for item in domains], "count": len(domains)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_domain(
    data: DomainCreateRequest,
    current_user: UsuarioPlataforma = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    domain_name = normalize_domain_name(data.name)
    if not validate_domain_name(domain_name):
        raise HTTPException(status_code=400, detail="Informe um domínio válido.")

    status_value = normalize_status(data.status)
    has_any = db.query(Dominio).filter(Dominio.empresa_id == current_user.empresa_id).first()
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
    was_primary = bool(domain.is_primary)
    old_domain_name = domain.name

    if data.name is not None:
        domain_name = normalize_domain_name(data.name)
        if not validate_domain_name(domain_name):
            raise HTTPException(status_code=400, detail="Informe um domínio válido.")
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
    return {"success": True, "message": "Domínio principal definido com sucesso.", "item": serialize_domain(domain)}


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
        client = get_stalwart_client()
        if client.enabled:
            client.delete_domain(domain.name)
        db.delete(domain)
        db.flush()
        if was_primary:
            fallback = get_fallback_domain(db, current_user.empresa_id)
            if fallback:
                fallback.is_primary = True
        db.commit()
    except StalwartProvisioningError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"success": True, "message": "Domínio removido com sucesso.", "deleted": deleted_item}


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

    domain.status = "active" if required_ok else (domain.status if domain.status == "inactive" else "pending")
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
