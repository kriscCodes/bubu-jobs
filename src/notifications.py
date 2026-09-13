"""Small persistent SMS outbox; credentials and phone numbers never enter state."""
import base64
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .dedupe import save_state

LOG = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
ACTIVE = {"accepted", "scheduled", "queued", "sending", "sent"}
FAILED = {"failed", "undelivered", "canceled"}


def load_dotenv(path: Path) -> None:
    """Load literal KEY=value lines without overriding process environment."""
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
        if not match:
            raise ValueError(f"Invalid .env syntax at line {number}")
        key, value = match.groups()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed .env quote at line {number}")
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True, repr=False)
class TwilioClient:
    account_sid: str
    auth_token: str
    from_number: str
    to_number: str

    @classmethod
    def from_environment(cls) -> "TwilioClient":
        names = ("ACCOUNT_SID", "AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "TO_PHONE_NUMBER")
        values = [os.environ.get(name, "").strip() for name in names]
        missing = [name for name, value in zip(names, values) if not value]
        if missing:
            raise ValueError("Missing SMS settings: " + ", ".join(missing))
        if not re.fullmatch(r"AC[0-9a-fA-F]{32}", values[0]):
            raise ValueError("ACCOUNT_SID must be an AC-prefixed Account SID")
        for name, value in zip(names[2:], values[2:]):
            if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
                raise ValueError(f"{name} must be an international +countrycode phone number")
        return cls(*values)

    def request(self, suffix: str, data: dict[str, str] | None = None) -> dict:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages{suffix}.json"
        auth = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        request = Request(url, data=urlencode(data).encode() if data else None,
                          headers={"Authorization": "Basic " + auth,
                                   "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except HTTPError as error:
            # Never log the response message: it can contain phone numbers.
            try:
                code = json.loads(error.read()).get("code")
            except (ValueError, OSError):
                code = None
            safe_code = str(code) if isinstance(code, int) else "unknown"
            raise SmsError(f"Twilio HTTP {error.code}, code {safe_code}",
                           retryable=error.code == 429,
                           uncertain=error.code >= 500) from None
        except (URLError, OSError, ValueError):
            # A POST timeout can mean Twilio accepted the message. Do not blindly resend.
            raise SmsError("Twilio response unavailable; outcome requires reconciliation",
                           uncertain=True) from None

    def send(self, body: str) -> dict:
        return self.request("", {"From": self.from_number, "To": self.to_number, "Body": body})

    def status(self, sid: str) -> dict:
        if not re.fullmatch(r"SM[0-9a-fA-F]{32}", sid):
            raise ValueError("Invalid saved Twilio message SID")
        return self.request("/" + sid)


class SmsError(Exception):
    def __init__(self, message: str, retryable: bool = False, uncertain: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.uncertain = uncertain


def ascii_text(value: str, limit: int) -> str:
    return " ".join(value.encode("ascii", "replace").decode().split())[:limit]


def digest_body(jobs: list[dict]) -> str:
    """Bound one API message to 900 ASCII characters; full results stay in logs."""
    body = f"bubu-jobs: {len(jobs)} new job match(es)."
    footer = "\nAll matches: https://github.com/kriscCodes/bubu-jobs/actions"
    shown = 0
    for job in jobs:
        entry = (f"\n{ascii_text(job['company'], 45)}: {ascii_text(job['title'], 70)}"
                 f"\n{job['canonical_apply_url'] or job['source_url']}")
        if len(body + entry + footer) > 860:
            break
        body += entry
        shown += 1
    if shown < len(jobs):
        body += f"\n+{len(jobs) - shown} more in run logs."
    return body + footer


def enqueue(state: dict, jobs: list[dict], test: bool = False) -> None:
    outbox = state.setdefault("sms", {})
    if test:
        outbox.setdefault("test-v1", {"body": "bubu-jobs test: SMS alerts are connected. Only newly discovered jobs will trigger alerts.",
                                      "job_ids": [], "status": "pending", "attempts": 0})
    if jobs:
        ids = sorted(job["job_id"] for job in jobs)
        key = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
        outbox.setdefault(key, {"body": digest_body(jobs), "job_ids": ids,
                               "status": "pending", "attempts": 0})


def deliver(state: dict, path: Path, client: TwilioClient) -> None:
    """Refresh receipts, then attempt at most one digest. Retries occur on later runs."""
    outbox = state.get("sms", {})
    errors: list[str] = []
    for key, item in outbox.items():
        status = item["status"]
        if status == "sending":
            item["status"] = "uncertain"
        elif status in ACTIVE:
            try:
                receipt = client.status(item["sid"])
                status = receipt.get("status")
                if status == "delivered":
                    item["status"] = "delivered"
                elif status in FAILED:
                    item["status"] = "pending" if item["attempts"] < MAX_ATTEMPTS else "blocked"
                    item["error"] = f"Twilio delivery {status}; code {receipt.get('error_code')}"
                elif status not in ACTIVE:
                    errors.append(f"SMS {key}: unrecognized delivery status")
                # Keep the local accepted state while the carrier is processing it.
            except SmsError as error:
                errors.append(f"SMS {key}: {error}")
    save_state(path, state)
    for key, item in outbox.items():
        if item["status"] != "pending":
            continue
        item["attempts"] += 1
        item["status"] = "sending"
        save_state(path, state)  # Retain evidence of an interrupted POST.
        try:
            receipt = client.send(item["body"])
            sid = receipt.get("sid", "")
            if not re.fullmatch(r"SM[0-9a-fA-F]{32}", sid):
                raise SmsError("Twilio returned no valid message SID", uncertain=True)
            item["sid"] = sid
            status = receipt.get("status")
            if status == "delivered":
                item["status"] = "delivered"
            elif status in FAILED:
                item["status"] = "pending" if item["attempts"] < MAX_ATTEMPTS else "blocked"
                errors.append(f"SMS {key}: Twilio delivery {status}")
            else:
                item["status"] = "accepted"
            item.pop("error", None)
            LOG.warning("SMS %s: %s (attempt %d)", key, item["status"], item["attempts"])
        except SmsError as error:
            item["status"] = ("uncertain" if error.uncertain else
                              "pending" if error.retryable and item["attempts"] < MAX_ATTEMPTS else "blocked")
            item["error"] = str(error)
            errors.append(f"SMS {key}: {error}")
        save_state(path, state)
        break
    for key, item in outbox.items():
        if item["status"] in {"blocked", "uncertain"}:
            errors.append(f"SMS {key} is {item['status']}; inspect Twilio logs before --retry-sms {key}")
    if errors:
        raise SmsError("; ".join(errors))
