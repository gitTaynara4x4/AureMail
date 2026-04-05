from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.parse
import urllib.request
from typing import Any


class StalwartProvisioningError(RuntimeError):
    """Erro amigável para provisionamento no servidor de e-mail."""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class StalwartClient:
    """
    Cliente mínimo para a Management API do Stalwart.

    Observações:
    - aceita token Bearer OU usuário/senha Basic
    - usa apenas urllib da stdlib
    - trabalha em modo idempotente sempre que possível
    """

    def __init__(self) -> None:
        self.base_url = (os.getenv("AUREMAIL_MAIL_SERVER_API_URL", "") or "").strip().rstrip("/")
        self.api_token = (os.getenv("AUREMAIL_MAIL_SERVER_API_TOKEN", "") or "").strip()
        self.api_user = (os.getenv("AUREMAIL_MAIL_SERVER_API_USER", "") or "").strip()
        self.api_password = (os.getenv("AUREMAIL_MAIL_SERVER_API_PASSWORD", "") or "").strip()
        self.timeout = int((os.getenv("AUREMAIL_MAIL_SERVER_TIMEOUT", "15") or "15").strip())
        self.verify_ssl = _env_bool("AUREMAIL_MAIL_SERVER_VERIFY_SSL", True)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def ensure_enabled(self) -> None:
        if not self.enabled:
            raise StalwartProvisioningError(
                "A integração com o servidor de e-mail não está ativa. "
                "Configure AUREMAIL_MAIL_SERVER_API_URL no .env."
            )

    def _build_url(self, path: str) -> str:
        self.ensure_enabled()
        clean_path = "/" + str(path or "").lstrip("/")
        if self.base_url.endswith("/api"):
            return f"{self.base_url}{clean_path}"
        return f"{self.base_url}/api{clean_path}"

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        elif self.api_user and self.api_password:
            raw = f"{self.api_user}:{self.api_password}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("utf-8")

        return headers

    def _ssl_context(self):
        if self.verify_ssl:
            return None
        return ssl._create_unverified_context()  # noqa: SLF001

    def _request(self, method: str, path: str, payload: Any | None = None) -> Any:
        url = self._build_url(path)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url=url,
            data=data,
            headers=self._build_headers(),
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_context()) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            detail = ""
            try:
                raw = exc.read().decode("utf-8")
                parsed = json.loads(raw)
                detail = parsed.get("detail") or parsed.get("message") or raw
            except Exception:
                detail = str(exc)
            raise StalwartProvisioningError(
                f"Falha ao falar com o servidor de e-mail ({exc.code}): {detail}"
            ) from exc
        except Exception as exc:
            raise StalwartProvisioningError(
                f"Não consegui conectar ao servidor de e-mail: {exc}"
            ) from exc

        if not raw:
            return None

        try:
            parsed = json.loads(raw)
        except Exception:
            return raw

        return parsed.get("data", parsed)

    def list_principals(self, principal_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 0

        while True:
            query = {
                "page": page,
                "limit": limit,
            }
            if principal_type:
                query["types"] = principal_type

            path = "/principal?" + urllib.parse.urlencode(query)
            payload = self._request("GET", path) or {}
            batch = list(payload.get("items") or [])
            items.extend(batch)

            total = int(payload.get("total") or len(items))
            if len(items) >= total or not batch:
                break

            page += 1

        return items

    @staticmethod
    def _emails_from_principal(item: dict[str, Any]) -> list[str]:
        emails = item.get("emails") or []
        if isinstance(emails, str):
            return [emails.strip().lower()] if emails.strip() else []
        if isinstance(emails, list):
            return [str(email).strip().lower() for email in emails if str(email).strip()]
        return []

    def find_principal_by_name(self, name: str, principal_type: str | None = None) -> dict[str, Any] | None:
        wanted = str(name or "").strip().lower()
        if not wanted:
            return None

        for item in self.list_principals(principal_type=principal_type):
            candidate = str(item.get("name") or "").strip().lower()
            if candidate == wanted:
                return item
        return None

    def find_principal_by_email(self, email: str) -> dict[str, Any] | None:
        wanted = str(email or "").strip().lower()
        if not wanted:
            return None

        for item in self.list_principals(principal_type="individual"):
            if wanted in self._emails_from_principal(item):
                return item
        return None

    def create_domain(self, domain_name: str, description: str | None = None) -> int:
        domain_name = str(domain_name or "").strip().lower()
        existing = self.find_principal_by_name(domain_name, principal_type="domain")
        if existing:
            return int(existing["id"])

        payload = {
            "type": "domain",
            "quota": 0,
            "name": domain_name,
            "description": description or domain_name,
            "secrets": [],
            "emails": [],
            "urls": [],
            "memberOf": [],
            "roles": [],
            "lists": [],
            "members": [],
            "enabledPermissions": [],
            "disabledPermissions": [],
            "externalMembers": [],
        }
        created_id = self._request("POST", "/principal", payload)
        return int(created_id)

    def delete_domain(self, domain_name: str) -> None:
        existing = self.find_principal_by_name(domain_name, principal_type="domain")
        if not existing:
            return
        self._request("DELETE", f"/principal/{existing['id']}")

    def create_mailbox(
        self,
        *,
        login_name: str,
        email: str,
        password: str,
        display_name: str | None = None,
        quota_bytes: int = 0,
    ) -> int:
        login_name = str(login_name or "").strip().lower()
        email = str(email or "").strip().lower()

        existing = self.find_principal_by_email(email)
        if existing:
            raise StalwartProvisioningError(
                f"A caixa {email} já existe no servidor de e-mail."
            )

        payload = {
            "type": "individual",
            "quota": int(quota_bytes or 0),
            "name": login_name,
            "description": display_name or email,
            "secrets": [password],
            "emails": [email],
            "urls": [],
            "memberOf": [],
            "roles": [],
            "lists": [],
            "members": [],
            "enabledPermissions": [],
            "disabledPermissions": [],
            "externalMembers": [],
        }
        created_id = self._request("POST", "/principal", payload)
        return int(created_id)

    def update_mailbox(
        self,
        principal_id: int,
        *,
        display_name: str | None = None,
        quota_bytes: int | None = None,
        password: str | None = None,
        is_active: bool | None = None,
    ) -> None:
        operations: list[dict[str, Any]] = []

        if display_name is not None:
            operations.append({"action": "set", "field": "description", "value": display_name})

        if quota_bytes is not None:
            operations.append({"action": "set", "field": "quota", "value": int(quota_bytes)})

        if password is not None:
            operations.append({"action": "set", "field": "secrets", "value": [password]})

        if is_active is not None:
            operations.append({"action": "set", "field": "isEnabled", "value": bool(is_active)})

        if not operations:
            return

        self._request("PATCH", f"/principal/{principal_id}", operations)

    def delete_mailbox_by_email(self, email: str) -> None:
        existing = self.find_principal_by_email(email)
        if not existing:
            return
        self._request("DELETE", f"/principal/{existing['id']}")

    def create_dkim_signature(self, domain_name: str, selector: str | None = None, algorithm: str = "Ed25519"):
        payload = {
            "id": None,
            "algorithm": algorithm,
            "domain": str(domain_name or "").strip().lower(),
            "selector": selector,
        }
        return self._request("POST", "/dkim", payload)


_client_singleton: StalwartClient | None = None


def get_stalwart_client() -> StalwartClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = StalwartClient()
    return _client_singleton