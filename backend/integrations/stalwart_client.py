from __future__ import annotations

import base64
import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


logger = logging.getLogger("auremail.stalwart")


class StalwartProvisioningError(RuntimeError):
    """Erro amigável para provisionamento no servidor de e-mail."""


class StalwartClient:
    """Cliente simples para a Management API do Stalwart.

    Suporta autenticação por Bearer token ou Basic Auth.
    """

    def __init__(self) -> None:
        self.base_url = (os.getenv("AUREMAIL_MAIL_SERVER_API_URL", "") or "").strip().rstrip("/")
        self.api_token = (os.getenv("AUREMAIL_MAIL_SERVER_API_TOKEN", "") or "").strip()
        self.api_user = (os.getenv("AUREMAIL_MAIL_SERVER_API_USER", "") or "").strip()
        self.api_password = (os.getenv("AUREMAIL_MAIL_SERVER_API_PASSWORD", "") or "").strip()
        self.timeout = int((os.getenv("AUREMAIL_MAIL_SERVER_TIMEOUT", "15") or "15").strip())
        self.verify_ssl = (
            (os.getenv("AUREMAIL_MAIL_SERVER_VERIFY_SSL", "false") or "false").strip().lower() == "true"
        )
        self.default_role = (os.getenv("AUREMAIL_STALWART_DEFAULT_ROLE", "user") or "user").strip()

        logger.warning(
            "StalwartClient inicializado | enabled=%s | base_url=%s | verify_ssl=%s | timeout=%s | auth_mode=%s | default_role=%s",
            self.enabled,
            self.base_url or None,
            self.verify_ssl,
            self.timeout,
            self.auth_mode,
            self.default_role,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    @property
    def auth_mode(self) -> str:
        if self.api_token:
            return "bearer"
        if self.api_user and self.api_password:
            return "basic"
        return "none"

    def ensure_enabled(self) -> None:
        if not self.enabled:
            logger.error(
                "StalwartClient desativado | base_url=%s | auth_mode=%s",
                self.base_url or None,
                self.auth_mode,
            )
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
        return ssl._create_unverified_context()  # noqa: S323

    @staticmethod
    def _normalize_email(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _safe_preview(value: Any, limit: int = 400) -> str:
        text = str(value)
        if len(text) > limit:
            return text[:limit] + "...[truncado]"
        return text

    @staticmethod
    def _payload_summary(payload: Any | None) -> Any:
        if payload is None:
            return None

        if isinstance(payload, dict):
            summary: dict[str, Any] = {}
            for key, value in payload.items():
                if key in {"secrets", "password", "api_password", "token", "Authorization"}:
                    if isinstance(value, list):
                        summary[key] = [f"<oculto:{len(str(item))} chars>" for item in value]
                    else:
                        summary[key] = "<oculto>"
                elif isinstance(value, (str, int, float, bool)) or value is None:
                    summary[key] = value
                elif isinstance(value, list):
                    summary[key] = f"<list:{len(value)}>"
                elif isinstance(value, dict):
                    summary[key] = f"<dict:{len(value)} keys>"
                else:
                    summary[key] = f"<{type(value).__name__}>"
            return summary

        if isinstance(payload, list):
            return f"<list:{len(payload)}>"

        return f"<{type(payload).__name__}>"

    @staticmethod
    def _principal_summary(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None

        emails = item.get("emails") or []
        if isinstance(emails, str):
            emails = [emails]
        elif not isinstance(emails, list):
            emails = []

        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "type": item.get("type"),
            "quota": item.get("quota"),
            "emails": emails,
            "description": item.get("description"),
            "roles": item.get("roles") or [],
        }

    @staticmethod
    def _extract_error_detail(parsed: dict[str, Any]) -> str:
        detail = (
            parsed.get("details")
            or parsed.get("detail")
            or parsed.get("message")
            or parsed.get("error")
            or "Erro desconhecido"
        )
        item = parsed.get("item")
        if item is not None:
            detail = f"{detail} | item={item}"
        return str(detail)

    def _request(self, method: str, path: str, payload: Any | None = None) -> Any:
        method = method.upper()
        url = self._build_url(path)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        payload_summary = self._payload_summary(payload)

        logger.warning(
            "Stalwart request -> %s | url=%s | enabled=%s | verify_ssl=%s | timeout=%s | auth_mode=%s | payload=%s",
            method,
            url,
            self.enabled,
            self.verify_ssl,
            self.timeout,
            self.auth_mode,
            payload_summary,
        )

        req = urllib.request.Request(
            url=url,
            data=data,
            headers=self._build_headers(),
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_context()) as response:
                raw_bytes = response.read()
                raw = raw_bytes.decode("utf-8")
                logger.warning(
                    "Stalwart response <- %s | url=%s | status=%s | body=%s",
                    method,
                    url,
                    getattr(response, "status", None),
                    self._safe_preview(raw),
                )
        except urllib.error.HTTPError as exc:
            detail = ""
            raw_body = ""
            try:
                raw_body = exc.read().decode("utf-8")
                parsed = json.loads(raw_body) if raw_body else {}
                if isinstance(parsed, dict):
                    detail = self._extract_error_detail(parsed)
                else:
                    detail = raw_body
            except Exception:
                detail = str(exc)

            logger.error(
                "Stalwart HTTPError | method=%s | url=%s | code=%s | detail=%s | raw_body=%s",
                method,
                url,
                exc.code,
                detail,
                self._safe_preview(raw_body or detail),
            )

            raise StalwartProvisioningError(
                f"Falha ao falar com o servidor de e-mail ({exc.code}): {detail}"
            ) from exc
        except Exception as exc:
            logger.exception(
                "Stalwart exception | method=%s | url=%s | error=%s",
                method,
                url,
                exc,
            )
            raise StalwartProvisioningError(
                f"Não consegui conectar ao servidor de e-mail: {exc}"
            ) from exc

        if not raw:
            logger.warning(
                "Stalwart response vazia | method=%s | url=%s",
                method,
                url,
            )
            return None

        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning(
                "Stalwart response não-JSON | method=%s | url=%s | body=%s",
                method,
                url,
                self._safe_preview(raw),
            )
            return raw

        if isinstance(parsed, dict) and parsed.get("error"):
            detail = self._extract_error_detail(parsed)
            logger.error(
                "Stalwart respondeu JSON de erro | method=%s | url=%s | detail=%s | parsed=%s",
                method,
                url,
                detail,
                self._safe_preview(parsed),
            )
            raise StalwartProvisioningError(
                f"Falha ao falar com o servidor de e-mail: {detail}"
            )

        parsed_data = parsed.get("data", parsed)

        logger.warning(
            "Stalwart parsed response | method=%s | url=%s | parsed=%s",
            method,
            url,
            self._safe_preview(parsed_data),
        )

        return parsed_data

    def _extract_created_id(self, value: Any) -> int:
        logger.warning("Extraindo ID do principal criado | raw=%s", self._safe_preview(value))

        if value is None:
            raise StalwartProvisioningError(
                "O servidor de e-mail não retornou ID ao criar o principal."
            )

        if isinstance(value, dict):
            direct_id = value.get("id")
            if direct_id is not None:
                logger.warning("ID extraído diretamente | id=%s", direct_id)
                return int(direct_id)

            nested = value.get("data")
            if isinstance(nested, dict):
                nested_id = nested.get("id")
                if nested_id is not None:
                    logger.warning("ID extraído de value['data'] | id=%s", nested_id)
                    return int(nested_id)

            items = value.get("items")
            if isinstance(items, list) and items:
                first = items[0]
                if isinstance(first, dict) and first.get("id") is not None:
                    logger.warning("ID extraído de value['items'][0] | id=%s", first["id"])
                    return int(first["id"])

            raise StalwartProvisioningError(
                f"Resposta inesperada do servidor ao criar principal: {value}"
            )

        logger.warning("ID extraído por cast simples | value=%s", value)
        return int(value)

    def list_principals(self, principal_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logger.warning(
            "Listando principals | principal_type=%s | limit=%s",
            principal_type,
            limit,
        )

        items: list[dict[str, Any]] = []
        page = 0

        while True:
            query: dict[str, Any] = {"page": page, "limit": limit}
            if principal_type:
                query["types"] = principal_type

            path = "/principal?" + urllib.parse.urlencode(query)
            logger.warning("Buscando página de principals | page=%s | path=%s", page, path)

            payload = self._request("GET", path) or {}

            if isinstance(payload, list):
                batch = [item for item in payload if isinstance(item, dict)]
                items.extend(batch)
                logger.warning(
                    "Página retornou lista direta | page=%s | batch=%s | total_acumulado=%s",
                    page,
                    len(batch),
                    len(items),
                )
                break

            batch = list(payload.get("items") or [])
            items.extend(batch)

            total = int(payload.get("total") or len(items))
            logger.warning(
                "Página retornou dict | page=%s | batch=%s | total_reportado=%s | total_acumulado=%s",
                page,
                len(batch),
                total,
                len(items),
            )

            if len(items) >= total or not batch:
                break

            page += 1

        logger.warning(
            "Listagem de principals concluída | principal_type=%s | total=%s",
            principal_type,
            len(items),
        )
        return items

    @staticmethod
    def _emails_from_principal(item: dict[str, Any]) -> list[str]:
        emails = item.get("emails") or []

        if isinstance(emails, str):
            email = StalwartClient._normalize_email(emails)
            return [email] if email else []

        if isinstance(emails, list):
            return [
                StalwartClient._normalize_email(email)
                for email in emails
                if str(email).strip()
            ]

        return []

    def _merge_default_role(self, roles: list[str] | None = None) -> list[str]:
        merged = [str(role).strip() for role in (roles or []) if str(role).strip()]
        if self.default_role and self.default_role not in merged:
            merged.append(self.default_role)

        logger.warning(
            "Mesclando roles | input=%s | output=%s",
            roles or [],
            merged,
        )
        return merged

    def find_principal_by_name(self, name: str, principal_type: str | None = None) -> dict[str, Any] | None:
        wanted = str(name or "").strip().lower()
        logger.warning(
            "Procurando principal por nome | wanted=%s | principal_type=%s",
            wanted or None,
            principal_type,
        )

        if not wanted:
            logger.warning("Nome vazio ao procurar principal por nome")
            return None

        for item in self.list_principals(principal_type=principal_type):
            current_name = str(item.get("name") or "").strip().lower()
            if current_name == wanted:
                logger.warning(
                    "Principal encontrado por nome | wanted=%s | principal=%s",
                    wanted,
                    self._principal_summary(item),
                )
                return item

        logger.warning(
            "Principal NÃO encontrado por nome | wanted=%s | principal_type=%s",
            wanted,
            principal_type,
        )
        return None

    def find_principal_by_email(self, email: str) -> dict[str, Any] | None:
        wanted = self._normalize_email(email)
        logger.warning("Procurando principal por e-mail | wanted=%s", wanted or None)

        if not wanted:
            logger.warning("E-mail vazio ao procurar principal por e-mail")
            return None

        for item in self.list_principals(principal_type="individual"):
            emails = self._emails_from_principal(item)
            if wanted in emails:
                logger.warning(
                    "Principal encontrado por e-mail | wanted=%s | principal=%s",
                    wanted,
                    self._principal_summary(item),
                )
                return item

        logger.warning("Principal NÃO encontrado por e-mail | wanted=%s", wanted)
        return None

    def _mailbox_identity_candidates(self, email: str) -> list[str]:
        normalized = self._normalize_email(email)
        if not normalized:
            logger.warning("Sem candidatos de identidade | email vazio")
            return []

        candidates: list[str] = [normalized]

        if "@" in normalized:
            local_part = normalized.split("@", 1)[0].strip()
            if local_part and local_part not in candidates:
                candidates.append(local_part)

        logger.warning(
            "Candidatos de identidade para mailbox | email=%s | candidates=%s",
            normalized,
            candidates,
        )
        return candidates

    def find_mailbox_principal(self, email: str) -> dict[str, Any] | None:
        normalized = self._normalize_email(email)
        candidates = self._mailbox_identity_candidates(normalized)

        logger.warning(
            "Iniciando lookup de mailbox | email=%s | candidates=%s",
            normalized,
            candidates,
        )

        for candidate in candidates:
            logger.warning(
                "Tentando lookup por e-mail | original=%s | candidate=%s",
                normalized,
                candidate,
            )
            found = self.find_principal_by_email(candidate)
            if found:
                logger.warning(
                    "Mailbox encontrado por e-mail | original=%s | candidate=%s | principal=%s",
                    normalized,
                    candidate,
                    self._principal_summary(found),
                )
                return found

        for candidate in candidates:
            logger.warning(
                "Tentando lookup por nome | original=%s | candidate=%s",
                normalized,
                candidate,
            )
            found = self.find_principal_by_name(candidate, principal_type="individual")
            if found:
                logger.warning(
                    "Mailbox encontrado por nome | original=%s | candidate=%s | principal=%s",
                    normalized,
                    candidate,
                    self._principal_summary(found),
                )
                return found

        logger.warning(
            "Mailbox NÃO encontrado no Stalwart | email=%s | candidates=%s",
            normalized,
            candidates,
        )
        return None

    def create_domain(self, domain_name: str, description: str | None = None) -> int:
        domain_name = str(domain_name or "").strip().lower()
        logger.warning(
            "Criando domínio no Stalwart | domain=%s | description=%s",
            domain_name,
            description,
        )

        existing = self.find_principal_by_name(domain_name, principal_type="domain")
        if existing:
            logger.warning(
                "Domínio já existe no Stalwart | domain=%s | principal=%s",
                domain_name,
                self._principal_summary(existing),
            )
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

        created = self._request("POST", "/principal", payload)
        created_id = self._extract_created_id(created)

        logger.warning(
            "Domínio criado no Stalwart | domain=%s | principal_id=%s",
            domain_name,
            created_id,
        )
        return created_id

    def rename_domain(self, old_domain_name: str, new_domain_name: str) -> None:
        old_domain_name = str(old_domain_name or "").strip().lower()
        new_domain_name = str(new_domain_name or "").strip().lower()

        logger.warning(
            "Renomeando domínio no Stalwart | old=%s | new=%s",
            old_domain_name,
            new_domain_name,
        )

        if old_domain_name == new_domain_name:
            logger.warning("Rename de domínio ignorado | nomes idênticos")
            return

        existing = self.find_principal_by_name(old_domain_name, principal_type="domain")
        if not existing:
            logger.warning(
                "Domínio antigo não encontrado; criando novo | old=%s | new=%s",
                old_domain_name,
                new_domain_name,
            )
            self.create_domain(new_domain_name)
            return

        operations = [
            {"action": "set", "field": "name", "value": new_domain_name},
            {"action": "set", "field": "description", "value": new_domain_name},
        ]
        self._request("PATCH", f"/principal/{existing['id']}", operations)

        logger.warning(
            "Domínio renomeado no Stalwart | old=%s | new=%s | principal_id=%s",
            old_domain_name,
            new_domain_name,
            existing.get("id"),
        )

    def delete_domain(self, domain_name: str) -> None:
        domain_name = str(domain_name or "").strip().lower()
        logger.warning("Removendo domínio do Stalwart | domain=%s", domain_name)

        existing = self.find_principal_by_name(domain_name, principal_type="domain")
        if not existing:
            logger.warning("Domínio não existe no Stalwart; nada a remover | domain=%s", domain_name)
            return

        self._request("DELETE", f"/principal/{existing['id']}")

        logger.warning(
            "Domínio removido do Stalwart | domain=%s | principal_id=%s",
            domain_name,
            existing.get("id"),
        )

    def create_mailbox(
        self,
        *,
        login_name: str,
        email: str,
        password: str,
        display_name: str | None = None,
        quota_bytes: int = 0,
        is_enabled: bool = True,
    ) -> int:
        email = self._normalize_email(email)
        login_name = email

        logger.warning(
            "Criando mailbox no Stalwart | email=%s | login_name=%s | display_name=%s | quota_bytes=%s | is_enabled=%s",
            email,
            login_name,
            display_name,
            quota_bytes,
            is_enabled,
        )

        existing = self.find_mailbox_principal(email)
        if existing:
            logger.error(
                "Mailbox já existe no Stalwart | email=%s | principal=%s",
                email,
                self._principal_summary(existing),
            )
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
            "roles": self._merge_default_role([]),
            "lists": [],
            "members": [],
            "enabledPermissions": [],
            "disabledPermissions": [],
            "externalMembers": [],
        }

        created = self._request("POST", "/principal", payload)
        created_id = self._extract_created_id(created)

        logger.warning(
            "Mailbox criada no Stalwart | email=%s | principal_id=%s",
            email,
            created_id,
        )

        if not is_enabled:
            logger.warning("Mailbox criada desativada; aplicando update is_active=False | email=%s", email)
            self.update_mailbox_by_email(
                email,
                new_login_name=email,
                is_active=False,
            )

        return created_id

    def update_mailbox_by_email(
        self,
        current_email: str,
        *,
        new_login_name: str | None = None,
        new_email: str | None = None,
        display_name: str | None = None,
        quota_bytes: int | None = None,
        password: str | None = None,
        is_active: bool | None = None,
    ) -> None:
        current_email = self._normalize_email(current_email)

        logger.warning(
            "Atualizando mailbox no Stalwart | current_email=%s | new_login_name=%s | new_email=%s | display_name=%s | quota_bytes=%s | is_active=%s | password_sent=%s",
            current_email,
            new_login_name,
            new_email,
            display_name,
            quota_bytes,
            is_active,
            password is not None,
        )

        existing = self.find_mailbox_principal(current_email)
        if not existing:
            logger.error("Mailbox não existe no Stalwart para update | current_email=%s", current_email)
            raise StalwartProvisioningError(
                f"A caixa {current_email} não existe no servidor de e-mail."
            )

        operations: list[dict[str, Any]] = []

        if new_email is not None:
            new_email = self._normalize_email(new_email)

        if new_login_name is not None:
            operations.append({
                "action": "set",
                "field": "name",
                "value": str(new_login_name).strip().lower(),
            })

        if new_email is not None:
            operations.append({
                "action": "set",
                "field": "emails",
                "value": [new_email],
            })

        if display_name is not None:
            operations.append({
                "action": "set",
                "field": "description",
                "value": display_name,
            })

        if quota_bytes is not None:
            operations.append({
                "action": "set",
                "field": "quota",
                "value": int(quota_bytes),
            })

        if password is not None:
            operations.append({
                "action": "set",
                "field": "secrets",
                "value": [password],
            })

        if is_active is not None:
            operations.append({
                "action": "set",
                "field": "isEnabled",
                "value": bool(is_active),
            })

        merged_roles = self._merge_default_role(existing.get("roles") or [])
        if merged_roles != list(existing.get("roles") or []):
            operations.append({
                "action": "set",
                "field": "roles",
                "value": merged_roles,
            })

        logger.warning(
            "Operações de update prontas | current_email=%s | principal=%s | operations=%s",
            current_email,
            self._principal_summary(existing),
            self._payload_summary(operations),
        )

        if operations:
            self._request("PATCH", f"/principal/{existing['id']}", operations)
            logger.warning(
                "Mailbox atualizada no Stalwart | current_email=%s | principal_id=%s",
                current_email,
                existing.get("id"),
            )
        else:
            logger.warning("Nenhuma operação de update para mailbox | current_email=%s", current_email)

    def delete_mailbox_by_email(self, email: str) -> None:
        normalized_email = self._normalize_email(email)

        logger.warning(
            "Iniciando delete de mailbox no Stalwart | email=%s | base_url=%s | enabled=%s",
            normalized_email,
            self.base_url or None,
            self.enabled,
        )

        existing = self.find_mailbox_principal(normalized_email)

        logger.warning(
            "Resultado do lookup antes do delete | email=%s | principal=%s",
            normalized_email,
            self._principal_summary(existing),
        )

        if not existing:
            logger.error(
                "Mailbox não encontrada no Stalwart para delete | email=%s",
                normalized_email,
            )
            raise StalwartProvisioningError(
                f"A caixa {normalized_email} não foi encontrada no servidor de e-mail."
            )

        principal_id = existing.get("id")
        principal_name = str(existing.get("name") or "").strip()

        logger.warning(
            "Dados do principal para delete | email=%s | principal_id=%s | principal_name=%s",
            normalized_email,
            principal_id,
            principal_name or None,
        )

        if principal_id is None and not principal_name:
            logger.error(
                "Principal sem id e sem name para delete | email=%s | principal=%s",
                normalized_email,
                self._principal_summary(existing),
            )
            raise StalwartProvisioningError(
                f"Não foi possível identificar o principal da caixa {normalized_email} no servidor de e-mail."
            )

        first_error: Exception | None = None

        if principal_id is not None:
            try:
                logger.warning(
                    "Tentando delete por principal_id | email=%s | principal_id=%s",
                    normalized_email,
                    principal_id,
                )
                self._request("DELETE", f"/principal/{principal_id}")
                logger.warning(
                    "Delete por principal_id concluído | email=%s | principal_id=%s",
                    normalized_email,
                    principal_id,
                )
                return
            except StalwartProvisioningError as exc:
                logger.error(
                    "Falha no delete por principal_id | email=%s | principal_id=%s | error=%s",
                    normalized_email,
                    principal_id,
                    exc,
                )
                first_error = exc

        if principal_name:
            try:
                logger.warning(
                    "Tentando delete por principal_name | email=%s | principal_name=%s",
                    normalized_email,
                    principal_name,
                )
                self._request("DELETE", f"/principal/{urllib.parse.quote(principal_name, safe='')}")
                logger.warning(
                    "Delete por principal_name concluído | email=%s | principal_name=%s",
                    normalized_email,
                    principal_name,
                )
                return
            except StalwartProvisioningError as exc:
                logger.error(
                    "Falha no delete por principal_name | email=%s | principal_name=%s | error=%s",
                    normalized_email,
                    principal_name,
                    exc,
                )
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            logger.error(
                "Delete de mailbox falhou após tentativas | email=%s | error=%s",
                normalized_email,
                first_error,
            )
            raise first_error

        logger.error(
            "Delete de mailbox terminou sem sucesso e sem erro capturado | email=%s",
            normalized_email,
        )
        raise StalwartProvisioningError(
            f"Não foi possível remover a caixa {normalized_email} no servidor de e-mail."
        )

    def create_dkim_signature(
        self,
        domain_name: str,
        selector: str | None = None,
        algorithm: str = "Ed25519",
    ):
        logger.warning(
            "Criando assinatura DKIM | domain=%s | selector=%s | algorithm=%s",
            domain_name,
            selector,
            algorithm,
        )

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
        logger.warning("Criando singleton do StalwartClient")
        _client_singleton = StalwartClient()
    else:
        logger.warning(
            "Reutilizando singleton do StalwartClient | enabled=%s | base_url=%s",
            _client_singleton.enabled,
            _client_singleton.base_url or None,
        )
    return _client_singleton