from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


class SmtpDeliveryError(RuntimeError):
    """Erro amigável para envio SMTP."""


class AureMailSmtpClient:
    def __init__(self) -> None:
        self.host = (os.getenv("AUREMAIL_SMTP_HOST", "") or "").strip() or (
            os.getenv("AUREMAIL_MAIL_SERVER_HOST", "") or ""
        ).strip()
        self.port = int((os.getenv("AUREMAIL_SMTP_PORT", "587") or "587").strip())
        self.timeout = int((os.getenv("AUREMAIL_SMTP_TIMEOUT", "20") or "20").strip())
        self.use_starttls = (os.getenv("AUREMAIL_SMTP_STARTTLS", "true") or "true").strip().lower() == "true"
        self.use_ssl = (os.getenv("AUREMAIL_SMTP_SSL", "false") or "false").strip().lower() == "true"

    def ensure_enabled(self) -> None:
        if not self.host:
            raise SmtpDeliveryError(
                "AUREMAIL_SMTP_HOST não está configurado no .env."
            )

    def send_message(
        self,
        *,
        username: str,
        password: str,
        from_email: str,
        to_email: str,
        subject: str | None,
        body_text: str | None,
        from_name: str | None = None,
    ) -> str:
        self.ensure_enabled()

        msg = EmailMessage()
        msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
        msg["To"] = to_email
        msg["Subject"] = subject or ""
        msg["Date"] = formatdate(localtime=True)

        message_id = make_msgid(domain=from_email.split("@", 1)[-1])
        msg["Message-ID"] = message_id

        msg.set_content(body_text or "")

        try:
            if self.use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context) as server:
                    server.login(username, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                    server.ehlo()
                    if self.use_starttls:
                        context = ssl.create_default_context()
                        server.starttls(context=context)
                        server.ehlo()
                    server.login(username, password)
                    server.send_message(msg)

            return str(message_id)
        except smtplib.SMTPException as exc:
            raise SmtpDeliveryError(f"Falha ao enviar e-mail via SMTP: {exc}") from exc
        except Exception as exc:
            raise SmtpDeliveryError(f"Erro ao conectar/enviar via SMTP: {exc}") from exc


_smtp_singleton: AureMailSmtpClient | None = None


def get_smtp_client() -> AureMailSmtpClient:
    global _smtp_singleton
    if _smtp_singleton is None:
        _smtp_singleton = AureMailSmtpClient()
    return _smtp_singleton