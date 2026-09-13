import hashlib
import json
import os
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import fcntl


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username:
        raise ValueError("Expected an absolute HTTP(S) job URL")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       parts.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def job_id(company: str, title: str, location: str, url: str) -> str:
    fields = [" ".join(unicodedata.normalize("NFKC", s).casefold().split())
              for s in (company, title, location)]
    fields.append(normalize_url(url))  # URL paths and IDs remain case-sensitive.
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def empty_state() -> dict:
    return {"version": 1, "source": {}, "jobs": {}}


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("version") != 1
            or not isinstance(state.get("source"), dict)
            or not isinstance(state.get("jobs"), dict)
            or any(not isinstance(v, dict) for v in state["jobs"].values())):
        raise ValueError("Invalid seen-jobs state; restore a backup instead of resetting it")
    for key in ("url", "etag", "policy"):
        if key in state["source"] and not isinstance(state["source"][key], (str, type(None))):
            raise ValueError("Invalid source metadata")
    sms = state.get("sms", {})
    statuses = {"pending", "sending", "accepted", "delivered", "blocked", "uncertain"}
    if not isinstance(sms, dict):
        raise ValueError("Invalid SMS outbox")
    for item in sms.values():
        if (not isinstance(item, dict) or item.get("status") not in statuses
                or not isinstance(item.get("body"), str)
                or not isinstance(item.get("job_ids"), list)
                or not isinstance(item.get("attempts"), int)
                or item["attempts"] < 0
                or (item["status"] == "accepted" and not isinstance(item.get("sid"), str))):
            raise ValueError("Invalid SMS outbox item")
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    fd, name = tempfile.mkstemp(prefix=".seen-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def state_lock(path: Path) -> Iterator[None]:
    """Serialize local runs; the Actions workflow separately serializes runners."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
