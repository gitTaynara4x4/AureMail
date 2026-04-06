from __future__ import annotations

import imaplib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html import unescape
from typing import Any


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
    pairs = []
    for name, email in getaddresses([value or ""]):
        email_norm = _normalize_email(email)
        if email_norm:
            pairs.append((_decode_header_value(name), email_norm))
    return pairs


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</p\s*>", "\n\n", text)
    text = re.sub(r"(?s)<.*?>", " ", text)
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

            if not payload:
                continue

            if content_type == "text/plain":
                plain_parts.append(str(payload))
            elif content_type == "text/html":
                html_parts.append(str(payload))
    else:
        try:
            payload = message.get_content()
        except Exception:
            raw = message.get_payload(decode=True) or b""
            charset = message.get_content_charset() or "utf-8"
            payload = raw.decode(charset, errors="replace")

        content_type = message.get_content_type()
        if content_type == "text/plain":
            plain_parts.append(str(payload))
        elif content_type == "text/html":
            html_parts.append(str(payload))

    body_text = "\n\n".join([part.strip() for part in plain_parts if str(part).strip()]) or None
    body_html = "\n".join([part.strip() for part in html_parts if str(part).strip()]) or None

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
    text = flags_blob.decode("utf-8", errors="replace") if isinstance(flags_blob, bytes) else str(flags_blob)
    return "\\Seen" in text


class AureMailImapClient:
    def __init__(self) -> None:
        self.host = (os.getenv("AUREMAIL_IMAP_HOST", "") or "").strip() or (
            os.getenv("AUREMAIL_MAIL_SERVER_HOST", "") or ""
        ).strip()
        self.port = int((os.getenv("AUREMAIL_IMAP_PORT", "993") or "993").strip())
        self.timeout = int((os.getenv("AUREMAIL_IMAP_TIMEOUT", "20") or "20").strip())
        self.mailbox_name = (os.getenv("AUREMAIL_IMAP_INBOX_NAME", "INBOX") or "INBOX").strip()
        self.sync_limit = int((os.getenv("AUREMAIL_IMAP_SYNC_LIMIT", "30") or "30").strip())
        self.use_ssl = (os.getenv("AUREMAIL_IMAP_SSL", "true") or "true").strip().lower() == "true"

    def ensure_enabled(self) -> None:
        if not self.host:
            raise ImapSyncError("AUREMAIL_IMAP_HOST não configurado no .env.")

    def _connect(self):
        self.ensure_enabled()
        imaplib._MAXLINE = max(imaplib._MAXLINE, 10_000_000)

        try:
            if self.use_ssl:
                return imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
            client = imaplib.IMAP4(self.host, self.port, timeout=self.timeout)
            try:
                client.starttls()
            except Exception:
                pass
            return client
        except Exception as exc:
            raise ImapSyncError(f"Não foi possível conectar ao IMAP: {exc}") from exc

    def fetch_inbox_messages(
        self,
        *,
        email_address: str,
        password: str,
        limit: int | None = None,
    ) -> list[RemoteMessage]:
        sync_limit = int(limit or self.sync_limit or 30)

        try:
            with self._connect() as client:
                login_status, login_data = client.login(email_address, password)
                if login_status != "OK":
                    raise ImapSyncError(f"Falha no login IMAP: {login_data}")

                select_status, _ = client.select(self.mailbox_name, readonly=True)
                if select_status != "OK":
                    raise ImapSyncError(f"Não consegui abrir a caixa {self.mailbox_name}.")

                search_status, search_data = client.uid("search", None, "ALL")
                if search_status != "OK":
                    raise ImapSyncError("Falha ao listar mensagens via IMAP.")

                raw_uids = (search_data[0] or b"").decode("utf-8", errors="replace").strip()
                if not raw_uids:
                    return []

                all_uids = [uid for uid in raw_uids.split() if uid.strip()]
                wanted_uids = all_uids[-sync_limit:]

                items: list[RemoteMessage] = []

                for uid in wanted_uids:
                    fetch_status, fetch_data = client.uid("fetch", uid, "(RFC822 FLAGS)")
                    if fetch_status != "OK" or not fetch_data:
                        continue

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

                    if not message_bytes:
                        continue

                    message = BytesParser(policy=policy.default).parsebytes(message_bytes)

                    from_name, from_email = parseaddr(message.get("From") or "")
                    from_name = _decode_header_value(from_name)
                    from_email = _normalize_email(from_email)

                    to_pairs = _extract_email_list(message.get("To"))
                    cc_pairs = _extract_email_list(message.get("Cc"))

                    to_email = ", ".join([email for _, email in to_pairs]) or email_address
                    cc_email = ", ".join([email for _, email in cc_pairs]) or None

                    subject = _decode_header_value(message.get("Subject"))
                    body_text, body_html = _extract_text_bodies(message)
                    message_id_header = _decode_header_value(message.get("Message-Id")) or _build_fallback_message_id(uid, email_address)
                    sent_at = _parse_sent_at(message.get("Date"))
                    raw_source = message_bytes.decode("utf-8", errors="replace")

                    items.append(
                        RemoteMessage(
                            uid=uid,
                            message_id_header=message_id_header,
                            from_name=from_name,
                            from_email=from_email or email_address,
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

                return items

        except ImapSyncError:
            raise
        except Exception as exc:
            raise ImapSyncError(f"Erro inesperado ao sincronizar IMAP: {exc}") from exc


_imap_singleton: AureMailImapClient | None = None


def get_imap_client() -> AureMailImapClient:
    global _imap_singleton
    if _imap_singleton is None:
        _imap_singleton = AureMailImapClient()
    return _imap_singleton