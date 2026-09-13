"""Gmail SMTP delivery with a persistent, independent email outbox."""
import hashlib
import html
import json
import logging
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

from .dedupe import save_state

LOG = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


class EmailError(Exception):
    def __init__(self, message: str, retryable: bool = False, uncertain: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.uncertain = uncertain


def validate_address(value: str, setting: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value):
        raise ValueError(f"{setting} must be one plain email address")
    return value


@dataclass(frozen=True, repr=False)
class GmailClient:
    sender: str
    recipient: str
    password: str

    @classmethod
    def from_environment(cls) -> "GmailClient":
        names = ("EMAIL_SENDER", "EMAIL_RECIPIENT", "EMAIL_PASSWORD")
        values = [os.environ.get(name, "").strip() for name in names]
        missing = [name for name, value in zip(names, values) if not value]
        if missing:
            raise ValueError("Missing email settings: " + ", ".join(missing))
        return cls(validate_address(values[0], names[0]), validate_address(values[1], names[1]),
                   values[2].replace(" ", ""))

    def send(self, item: dict, key: str) -> str:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = self.recipient
        message["Subject"] = item["subject"]
        message["Date"] = formatdate(localtime=False)
        sender_id = hashlib.sha256(self.sender.casefold().encode()).hexdigest()[:12]
        message_id = f"<bubu-jobs-{key}-{sender_id}@{self.sender.split('@')[1]}>"
        message["Message-ID"] = message_id
        message.set_content(item["text"])
        message.add_alternative(item["html"], subtype="html")
        smtp = None
        sending = False
        try:
            smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30,
                                    context=ssl.create_default_context())
            smtp.login(self.sender, self.password)
            sending = True
            refused = smtp.send_message(message)
            if refused:
                raise EmailError("SMTP refused the recipient")
            return message_id  # SMTP accepted; not a read receipt or delivery guarantee.
        except smtplib.SMTPAuthenticationError:
            raise EmailError("Gmail authentication failed; check EMAIL_SENDER and its App Password") from None
        except smtplib.SMTPRecipientsRefused as error:
            transient = all(400 <= value[0] < 500 for value in error.recipients.values())
            raise EmailError("SMTP refused the recipient", retryable=transient) from None
        except smtplib.SMTPResponseException as error:
            raise EmailError(f"SMTP rejected the request (status {error.smtp_code})",
                             retryable=400 <= error.smtp_code < 500) from None
        except (OSError, smtplib.SMTPException):
            raise EmailError("SMTP connection failed" + ("; send outcome is uncertain" if sending else " before sending"),
                             retryable=not sending, uncertain=sending) from None
        finally:
            if smtp is not None:
                # Closing must not turn an already accepted message into a failed send.
                try:
                    smtp.close()
                except OSError:
                    pass


def render_digest(jobs: list[dict], test: bool = False) -> tuple[str, str, str]:
    subject = "[bubu-jobs] Email test" if test else f"[bubu-jobs] {len(jobs)} new job match(es)"
    intro = ("This is a test of email alerts from your account to yourself. No application was submitted."
             if test else "New Product Management matches from the Jobright README:")
    text = [subject, "", intro]
    cards = []
    for job in jobs:
        url = job.get("canonical_apply_url") or job["source_url"]
        lines = [f"Company: {job['company']}", f"Title: {job['title']}",
                 f"Location: {job['location']}", f"Work model: {job['work_model']}",
                 f"Date posted: {job['date_posted']}", f"ATS: {job['ats']}", f"Apply: {url}"]
        text.extend(["", *lines])
        e = html.escape
        cards.append(f'<div style="border-top:1px solid #ddd;padding:16px 0">'
                     f'<h2 style="font-size:18px;margin:0 0 8px">{e(job["title"])}</h2>'
                     f'<p><strong>{e(job["company"])}</strong><br>{e(job["location"])} · {e(job["work_model"])}</p>'
                     f'<p>Posted: {e(job["date_posted"])} · ATS: {e(job["ats"])}</p>'
                     f'<a href="{e(url, quote=True)}">View job / apply</a></div>')
    footer = "You receive this digest only when new relevant jobs are discovered (or a saved delivery retries)."
    text.extend(["", footer])
    body = (f'<html><body style="font-family:Arial,sans-serif;max-width:640px;margin:auto;padding:24px;color:#222">'
            f'<h1 style="font-size:24px">{html.escape(subject)}</h1><p>{html.escape(intro)}</p>'
            + "".join(cards) + f'<p style="color:#666;font-size:12px">{footer}</p></body></html>')
    return subject, "\n".join(text), body


def enqueue_email(state: dict, jobs: list[dict], test: bool = False) -> None:
    outbox = state.setdefault("email", {})
    if test:
        subject, text, body = render_digest([], test=True)
        outbox.setdefault("test-v1", {"job_ids": [], "subject": subject, "text": text, "html": body,
                                      "status": "pending", "attempts": 0})
    if jobs:
        ids = sorted(job["job_id"] for job in jobs)
        key = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
        subject, text, body = render_digest(jobs)
        outbox.setdefault(key, {"job_ids": ids, "subject": subject, "text": text, "html": body,
                               "status": "pending", "attempts": 0})


def migrate_unsent_sms(state: dict) -> None:
    """Carry only failed/pending job alerts into email, not the original seen backlog."""
    if state.get("email_migrated"):
        return
    ids = {job_id for item in state.get("sms", {}).values()
           if item["status"] in {"pending", "blocked"} for job_id in item["job_ids"]}
    covered = {job_id for item in state.get("email", {}).values() for job_id in item["job_ids"]}
    enqueue_email(state, [state["jobs"][key] for key in sorted(ids - covered)])
    state["email_migrated"] = True


def deliver_email(state: dict, path: Path, client: GmailClient) -> None:
    outbox = state.get("email", {})
    for item in outbox.values():
        if item["status"] == "sending":
            item["status"] = "uncertain"
    save_state(path, state)
    blocked = [key for key, item in outbox.items() if item["status"] in {"blocked", "uncertain"}]
    if blocked:
        raise EmailError("Email needs attention; inspect Sent mail before --retry-email " + blocked[0])
    # The explicit connection test goes first. One outgoing email per invocation.
    keys = sorted(outbox, key=lambda key: (key != "test-v1", key))
    for key in keys:
        item = outbox[key]
        if item["status"] != "pending":
            continue
        item.update(status="sending", attempts=item["attempts"] + 1)
        save_state(path, state)
        try:
            item["message_id"] = client.send(item, key)
            item["status"] = "submitted"
            item.pop("error", None)
        except EmailError as error:
            item["status"] = ("uncertain" if error.uncertain else "pending"
                              if error.retryable and item["attempts"] < MAX_ATTEMPTS else "blocked")
            item["error"] = str(error)
            save_state(path, state)
            raise
        save_state(path, state)
        LOG.warning("Email %s submitted to SMTP (attempt %d)", key, item["attempts"])
        return
