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


TRACKING_PARAMS = frozenset({"fbclid", "gclid", "ref"})


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username:
        raise ValueError("Expected an absolute HTTP(S) job URL")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       path, urlencode(sorted(query)), ""))


def normalize_apply_url(url: str) -> str:
    """Cross-source apply URL key: lowercase host, drop utm_*/ref, strip trailing /apply."""
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    path = parts.path
    if path.lower().endswith("/apply"):
        path = path[:-6].rstrip("/") or "/"
    host = (parts.hostname or "").lower()
    netloc = host if not parts.port else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, path, parts.query, ""))


def company_title_key(company: str, title: str) -> str:
    return "\0".join((_normalized_text(company), _normalized_text(title)))


def apply_url_key(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return normalize_apply_url(url)
    except ValueError:
        return None


def job_id(company: str, title: str, location: str, url: str) -> str:
    fields = [_normalized_text(s) for s in (company, title, location)]
    fields.append(normalize_url(url))  # URL paths and IDs remain case-sensitive.
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def empty_state() -> dict:
    return {"version": 1, "source": {}, "sources": {}, "jobs": {}}


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
    if "sms_paused" in state and not isinstance(state["sms_paused"], str):
        raise ValueError("Invalid SMS pause metadata")
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
    if "sources" in state:
        if not isinstance(state["sources"], dict) or any(
                not isinstance(meta, dict) for meta in state["sources"].values()):
            raise ValueError("Invalid per-source metadata")
    if "email_migrated" in state and not isinstance(state["email_migrated"], bool):
        raise ValueError("Invalid email migration flag")
    outbox = state.get("email", {})
    if not isinstance(outbox, dict):
        raise ValueError("Invalid email outbox")
    for item in outbox.values():
        if (not isinstance(item, dict)
                or item.get("status") not in {"pending", "sending", "submitted", "blocked", "uncertain"}
                or not all(isinstance(item.get(field), str) for field in ("subject", "text", "html"))
                or not isinstance(item.get("job_ids"), list)
                or not isinstance(item.get("attempts"), int) or item["attempts"] < 0):
            raise ValueError("Invalid email outbox item")
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


def build_seen_index(jobs: dict) -> dict[str, set[str]]:
    """Index stored jobs by id, normalized apply URL, and company+title."""
    index: dict[str, set[str]] = {"ids": set(jobs), "urls": set(), "titles": set()}
    for job in jobs.values():
        remember_stored_job(job, index)
    return index


def remember_stored_job(job: dict, index: dict[str, set[str]]) -> None:
    job_id_value = job.get("job_id")
    if isinstance(job_id_value, str):
        index["ids"].add(job_id_value)
    for field in ("canonical_apply_url", "source_url"):
        key = apply_url_key(job.get(field))
        if key:
            index["urls"].add(key)
    index["titles"].add(company_title_key(job.get("company", ""), job.get("title", "")))


def remember_job(job, index: dict[str, set[str]]) -> None:
    index["ids"].add(job.job_id)
    url_key = apply_url_key(job.canonical_apply_url) or apply_url_key(job.source_url)
    if url_key:
        index["urls"].add(url_key)
    index["titles"].add(company_title_key(job.company, job.title))


def is_seen_job(job, index: dict[str, set[str]]) -> bool:
    if job.job_id in index["ids"]:
        return True
    url_key = apply_url_key(job.canonical_apply_url) or apply_url_key(job.source_url)
    if url_key and url_key in index["urls"]:
        return True
    return company_title_key(job.company, job.title) in index["titles"]


def dedupe_jobs(jobs: list) -> list:
    """Keep the first job for each normalized apply URL, else company+title."""
    index: dict[str, set[str]] = {"ids": set(), "urls": set(), "titles": set()}
    unique = []
    for job in jobs:
        if is_seen_job(job, index):
            continue
        remember_job(job, index)
        unique.append(job)
    return unique
