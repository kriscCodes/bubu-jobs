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
from typing import Optional

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

    def send(self, item: dict, key: str, override_recipient: Optional[str] = None) -> str:
        recipient = override_recipient or self.recipient
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
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
            return message_id
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
                try:
                    smtp.close()
                except OSError:
                    pass


def render_digest(jobs: list[dict], test: bool = False) -> tuple[str, str, str]:
    """Render email digest with styled HTML and direct links.
    
    Uses the direct_links module to find verified apply URLs when available,
    falling back to Jobright URLs otherwise. Includes pay range and application
    question indicators when available.
    """
    from .html_email import JobCard, render_html_email, render_plain_text_email, render_sample_email_for_preview
    from .direct_links import get_direct_link
    
    subject = "[bubu-jobs] Email test" if test else f"[bubu-jobs] {len(jobs)} new job match(es)"
    
    if test:
        html_body, text_body = render_sample_email_for_preview()
        return subject, text_body, html_body
    
    cards = []
    for job in jobs:
        company = job.get("company", "")
        title = job.get("title", "")
        location = job.get("location", "")
        date_posted = job.get("date_posted", "")
        fallback_url = job.get("canonical_apply_url") or job.get("source_url", "")
        
        try:
            direct_link = get_direct_link(company, title, location)
        except Exception:
            direct_link = None
        
        work_model = job.get("work_model", "")
        ats = job.get("ats", "")
        pay_range = job.get("pay_range", "")
        has_written_questions = job.get("has_written_questions")
        
        if direct_link:
            cards.append(JobCard(
                company=company,
                title=title,
                location=location,
                date=date_posted,
                apply_url=direct_link.direct_url,
                is_direct_link=True,
                source_note=direct_link.note,
                work_model=work_model,
                ats=ats,
                pay_range=pay_range,
                has_written_questions=has_written_questions,
            ))
        else:
            cards.append(JobCard(
                company=company,
                title=title,
                location=location,
                date=date_posted,
                apply_url=fallback_url,
                is_direct_link=False,
                work_model=work_model,
                ats=ats,
                pay_range=pay_range,
                has_written_questions=has_written_questions,
            ))
    
    text_body = render_plain_text_email(cards, subject)
    html_body = render_html_email(cards, subject)
    
    return subject, text_body, html_body


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


def send_test_email_to(recipient: str, client: GmailClient) -> str:
    """Send a single test email with sample job data to a specific recipient.
    
    This is for testing the email design without affecting the normal outbox.
    
    Args:
        recipient: Email address to send to
        client: Configured GmailClient
    
    Returns:
        Message ID of the sent email
    
    Raises:
        EmailError: If sending fails
    """
    from .html_email import render_sample_email_for_preview
    
    validate_address(recipient, "test recipient")
    
    html_body, text_body = render_sample_email_for_preview()
    item = {
        "subject": "[bubu-jobs] Design Preview Test",
        "text": text_body,
        "html": html_body,
    }
    
    LOG.info("Sending test email to %s", recipient)
    message_id = client.send(item, "design-test-v1", override_recipient=recipient)
    LOG.info("Test email sent: %s", message_id)
    return message_id
