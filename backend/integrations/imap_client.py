from __future__ import annotations

import imaplib
import logging
import os
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html import unescape
from typing import Any


logger = logging.getLogger("auremail.imap")


class ImapSyncError(RuntimeError):
    """Erro amigável de sincronização IMAP."""


@dataclass
class RemoteMessage:
    uid: str
    message_id_header: str
    from_name: str | None
    from_email: str
    to_email: str
    cc_email: str | None
    subject: str | None
    preview: str | None
    body_text: str | None
    body_html: str | None
    raw_source: str | None
    sent_at: datetime | None
    is_read: bool


def _env_str(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name, "true" if default else "false").lower()
    return raw == "true"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = _env_str(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _env_csv(name: str, default: str) -> list[str]:
    raw = _env_str(name, default)
    parts = [part.strip() for part in raw.split(",")]
    unique: list[str] = []
    for part in parts:
        if part and part not in unique:
            unique.append(part)
    return unique


def _decode_header_value(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(make_header(decode_header(value))).strip() or None
    except Exception:
        return str(value).strip() or None


def _normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def _extract_email_list(value: str | None) -> list[tuple[str | None, str]]:
    pairs: list[tuple[str | None, str]] = []
    for name, email in getaddresses([value or ""]):
        email_norm = _normalize_email(email)
        if email_norm:
            pairs.append((_decode_header_value(name), email_norm))
    return pairs


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None

    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n\n", text)
    text = re.sub(r"(?is)</div\s*>", "\n", text)
    text = re.sub(r"(?is)<li\s*>", "• ", text)
    text = re.sub(r"(?is)</li\s*>", "\n", text)
    text = re.sub(r"(?is)<.*?>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


def _extract_text_bodies(message) -> tuple[str | None, str | None]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get_content_disposition() or "").lower()

            if disposition == "attachment":
                continue

            try:
                payload = part.get_content()
            except Exception:
                try:
                    raw = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    payload = raw.decode(charset, errors="replace")
                except Exception:
                    payload = None

            if payload is None:
                continue

            payload_text = str(payload).strip()
            if not payload_text:
                continue

            if content_type == "text/plain":
                plain_parts.append(payload_text)
            elif content_type == "text/html":
                html_parts.append(payload_text)
    else:
        try:
            payload = message.get_content()
        except Exception:
            raw = message.get_payload(decode=True) or b""
            charset = message.get_content_charset() or "utf-8"
            payload = raw.decode(charset, errors="replace")

        payload_text = str(payload or "").strip()
        content_type = message.get_content_type()

        if payload_text:
            if content_type == "text/plain":
                plain_parts.append(payload_text)
            elif content_type == "text/html":
                html_parts.append(payload_text)

    body_text = "\n\n".join(part for part in plain_parts if part) or None
    body_html = "\n".join(part for part in html_parts if part) or None

    if not body_text and body_html:
        body_text = _strip_html(body_html)

    return body_text, body_html


def _preview_from_body(body: str | None, max_len: int = 180) -> str | None:
    if not body:
        return None
    text = " ".join(body.split())
    return text[:max_len] if text else None


def _parse_sent_at(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        dt = parsedate_to_datetime(value)
        if dt is None:
            return None

        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _build_fallback_message_id(uid: str, mailbox_email: str) -> str:
    domain = mailbox_email.split("@", 1)[-1] if "@" in mailbox_email else "local"
    return f"<imap-{uid}@{domain}>"


def _flags_to_is_read(flags_blob: bytes | str | None) -> bool:
    if not flags_blob:
        return False

    text = (
        flags_blob.decode("utf-8", errors="replace")
        if isinstance(flags_blob, bytes)
        else str(flags_blob)
    )
    return "\\Seen" in text


def _extract_fetch_parts(fetch_data) -> tuple[bytes | None, bytes]:
    message_bytes = None
    flags_blob = b""

    for part in fetch_data:
        if not isinstance(part, tuple) or len(part) < 2:
            continue

        meta, payload = part

        if isinstance(meta, bytes):
            flags_blob = meta

        if isinstance(payload, (bytes, bytearray)):
            message_bytes = bytes(payload)

    return message_bytes, flags_blob


def _safe_text(value: Any, max_len: int = 220) -> str:
    text = str(value or "")
    if len(text) > max_len:
        return text[:max_len] + "...[truncado]"
    return text



class AureMailImapClient:
    def __init__(self) -> None:
        self.host = _env_str("AUREMAIL_IMAP_HOST") or _env_str("AUREMAIL_MAIL_SERVER_HOST")
        self.port = _env_int("AUREMAIL_IMAP_PORT", 993, minimum=1)
        self.timeout = _env_int("AUREMAIL_IMAP_TIMEOUT", 20, minimum=1)
        self.inbox_names = _env_csv(
            "AUREMAIL_IMAP_INBOX_NAMES",
            _env_str("AUREMAIL_IMAP_INBOX_NAME", "INBOX") or "INBOX",
        )
        self.junk_names = _env_csv(
            "AUREMAIL_IMAP_JUNK_NAMES",
            "Junk Mail,Junk,SPAM,Spam",
        )
        self.sent_names = _env_csv(
            "AUREMAIL_IMAP_SENT_NAMES",
            "Sent,Sent Messages,Sent Items,Enviados",
        )
        self.draft_names = _env_csv(
            "AUREMAIL_IMAP_DRAFT_NAMES",
            "Drafts,Rascunhos",
        )
        self.trash_names = _env_csv(
            "AUREMAIL_IMAP_TRASH_NAMES",
            "Trash,Lixeira,Deleted Messages,Deleted Items,Bin",
        )
        self.sync_limit = _env_int("AUREMAIL_IMAP_SYNC_LIMIT", 30, minimum=1)
        self.use_ssl = _env_bool("AUREMAIL_IMAP_SSL", True)
        self.use_starttls = _env_bool("AUREMAIL_IMAP_STARTTLS", True)
        self.verify_ssl = _env_bool("AUREMAIL_IMAP_VERIFY_SSL", True)

        logger.warning(
            "IMAP client inicializado | host=%s | port=%s | timeout=%s | inbox_names=%s | junk_names=%s | sent_names=%s | draft_names=%s | trash_names=%s | sync_limit=%s | use_ssl=%s | use_starttls=%s | verify_ssl=%s",
            self.host or None,
            self.port,
            self.timeout,
            self.inbox_names,
            self.junk_names,
            self.sent_names,
            self.draft_names,
            self.trash_names,
            self.sync_limit,
            self.use_ssl,
            self.use_starttls,
            self.verify_ssl,
        )

    def ensure_enabled(self) -> None:
        if not self.host:
            logger.error("IMAP desativado | AUREMAIL_IMAP_HOST/AUREMAIL_MAIL_SERVER_HOST vazio")
            raise ImapSyncError("AUREMAIL_IMAP_HOST não configurado no .env.")

    def _ssl_context(self):
        if self.verify_ssl:
            return ssl.create_default_context()
        return ssl._create_unverified_context()  # noqa: S323

    def _connect(self):
        self.ensure_enabled()
        imaplib._MAXLINE = max(imaplib._MAXLINE, 10_000_000)

        logger.warning(
            "Abrindo conexão IMAP | host=%s | port=%s | timeout=%s | use_ssl=%s | use_starttls=%s | verify_ssl=%s",
            self.host,
            self.port,
            self.timeout,
            self.use_ssl,
            self.use_starttls,
            self.verify_ssl,
        )

        try:
            if self.use_ssl:
                client = imaplib.IMAP4_SSL(
                    self.host,
                    self.port,
                    timeout=self.timeout,
                    ssl_context=self._ssl_context(),
                )
                logger.warning("Conexão IMAP4_SSL aberta | welcome=%s", _safe_text(getattr(client, "welcome", b"")))
                return client

            client = imaplib.IMAP4(self.host, self.port, timeout=self.timeout)
            logger.warning("Conexão IMAP4 aberta sem SSL | welcome=%s", _safe_text(getattr(client, "welcome", b"")))

            if self.use_starttls:
                try:
                    status, data = client.starttls(ssl_context=self._ssl_context())
                    logger.warning(
                        "Resposta STARTTLS IMAP | status=%s | data=%s",
                        status,
                        _safe_text(data),
                    )
                    if status != "OK":
                        raise ImapSyncError("Falha ao iniciar STARTTLS no IMAP.")
                except Exception as exc:
                    try:
                        client.logout()
                    except Exception:
                        pass
                    logger.exception("Falha no STARTTLS do IMAP")
                    raise ImapSyncError(f"Falha no STARTTLS do IMAP: {exc}") from exc

            return client

        except ImapSyncError:
            raise
        except Exception as exc:
            logger.exception("Falha ao conectar no IMAP")
            raise ImapSyncError(f"Não foi possível conectar ao IMAP: {exc}") from exc

    def _safe_logout(self, client) -> None:
        try:
            logger.warning("Executando logout IMAP")
            client.logout()
        except Exception as exc:
            logger.warning("Falha silenciosa no logout IMAP | error=%s", exc)

    def _login_via_login(self, email_address: str, password: str):
        logger.warning(
            "Tentando auth IMAP via LOGIN | email=%s | password_len=%s",
            email_address,
            len(password or ""),
        )
        client = self._connect()
        try:
            login_status, login_data = client.login(email_address, password)
            logger.warning(
                "Resposta auth LOGIN IMAP | email=%s | status=%s | data=%s",
                email_address,
                login_status,
                _safe_text(login_data),
            )
            if login_status != "OK":
                raise ImapSyncError(f"Falha no login IMAP: {login_data}")
            return client
        except Exception:
            self._safe_logout(client)
            raise

    def _login_via_auth_plain(self, email_address: str, password: str):
        logger.warning(
            "Tentando auth IMAP via AUTH PLAIN | email=%s | password_len=%s",
            email_address,
            len(password or ""),
        )
        client = self._connect()
        try:
            auth_bytes = f"\0{email_address}\0{password}".encode("utf-8")

            def auth_callback(_challenge: bytes | None) -> bytes:
                return auth_bytes

            auth_status, auth_data = client.authenticate("PLAIN", auth_callback)
            logger.warning(
                "Resposta auth AUTH PLAIN IMAP | email=%s | status=%s | data=%s",
                email_address,
                auth_status,
                _safe_text(auth_data),
            )
            if auth_status != "OK":
                raise ImapSyncError(f"Falha no AUTH PLAIN IMAP: {auth_data}")
            return client
        except Exception:
            self._safe_logout(client)
            raise

    def _connect_authenticated(self, email_address: str, password: str):
        login_error: Exception | None = None
        plain_error: Exception | None = None

        try:
            logger.warning("Primeira tentativa de autenticação IMAP | método=LOGIN | email=%s", email_address)
            return self._login_via_login(email_address, password)
        except Exception as exc:
            login_error = exc
            logger.warning("Falha no método LOGIN IMAP | email=%s | error=%s", email_address, exc)

        try:
            logger.warning("Segunda tentativa de autenticação IMAP | método=AUTH PLAIN | email=%s", email_address)
            return self._login_via_auth_plain(email_address, password)
        except Exception as exc:
            plain_error = exc
            logger.warning("Falha no método AUTH PLAIN IMAP | email=%s | error=%s", email_address, exc)

        logger.error(
            "Autenticação IMAP falhou em todos os métodos | email=%s | login_error=%s | plain_error=%s",
            email_address,
            login_error,
            plain_error,
        )
        raise ImapSyncError(
            f"Falha ao autenticar no IMAP. Tentativas: LOGIN: {login_error} | AUTH PLAIN: {plain_error}"
        )

    def _folder_candidates(self, folder_slug: str) -> list[str]:
        slug = (folder_slug or "inbox").strip().lower()
        mapping = {
            "inbox": self.inbox_names,
            "junk": self.junk_names,
            "sent": self.sent_names,
            "drafts": self.draft_names,
            "trash": self.trash_names,
        }
        candidates = mapping.get(slug, self.inbox_names)
        return [item for item in candidates if item]

    def _mailbox_arg(self, mailbox_name: str) -> str:
        text = str(mailbox_name or "").strip()
        if not text:
            return text
        if text.upper() == "INBOX":
            return "INBOX"
        if re.fullmatch(r"[A-Za-z0-9._/\-]+", text):
            return text
        escaped = text.replace("\\", "\\\\").replace('"', r'\"')
        return f'"{escaped}"'

    def _select_mailbox(self, client, *, email_address: str, mailbox_name: str, readonly: bool) -> tuple[str, Any]:
        try:
            status, data = client.select(self._mailbox_arg(mailbox_name), readonly=readonly)
        except Exception as exc:
            logger.warning(
                "Exceção ao selecionar pasta IMAP | email=%s | mailbox_name=%s | readonly=%s | error=%s",
                email_address,
                mailbox_name,
                readonly,
                exc,
            )
            raise
        logger.warning(
            "Resposta select IMAP | email=%s | mailbox_name=%s | readonly=%s | status=%s | data=%s",
            email_address,
            mailbox_name,
            readonly,
            status,
            _safe_text(data),
        )
        return status, data

    def _select_first_available_mailbox(
        self,
        client,
        *,
        email_address: str,
        folder_slug: str,
        readonly: bool = True,
    ) -> str | None:
        candidates = self._folder_candidates(folder_slug)
        logger.warning(
            "Tentando abrir pasta IMAP | email=%s | folder_slug=%s | readonly=%s | candidates=%s",
            email_address,
            folder_slug,
            readonly,
            candidates,
        )

        for mailbox_name in candidates:
            try:
                select_status, _select_data = self._select_mailbox(
                    client,
                    email_address=email_address,
                    mailbox_name=mailbox_name,
                    readonly=readonly,
                )
            except Exception:
                continue

            if select_status == "OK":
                return mailbox_name

        return None

    def _create_mailbox(self, client, *, email_address: str, mailbox_name: str) -> bool:
        try:
            status, data = client.create(self._mailbox_arg(mailbox_name))
        except Exception as exc:
            logger.warning(
                "Exceção ao criar pasta IMAP | email=%s | mailbox_name=%s | error=%s",
                email_address,
                mailbox_name,
                exc,
            )
            return False

        logger.warning(
            "Resposta create IMAP | email=%s | mailbox_name=%s | status=%s | data=%s",
            email_address,
            mailbox_name,
            status,
            _safe_text(data),
        )

        if status == "OK":
            return True

        data_text = _safe_text(data).lower()
        if "already exists" in data_text or "já existe" in data_text:
            return True
        return False

    def _ensure_remote_mailbox(self, client, *, email_address: str, folder_slug: str) -> str | None:
        selected = self._select_first_available_mailbox(
            client,
            email_address=email_address,
            folder_slug=folder_slug,
            readonly=False,
        )
        if selected:
            return selected

        if folder_slug == "inbox":
            return None

        for mailbox_name in self._folder_candidates(folder_slug):
            created = self._create_mailbox(
                client,
                email_address=email_address,
                mailbox_name=mailbox_name,
            )
            if not created:
                continue

            try:
                select_status, _select_data = self._select_mailbox(
                    client,
                    email_address=email_address,
                    mailbox_name=mailbox_name,
                    readonly=False,
                )
            except Exception:
                continue

            if select_status == "OK":
                return mailbox_name

        return None

    def _message_id_variants(self, message_id_header: str | None) -> list[str]:
        text = str(message_id_header or "").strip()
        if not text:
            return []

        stripped = text.strip("<>").strip()
        variants: list[str] = []
        for candidate in (text, text.lower(), stripped, stripped.lower(), f"<{stripped}>", f"<{stripped.lower()}>"):
            candidate = str(candidate or "").strip()
            if candidate and candidate not in variants:
                variants.append(candidate)
        return variants

    def _message_id_matches(self, current_value: str | None, expected_value: str | None) -> bool:
        if not current_value or not expected_value:
            return False
        current_variants = set(self._message_id_variants(current_value))
        expected_variants = set(self._message_id_variants(expected_value))
        return bool(current_variants & expected_variants)

    def _search_uids_by_message_id(self, client, *, message_id_header: str) -> list[str]:
        found: list[str] = []
        for query in self._message_id_variants(message_id_header):
            try:
                search_status, search_data = client.uid("search", None, "HEADER", "Message-ID", query)
            except Exception as exc:
                logger.warning(
                    "Exceção no search Message-ID IMAP | query=%s | error=%s",
                    _safe_text(query),
                    exc,
                )
                continue

            logger.warning(
                "Resposta search Message-ID IMAP | query=%s | status=%s | data=%s",
                _safe_text(query),
                search_status,
                _safe_text(search_data),
            )
            if search_status != "OK":
                continue

            raw = (search_data[0] or b"").decode("utf-8", errors="replace").strip() if search_data else ""
            for uid in raw.split():
                uid = uid.strip()
                if uid and uid not in found:
                    found.append(uid)

            if found:
                break

        return found

    def _fetch_message_id_for_uid(self, client, uid: str) -> str | None:
        fetch_status, fetch_data = client.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        logger.warning(
            "Resposta fetch header Message-ID IMAP | uid=%s | status=%s | type=%s",
            uid,
            fetch_status,
            type(fetch_data).__name__,
        )
        if fetch_status != "OK" or not fetch_data:
            return None

        header_bytes = None
        for part in fetch_data:
            if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
                header_bytes = bytes(part[1])
                break

        if not header_bytes:
            return None

        try:
            parsed = BytesParser(policy=policy.default).parsebytes(header_bytes)
            return _decode_header_value(parsed.get("Message-Id"))
        except Exception:
            text = header_bytes.decode("utf-8", errors="replace")
            match = re.search(r"(?im)^message-id:\s*(.+)$", text)
            return match.group(1).strip() if match else None

    def _fallback_scan_matching_uids(self, client, *, message_id_header: str) -> list[str]:
        found: list[str] = []

        search_status, search_data = client.uid("search", None, "ALL")
        logger.warning(
            "Fallback scan search IMAP | status=%s | data=%s",
            search_status,
            _safe_text(search_data),
        )
        if search_status != "OK":
            return found

        raw_uids = (search_data[0] or b"").decode("utf-8", errors="replace").strip() if search_data else ""
        if not raw_uids:
            return found

        for uid in [item for item in raw_uids.split() if item.strip()]:
            current_message_id = self._fetch_message_id_for_uid(client, uid)
            if self._message_id_matches(current_message_id, message_id_header):
                found.append(uid)

        return found

    def _find_uids_in_selected_mailbox(self, client, *, message_id_header: str) -> list[str]:
        found = self._search_uids_by_message_id(client, message_id_header=message_id_header)
        if found:
            return found
        return self._fallback_scan_matching_uids(client, message_id_header=message_id_header)

    def _discover_message_locations(
        self,
        client,
        *,
        email_address: str,
        message_id_header: str,
        preferred_folder: str | None = None,
    ) -> list[dict[str, Any]]:
        folder_order = []
        for slug in [preferred_folder, "inbox", "trash", "junk", "sent", "drafts"]:
            normalized = str(slug or "").strip().lower()
            if normalized and normalized not in folder_order:
                folder_order.append(normalized)

        found_locations: list[dict[str, Any]] = []

        for folder_slug in folder_order:
            mailbox_name = self._select_first_available_mailbox(
                client,
                email_address=email_address,
                folder_slug=folder_slug,
                readonly=False,
            )
            if not mailbox_name:
                continue

            uids = self._find_uids_in_selected_mailbox(
                client,
                message_id_header=message_id_header,
            )
            if not uids:
                continue

            found_locations.append(
                {
                    "folder_slug": folder_slug,
                    "mailbox_name": mailbox_name,
                    "uids": uids,
                }
            )

        return found_locations

    def _delete_uid_in_mailbox(
        self,
        client,
        *,
        email_address: str,
        folder_slug: str,
        mailbox_name: str,
        uid: str,
    ) -> None:
        self._select_mailbox(
            client,
            email_address=email_address,
            mailbox_name=mailbox_name,
            readonly=False,
        )

        store_status, store_data = client.uid("store", uid, "+FLAGS.SILENT", "(\\Deleted)")
        logger.warning(
            "Resposta STORE delete definitivo IMAP | folder_slug=%s | mailbox_name=%s | uid=%s | status=%s | data=%s",
            folder_slug,
            mailbox_name,
            uid,
            store_status,
            _safe_text(store_data),
        )
        if store_status != "OK":
            raise ImapSyncError("Falha ao marcar a mensagem como deletada no servidor IMAP.")

        expunge_status, expunge_data = client.expunge()
        logger.warning(
            "Resposta EXPUNGE delete definitivo IMAP | folder_slug=%s | mailbox_name=%s | status=%s | data=%s",
            folder_slug,
            mailbox_name,
            expunge_status,
            _safe_text(expunge_data),
        )
        if expunge_status != "OK":
            raise ImapSyncError("Falha ao expurgar a mensagem no servidor IMAP.")

    def _move_uid_between_mailboxes(
        self,
        client,
        *,
        email_address: str,
        source_folder_slug: str,
        source_mailbox_name: str,
        target_folder_slug: str,
        target_mailbox_name: str,
        uid: str,
    ) -> None:
        self._select_mailbox(
            client,
            email_address=email_address,
            mailbox_name=source_mailbox_name,
            readonly=False,
        )

        move_status, move_data = client.uid("MOVE", uid, self._mailbox_arg(target_mailbox_name))
        logger.warning(
            "Resposta MOVE IMAP | source_folder=%s | source_mailbox=%s | target_folder=%s | target_mailbox=%s | uid=%s | status=%s | data=%s",
            source_folder_slug,
            source_mailbox_name,
            target_folder_slug,
            target_mailbox_name,
            uid,
            move_status,
            _safe_text(move_data),
        )
        if move_status == "OK":
            return

        copy_status, copy_data = client.uid("COPY", uid, self._mailbox_arg(target_mailbox_name))
        logger.warning(
            "Resposta COPY IMAP | source_folder=%s | source_mailbox=%s | target_folder=%s | target_mailbox=%s | uid=%s | status=%s | data=%s",
            source_folder_slug,
            source_mailbox_name,
            target_folder_slug,
            target_mailbox_name,
            uid,
            copy_status,
            _safe_text(copy_data),
        )
        if copy_status != "OK":
            raise ImapSyncError("Falha ao copiar a mensagem para a pasta remota de destino.")

        self._delete_uid_in_mailbox(
            client,
            email_address=email_address,
            folder_slug=source_folder_slug,
            mailbox_name=source_mailbox_name,
            uid=uid,
        )

    def fetch_folder_messages(
        self,
        *,
        email_address: str,
        password: str,
        folder_slug: str = "inbox",
        limit: int | None = None,
    ) -> list[RemoteMessage]:
        sync_limit = int(limit or self.sync_limit or 30)
        if sync_limit <= 0:
            sync_limit = 30

        logger.warning(
            "Iniciando fetch IMAP da pasta | email=%s | folder_slug=%s | candidates=%s | sync_limit=%s | host=%s | port=%s | use_ssl=%s | use_starttls=%s | verify_ssl=%s | password_len=%s",
            email_address,
            folder_slug,
            self._folder_candidates(folder_slug),
            sync_limit,
            self.host,
            self.port,
            self.use_ssl,
            self.use_starttls,
            self.verify_ssl,
            len(password or ""),
        )

        client = None

        try:
            client = self._connect_authenticated(email_address, password)

            selected_mailbox = self._select_first_available_mailbox(
                client,
                email_address=email_address,
                folder_slug=folder_slug,
                readonly=True,
            )

            if not selected_mailbox:
                if folder_slug == "junk":
                    logger.warning(
                        "Nenhuma pasta junk encontrada no IMAP | email=%s | candidates=%s",
                        email_address,
                        self._folder_candidates(folder_slug),
                    )
                    return []
                raise ImapSyncError("Não consegui abrir a pasta remota para sincronização.")

            search_status, search_data = client.uid("search", None, "ALL")
            logger.warning(
                "Resposta search IMAP | email=%s | folder_slug=%s | selected_mailbox=%s | status=%s | raw=%s",
                email_address,
                folder_slug,
                selected_mailbox,
                search_status,
                _safe_text(search_data),
            )
            if search_status != "OK":
                raise ImapSyncError("Falha ao listar mensagens via IMAP.")

            raw_uids = (search_data[0] or b"").decode("utf-8", errors="replace").strip()
            logger.warning(
                "UIDs brutos retornados pelo IMAP | email=%s | folder_slug=%s | selected_mailbox=%s | raw_uids=%s",
                email_address,
                folder_slug,
                selected_mailbox,
                _safe_text(raw_uids, 500),
            )

            if not raw_uids:
                logger.warning(
                    "Pasta IMAP vazia | email=%s | folder_slug=%s | selected_mailbox=%s",
                    email_address,
                    folder_slug,
                    selected_mailbox,
                )
                return []

            all_uids = [uid for uid in raw_uids.split() if uid.strip()]
            wanted_uids = all_uids[-sync_limit:]

            logger.warning(
                "UIDs processados para sync | email=%s | folder_slug=%s | selected_mailbox=%s | total_uids=%s | wanted_uids=%s",
                email_address,
                folder_slug,
                selected_mailbox,
                len(all_uids),
                wanted_uids,
            )

            items: list[RemoteMessage] = []

            for uid in wanted_uids:
                logger.warning(
                    "Fazendo fetch da mensagem IMAP | email=%s | folder_slug=%s | selected_mailbox=%s | uid=%s",
                    email_address,
                    folder_slug,
                    selected_mailbox,
                    uid,
                )

                fetch_status, fetch_data = client.uid("fetch", uid, "(RFC822 FLAGS)")
                logger.warning(
                    "Resposta fetch IMAP | email=%s | folder_slug=%s | uid=%s | status=%s | fetch_data_type=%s",
                    email_address,
                    folder_slug,
                    uid,
                    fetch_status,
                    type(fetch_data).__name__,
                )

                if fetch_status != "OK" or not fetch_data:
                    logger.warning(
                        "Fetch ignorado | email=%s | folder_slug=%s | uid=%s | status=%s | has_data=%s",
                        email_address,
                        folder_slug,
                        uid,
                        fetch_status,
                        bool(fetch_data),
                    )
                    continue

                message_bytes, flags_blob = _extract_fetch_parts(fetch_data)
                logger.warning(
                    "Partes extraídas do fetch | email=%s | folder_slug=%s | uid=%s | message_bytes=%s | flags=%s",
                    email_address,
                    folder_slug,
                    uid,
                    len(message_bytes) if message_bytes else 0,
                    _safe_text(flags_blob),
                )

                if not message_bytes:
                    logger.warning(
                        "Mensagem sem payload RFC822 | email=%s | folder_slug=%s | uid=%s",
                        email_address,
                        folder_slug,
                        uid,
                    )
                    continue

                message = BytesParser(policy=policy.default).parsebytes(message_bytes)

                from_name, from_email = parseaddr(message.get("From") or "")
                from_name = _decode_header_value(from_name)
                from_email = _normalize_email(from_email) or "unknown@unknown.local"

                to_pairs = _extract_email_list(message.get("To"))
                cc_pairs = _extract_email_list(message.get("Cc"))

                to_email = ", ".join(email for _, email in to_pairs) or email_address
                cc_email = ", ".join(email for _, email in cc_pairs) or None

                subject = _decode_header_value(message.get("Subject"))
                body_text, body_html = _extract_text_bodies(message)
                message_id_header = (
                    _decode_header_value(message.get("Message-Id"))
                    or _build_fallback_message_id(uid, email_address)
                )
                sent_at = _parse_sent_at(message.get("Date"))
                raw_source = message_bytes.decode("utf-8", errors="replace")

                logger.warning(
                    "Mensagem IMAP parseada | email=%s | folder_slug=%s | uid=%s | message_id=%s | from=%s | to=%s | subject=%s | sent_at=%s | is_read=%s | raw_len=%s",
                    email_address,
                    folder_slug,
                    uid,
                    message_id_header,
                    from_email,
                    to_email,
                    _safe_text(subject),
                    sent_at.isoformat() if sent_at else None,
                    _flags_to_is_read(flags_blob),
                    len(raw_source or ""),
                )

                items.append(
                    RemoteMessage(
                        uid=uid,
                        message_id_header=message_id_header,
                        from_name=from_name,
                        from_email=from_email,
                        to_email=to_email,
                        cc_email=cc_email,
                        subject=subject,
                        preview=_preview_from_body(body_text),
                        body_text=body_text,
                        body_html=body_html,
                        raw_source=raw_source,
                        sent_at=sent_at,
                        is_read=_flags_to_is_read(flags_blob),
                    )
                )

            logger.warning(
                "Fetch IMAP concluído | email=%s | folder_slug=%s | selected_mailbox=%s | total_items=%s",
                email_address,
                folder_slug,
                selected_mailbox,
                len(items),
            )
            return items

        except ImapSyncError:
            raise
        except Exception as exc:
            logger.exception("Erro inesperado durante fetch IMAP | email=%s | folder_slug=%s", email_address, folder_slug)
            raise ImapSyncError(f"Erro inesperado ao sincronizar IMAP: {exc}") from exc
        finally:
            if client is not None:
                self._safe_logout(client)

    def fetch_inbox_messages(
        self,
        *,
        email_address: str,
        password: str,
        limit: int | None = None,
    ) -> list[RemoteMessage]:
        return self.fetch_folder_messages(
            email_address=email_address,
            password=password,
            folder_slug="inbox",
            limit=limit,
        )

    def move_message_by_message_id(
        self,
        *,
        email_address: str,
        password: str,
        message_id_header: str,
        target_folder: str,
        preferred_source_folder: str | None = None,
    ) -> dict[str, Any]:
        normalized_message_id = str(message_id_header or "").strip()
        target_slug = (target_folder or "inbox").strip().lower()
        if not normalized_message_id:
            return {"moved": False, "moved_total": 0, "not_found": True, "already_in_target": False}

        client = None
        try:
            client = self._connect_authenticated(email_address, password)

            locations = self._discover_message_locations(
                client,
                email_address=email_address,
                message_id_header=normalized_message_id,
                preferred_folder=preferred_source_folder,
            )

            if not locations:
                logger.warning(
                    "Mensagem não localizada para move IMAP | email=%s | preferred_source_folder=%s | target_folder=%s | message_id=%s",
                    email_address,
                    preferred_source_folder,
                    target_slug,
                    _safe_text(normalized_message_id),
                )
                return {"moved": False, "moved_total": 0, "not_found": True, "already_in_target": False}

            if target_slug == "inbox":
                target_mailbox_name = self._select_first_available_mailbox(
                    client,
                    email_address=email_address,
                    folder_slug="inbox",
                    readonly=False,
                ) or "INBOX"
            else:
                target_mailbox_name = self._ensure_remote_mailbox(
                    client,
                    email_address=email_address,
                    folder_slug=target_slug,
                )

            if not target_mailbox_name:
                raise ImapSyncError(f"Não consegui abrir ou criar a pasta remota '{target_slug}'.")

            moved_total = 0
            already_in_target = False
            seen_pairs: set[tuple[str, str]] = set()

            for location in locations:
                source_folder_slug = str(location.get("folder_slug") or "").strip().lower()
                source_mailbox_name = str(location.get("mailbox_name") or "").strip()
                uids = [str(uid).strip() for uid in location.get("uids") or [] if str(uid).strip()]
                if not source_mailbox_name:
                    continue

                if source_folder_slug == target_slug and source_mailbox_name == target_mailbox_name:
                    already_in_target = True
                    continue

                for uid in uids:
                    key = (source_mailbox_name, uid)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    self._move_uid_between_mailboxes(
                        client,
                        email_address=email_address,
                        source_folder_slug=source_folder_slug or "inbox",
                        source_mailbox_name=source_mailbox_name,
                        target_folder_slug=target_slug,
                        target_mailbox_name=target_mailbox_name,
                        uid=uid,
                    )
                    moved_total += 1

            logger.warning(
                "Movimentação remota IMAP concluída | email=%s | preferred_source_folder=%s | target_folder=%s | target_mailbox=%s | moved_total=%s | already_in_target=%s | message_id=%s",
                email_address,
                preferred_source_folder,
                target_slug,
                target_mailbox_name,
                moved_total,
                already_in_target,
                _safe_text(normalized_message_id),
            )

            return {
                "moved": moved_total > 0,
                "moved_total": moved_total,
                "target_mailbox": target_mailbox_name,
                "not_found": False,
                "already_in_target": already_in_target,
            }

        except ImapSyncError:
            raise
        except Exception as exc:
            logger.exception("Erro inesperado ao mover mensagem no IMAP | email=%s | target_folder=%s", email_address, target_slug)
            raise ImapSyncError(f"Erro inesperado ao mover mensagem no IMAP: {exc}") from exc
        finally:
            if client is not None:
                self._safe_logout(client)

    def delete_message_by_message_id(
        self,
        *,
        email_address: str,
        password: str,
        message_id_header: str,
        preferred_folder: str | None = None,
    ) -> dict[str, Any]:
        normalized_message_id = str(message_id_header or "").strip()
        if not normalized_message_id:
            return {
                "deleted_total": 0,
                "deleted_from": [],
                "deleted_uids": [],
                "not_found": True,
            }

        client = None
        try:
            client = self._connect_authenticated(email_address, password)

            locations = self._discover_message_locations(
                client,
                email_address=email_address,
                message_id_header=normalized_message_id,
                preferred_folder=preferred_folder,
            )

            if not locations:
                logger.warning(
                    "Mensagem não localizada para exclusão IMAP | email=%s | preferred_folder=%s | message_id=%s",
                    email_address,
                    preferred_folder,
                    _safe_text(normalized_message_id),
                )
                return {
                    "deleted_total": 0,
                    "deleted_from": [],
                    "deleted_uids": [],
                    "not_found": True,
                }

            deleted_total = 0
            deleted_from: list[str] = []
            deleted_uids: list[str] = []
            seen_pairs: set[tuple[str, str]] = set()

            for location in locations:
                folder_slug = str(location.get("folder_slug") or "").strip().lower()
                mailbox_name = str(location.get("mailbox_name") or "").strip()
                uids = [str(uid).strip() for uid in location.get("uids") or [] if str(uid).strip()]
                if not mailbox_name:
                    continue

                for uid in uids:
                    key = (mailbox_name, uid)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)

                    self._delete_uid_in_mailbox(
                        client,
                        email_address=email_address,
                        folder_slug=folder_slug or "inbox",
                        mailbox_name=mailbox_name,
                        uid=uid,
                    )
                    deleted_total += 1
                    deleted_uids.append(uid)
                    if folder_slug and folder_slug not in deleted_from:
                        deleted_from.append(folder_slug)

            logger.warning(
                "Exclusão remota IMAP concluída | email=%s | preferred_folder=%s | deleted_total=%s | deleted_from=%s | deleted_uids=%s",
                email_address,
                preferred_folder,
                deleted_total,
                deleted_from,
                deleted_uids,
            )

            return {
                "deleted_total": deleted_total,
                "deleted_from": deleted_from,
                "deleted_uids": deleted_uids,
                "not_found": deleted_total == 0,
            }

        except ImapSyncError:
            raise
        except Exception as exc:
            logger.exception("Erro inesperado ao excluir mensagem no IMAP | email=%s", email_address)
            raise ImapSyncError(f"Erro inesperado ao excluir mensagem no IMAP: {exc}") from exc
        finally:
            if client is not None:
                self._safe_logout(client)


_imap_singleton: AureMailImapClient | None = None


def get_imap_client() -> AureMailImapClient:
    global _imap_singleton
    if _imap_singleton is None:
        logger.warning("Criando singleton do cliente IMAP")
        _imap_singleton = AureMailImapClient()
    else:
        logger.warning(
            "Reutilizando singleton do cliente IMAP | host=%s | port=%s | use_ssl=%s | use_starttls=%s",
            _imap_singleton.host or None,
            _imap_singleton.port,
            _imap_singleton.use_ssl,
            _imap_singleton.use_starttls,
        )
    return _imap_singleton
