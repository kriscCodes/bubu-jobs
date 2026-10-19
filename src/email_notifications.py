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
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path
from typing import Optional

from .dedupe import save_state
from .html_email import PANDA_IMAGE_PATH, PANDA_CID, PANDA_GITHUB_URL, LEGACY_PANDA_GITHUB_URLS

LOG = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def build_mime_message_with_cid(
    sender: str,
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str,
    message_id: str,
) -> MIMEMultipart:
    """Build a multipart/related MIME message with inline panda image.
    
    Structure:
        multipart/related
        ├── multipart/alternative
        │   ├── text/plain
        │   └── text/html (with src="cid:panda-hero")
        └── image/jpeg (Content-ID: <panda-hero>, Content-Disposition: inline)
    
    Args:
        sender: From address
        recipient: To address
        subject: Email subject
        text_body: Plain text content
        html_body: HTML content (should reference cid:panda-hero for the image)
        message_id: Message-ID header value
    
    Returns:
        Complete MIME message ready to send
    """
    msg_related = MIMEMultipart("related")
    msg_related["From"] = sender
    msg_related["To"] = recipient
    msg_related["Subject"] = subject
    msg_related["Date"] = formatdate(localtime=False)
    msg_related["Message-ID"] = message_id
    
    msg_alternative = MIMEMultipart("alternative")
    
    part_text = MIMEText(text_body, "plain", "utf-8")
    msg_alternative.attach(part_text)
    
    part_html = MIMEText(html_body, "html", "utf-8")
    msg_alternative.attach(part_html)
    
    msg_related.attach(msg_alternative)
    
    if PANDA_IMAGE_PATH.exists():
        with open(PANDA_IMAGE_PATH, "rb") as f:
            image_data = f.read()
        
        part_image = MIMEImage(image_data, _subtype="jpeg")
        part_image.add_header("Content-ID", f"<{PANDA_CID}>")
        part_image.add_header("Content-Disposition", "inline", filename="panda-hero.jpg")
        msg_related.attach(part_image)
    else:
        LOG.warning("Panda image not found at %s, skipping CID attachment", PANDA_IMAGE_PATH)
    
    return msg_related


def generate_test_eml(recipient: str, subject: str) -> tuple[str, str]:
    """Generate a complete RFC822 test message as .eml and the HTML part.
    
    Args:
        recipient: Email address to send to
        subject: Email subject line
    
    Returns:
        Tuple of (eml_content, html_content) - both as strings
    """
    from .html_email import render_sample_email_for_preview
    
    html_body, text_body = render_sample_email_for_preview(use_cid=True)
    
    sender_domain = "bubu-jobs.local"
    message_id = f"<test-preview-{hashlib.sha256(subject.encode()).hexdigest()[:12]}@{sender_domain}>"
    
    msg = build_mime_message_with_cid(
        sender="noreply@bubu-jobs.local",
        recipient=recipient,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        message_id=message_id,
    )
    
    return msg.as_string(), html_body


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

    def send(self, item: dict, key: str, override_recipient: Optional[str] = None, use_cid: bool = True) -> str:
        """Send an email with the panda image as CID inline attachment.
        
        Args:
            item: Dict with 'subject', 'text', 'html' keys
            key: Unique key for this email (used in Message-ID)
            override_recipient: Send to this address instead of default recipient
            use_cid: If True, build multipart/related with CID attachment.
                     If False, use simple multipart/alternative.
        
        Returns:
            Message-ID of sent email
        """
        recipient = override_recipient or self.recipient
        sender_id = hashlib.sha256(self.sender.casefold().encode()).hexdigest()[:12]
        message_id = f"<bubu-jobs-{key}-{sender_id}@{self.sender.split('@')[1]}>"
        
        if use_cid:
            from .html_email import render_html_email, render_plain_text_email, create_job_cards_from_jobs, render_sample_email_for_preview
            if "html_cid" in item:
                html_body = item["html_cid"]
            else:
                html_body = item["html"]
                for hosted in (PANDA_GITHUB_URL, *LEGACY_PANDA_GITHUB_URLS):
                    html_body = html_body.replace(hosted, f"cid:{PANDA_CID}")
            message = build_mime_message_with_cid(
                sender=self.sender,
                recipient=recipient,
                subject=item["subject"],
                text_body=item["text"],
                html_body=html_body,
                message_id=message_id,
            )
        else:
            message = EmailMessage()
            message["From"] = self.sender
            message["To"] = recipient
            message["Subject"] = item["subject"]
            message["Date"] = formatdate(localtime=False)
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
    falling back to each job's canonical or source URL. Includes source name,
    posted date, pay range, and application question indicators when available.
    """
    from .html_email import (JobCard, render_html_email, render_plain_text_email,
                            render_sample_email_for_preview, _is_jobright_url)
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
        source = job.get("source", "")
        apply_url = direct_link.direct_url if direct_link else fallback_url
        is_direct = bool(direct_link) or not _is_jobright_url(apply_url)
        
        cards.append(JobCard(
            company=company,
            title=title,
            location=location,
            date=date_posted,
            apply_url=apply_url,
            is_direct_link=is_direct,
            source_note=direct_link.note if direct_link else "",
            work_model=work_model,
            ats=ats,
            pay_range=pay_range,
            has_written_questions=has_written_questions,
            source=source,
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
    Uses CID inline attachment for the panda image for Gmail compatibility.
    
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
    
    html_body_cid, text_body = render_sample_email_for_preview(use_cid=True)
    html_body_hosted, _ = render_sample_email_for_preview(use_cid=False)
    item = {
        "subject": "[TEST v5] New PM Jobs - Bubu Jobs",
        "text": text_body,
        "html": html_body_hosted,
        "html_cid": html_body_cid,
    }
    
    LOG.info("Sending test email to %s with CID panda attachment", recipient)
    message_id = client.send(item, "design-test-v1", override_recipient=recipient, use_cid=True)
    LOG.info("Test email sent: %s", message_id)
    return message_id
