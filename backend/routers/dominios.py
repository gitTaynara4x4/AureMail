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
from backend.models import Dominio, UsuarioPlataforma
from backend.routers.auth import get_current_user


router = APIRouter(prefix="/api/dominios", tags=["Domínios"])


DOMAIN_REGEX = re.compile(
    r"^(?=.{1,255}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

AUREMAIL_PUBLIC_IP = os.getenv("AUREMAIL_PUBLIC_IP", "").strip()
AUREMAIL_APP_SUBDOMAIN = os.getenv("AUREMAIL_APP_SUBDOMAIN", "auremail").strip().lower()
AUREMAIL_MAIL_SUBDOMAIN = os.getenv("AUREMAIL_MAIL_SUBDOMAIN", "mail").strip().lower()
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
    allowed = {"pending", "active", "inactive"}
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

    return (
        query.order_by(
            Dominio.created_at.asc(),
            Dominio.id.asc(),
        )
        .first()
    )


def build_app_host(domain_name: str) -> str:
    return f"{AUREMAIL_APP_SUBDOMAIN}.{domain_name}" if AUREMAIL_APP_SUBDOMAIN else domain_name


def build_mail_host(domain_name: str) -> str:
    return f"{AUREMAIL_MAIL_SUBDOMAIN}.{domain_name}" if AUREMAIL_MAIL_SUBDOMAIN else domain_name


def build_spf_value(domain_name: str) -> str:
    mail_host = build_mail_host(domain_name)
    return f"v=spf1 mx a:{mail_host} ~all"


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
    text = re.sub(r"\s+", " ", text)
    return text


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
    app_host = build_app_host(domain_name)
    mail_host = build_mail_host(domain_name)
    dkim_host = f"{AUREMAIL_DKIM_SELECTOR}._domainkey.{domain_name}"

    records = [
        {
            "key": "app_a",
            "label": "Painel do AureMail",
            "description": "Subdomínio do painel/app web",
            "type": "A",
            "host": AUREMAIL_APP_SUBDOMAIN or "@",
            "fqdn": app_host,
            "value": AUREMAIL_PUBLIC_IP,
            "display_value": AUREMAIL_PUBLIC_IP or "CONFIGURE AUREMAIL_PUBLIC_IP",
            "copy_value": AUREMAIL_PUBLIC_IP or "",
            "ttl": AUREMAIL_DNS_TTL,
            "required": False,
        },
        {
            "key": "mail_a",
            "label": "Servidor de e-mail",
            "description": "Host usado pelo MX e pelo PTR",
            "type": "A",
            "host": AUREMAIL_MAIL_SUBDOMAIN or "@",
            "fqdn": mail_host,
            "value": AUREMAIL_PUBLIC_IP,
            "display_value": AUREMAIL_PUBLIC_IP or "CONFIGURE AUREMAIL_PUBLIC_IP",
            "copy_value": AUREMAIL_PUBLIC_IP or "",
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
        {
            "key": "mx",
            "label": "Entrada de e-mail",
            "description": "Registro MX do domínio principal",
            "type": "MX",
            "host": "@",
            "fqdn": domain_name,
            "value": f"10 {mail_host}",
            "display_value": f"10 {mail_host}",
            "copy_value": f"10 {mail_host}",
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
        {
            "key": "spf",
            "label": "SPF",
            "description": "Autoriza o host de e-mail a enviar pelo domínio",
            "type": "TXT",
            "host": "@",
            "fqdn": domain_name,
            "value": build_spf_value(domain_name),
            "display_value": build_spf_value(domain_name),
            "copy_value": build_spf_value(domain_name),
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
            "description": "Chave pública do servidor de e-mail",
            "type": "TXT",
            "host": f"{AUREMAIL_DKIM_SELECTOR}._domainkey",
            "fqdn": dkim_host,
            "value": AUREMAIL_DKIM_PUBLIC_KEY,
            "display_value": AUREMAIL_DKIM_PUBLIC_KEY or "GERAR CHAVE DKIM NO SERVIDOR E PREENCHER AUREMAIL_DKIM_PUBLIC_KEY",
            "copy_value": AUREMAIL_DKIM_PUBLIC_KEY or "",
            "ttl": AUREMAIL_DNS_TTL,
            "required": True,
        },
    ]

    return records


def build_dns_setup_payload(domain: Dominio) -> dict:
    domain_name = domain.name
    app_host = build_app_host(domain_name)
    mail_host = build_mail_host(domain_name)

    warnings: list[str] = []

    if not AUREMAIL_PUBLIC_IP:
        warnings.append(
            "A variável AUREMAIL_PUBLIC_IP ainda não está configurada no backend. "
            "Sem ela, os registros A ficam incompletos."
        )

    if not AUREMAIL_DKIM_PUBLIC_KEY:
        warnings.append(
            "A variável AUREMAIL_DKIM_PUBLIC_KEY ainda está vazia. "
            "Você vai preencher isso depois de gerar a chave pública DKIM no servidor de e-mail."
        )

    return {
        "success": True,
        "domain": serialize_domain(domain),
        "generated": {
            "public_ip": AUREMAIL_PUBLIC_IP or None,
            "app_subdomain": AUREMAIL_APP_SUBDOMAIN or "@",
            "mail_subdomain": AUREMAIL_MAIL_SUBDOMAIN or "@",
            "app_host": app_host,
            "mail_host": mail_host,
            "dkim_selector": AUREMAIL_DKIM_SELECTOR,
            "dmarc_report_email": build_dmarc_email(domain_name),
        },
        "records": build_dns_records(domain_name),
        "warnings": warnings,
        "steps": [
            "No provedor DNS do domínio, crie exatamente os registros mostrados na tabela.",
            "Se o domínio estiver no Registro.br, use a área de Zona DNS ou de endereçamento do domínio.",
            "O registro PTR do IP da VPS não fica na zona DNS do domínio. Ele é configurado no painel da VPS.",
            "Depois de salvar os registros, aguarde a propagação DNS e clique em Verificar DNS.",
            "Quando os registros obrigatórios estiverem corretos, siga para a criação das caixas de e-mail.",
        ],
    }


def verify_single_record(record: dict) -> dict:
    expected_value = record.get("value") or ""
    record_type = (record.get("type") or "").upper()
    fqdn = record.get("fqdn") or ""
    key = record.get("key") or ""

    if not expected_value:
        return {
            "key": key,
            "status": "pending_config",
            "found_values": [],
            "message": "Valor ainda não configurado no backend.",
        }

    if record_type == "A":
        found_values = doh_lookup(fqdn, "A")
        expected_normalized = normalize_host_value(expected_value)
        found_normalized = [normalize_host_value(item) for item in found_values]
        matched = expected_normalized in found_normalized
    elif record_type == "MX":
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
        db.commit()
        db.refresh(domain)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Esse domínio já está cadastrado.")

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
        fallback = get_fallback_domain(
            db,
            current_user.empresa_id,
            except_id=domain.id,
        )

        if fallback:
            domain.is_primary = False
            fallback.is_primary = True
        else:
            domain.is_primary = True

    try:
        db.commit()
        db.refresh(domain)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Esse domínio já está cadastrado.")

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

    db.delete(domain)
    db.flush()

    if was_primary:
        fallback = get_fallback_domain(db, current_user.empresa_id)
        if fallback:
            fallback.is_primary = True

    db.commit()

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

    return {
        "success": True,
        "domain": serialize_domain(domain),
        "records": verification_results,
        "all_required_ok": required_ok,
    }