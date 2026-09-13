"""
email_handler.py
All email-sending logic lives here: single sends, bulk sends, HTML templating
with dynamic placeholders, attachments, and open-rate tracking pixels.
"""

import os
import re
import smtplib
import logging
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger(__name__)


class EmailHandler:
    def __init__(self, sender_email, app_password, smtp_server, smtp_port):
        self.sender_email = sender_email
        self.app_password = app_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port

    # ---------------------------------------------------------------
    # Placeholder rendering, e.g. "Hi {{name}}" -> "Hi Haseeb"
    # ---------------------------------------------------------------
    @staticmethod
    def render_placeholders(text, context):
        """Replace {{placeholder}} tokens in text with values from context dict."""
        if not text:
            return text

        def replace(match):
            key = match.group(1).strip()
            return str(context.get(key, match.group(0)))

        return re.sub(r"\{\{\s*([\w]+)\s*\}\}", replace, text)

    # ---------------------------------------------------------------
    # Build a MIME message (with optional attachments + tracking pixel)
    # ---------------------------------------------------------------
    def _build_message(self, to_email, subject, html_body, attachments=None, tracking_id=None,
                        tracking_base_url=None):
        msg = MIMEMultipart("mixed")
        msg["From"] = self.sender_email
        msg["To"] = to_email
        msg["Subject"] = subject

        alt_part = MIMEMultipart("alternative")

        final_html = html_body
        if tracking_id and tracking_base_url:
            pixel_tag = f'<img src="{tracking_base_url}/track/open/{tracking_id}" width="1" height="1" alt="" />'
            final_html = f"{html_body}{pixel_tag}"

        alt_part.attach(MIMEText(final_html, "html"))
        msg.attach(alt_part)

        for filepath in (attachments or []):
            if not os.path.isfile(filepath):
                continue
            part = MIMEBase("application", "octet-stream")
            with open(filepath, "rb") as f:
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(filepath)
            part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            msg.attach(part)

        return msg

    # ---------------------------------------------------------------
    # Send a single email. Returns (success: bool, error_message: str|None)
    # ---------------------------------------------------------------
    def send_email(self, to_email, subject, html_body, attachments=None,
                    tracking_id=None, tracking_base_url=None):
        try:
            msg = self._build_message(
                to_email, subject, html_body,
                attachments=attachments,
                tracking_id=tracking_id,
                tracking_base_url=tracking_base_url,
            )
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=30) as server:
                server.login(self.sender_email, self.app_password)
                server.send_message(msg)
            logger.info("Email sent to %s", to_email)
            return True, None
        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP auth failed: %s", e)
            return False, "SMTP authentication failed. Check sender email / app password."
        except Exception as e:
            logger.error("Failed to send to %s: %s", to_email, e)
            return False, str(e)

    # ---------------------------------------------------------------
    # Send a test email to verify SMTP settings
    # ---------------------------------------------------------------
    def send_test_email(self, to_email):
        subject = "✅ Test Email - Automated Email Sender"
        body = (
            "<h2>It works! 🎉</h2>"
            "<p>Your SMTP configuration is correct and this app can send emails "
            "successfully.</p>"
        )
        return self.send_email(to_email, subject, body)

    # ---------------------------------------------------------------
    # Bulk send with per-recipient placeholder rendering
    # ---------------------------------------------------------------
    def send_bulk(self, recipients, subject, body, attachments=None,
                   tracking_base_url=None, extra_context=None):
        """
        recipients: list of dicts, each must contain 'email' and may contain
                    other keys used as placeholders (name, company, etc.)
        Returns a list of result dicts: {email, success, error, tracking_id}
        """
        results = []
        for r in recipients:
            email = r.get("email") if isinstance(r, dict) else r
            context = dict(r) if isinstance(r, dict) else {"email": email}
            if extra_context:
                context.update(extra_context)

            rendered_subject = self.render_placeholders(subject, context)
            rendered_body = self.render_placeholders(body, context)
            tracking_id = uuid.uuid4().hex

            success, error = self.send_email(
                email, rendered_subject, rendered_body,
                attachments=attachments,
                tracking_id=tracking_id,
                tracking_base_url=tracking_base_url,
            )
            results.append({
                "email": email,
                "subject": rendered_subject,
                "body": rendered_body,
                "success": success,
                "error": error,
                "tracking_id": tracking_id,
            })
        return results
