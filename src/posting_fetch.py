"""Fetch a job's direct posting and decide whether it is still open.

Prefers ATS JSON APIs (Greenhouse boards-api, Lever postings, Ashby, Workday
cxs) over HTML. Fail-open: timeouts, Cloudflare, Jobright wrappers, and other
fetch failures are unverifiable rather than closed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from .ats import detect_ats
from .config import POSTING_TIMEOUT_SECONDS

LOG = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; bubu-jobs/1.0; +https://github.com/kriscCodes/bubu-jobs)"
)
CLOSED_PHRASES = (
    "no longer accepting applications",
    "job not found",
    "this job is closed",
    "this job posting is no longer available",
    "this position has been filled",
    "position is no longer available",
    "this requisition is closed",
    "this job is no longer available",
    "the job you are looking for is no longer available",
)
JOBRIGHT_HOSTS = ("jobright.ai",)
WORKDAY_HOST = re.compile(r"(?i)^([\w-]+)\.wd\d+\.myworkdayjobs\.com$")
GREENHOUSE_JOB = re.compile(
    r"(?i)(?:job-boards|boards)\.greenhouse\.io/([^/]+)/jobs/(\d+)"
)
LEVER_JOB = re.compile(r"(?i)(?:jobs\.)?lever\.co/([^/]+)/([a-f0-9-]{36})")
ASHBY_JOB = re.compile(r"(?i)(?:jobs\.)?ashbyhq\.com/([^/]+)/([a-f0-9-]{36})")
UUID_RE = re.compile(r"(?i)[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
DIGITS_RE = re.compile(r"\d{5,}")

OPEN = "open"
CLOSED = "closed"
UNVERIFIABLE = "unverifiable"


@dataclass
class PostingSnapshot:
    url: str
    openness: str
    final_url: str = ""
    status_code: int | None = None
    ats: str = "Unknown"
    text: str = ""
    json_data: dict[str, Any] | None = None
    seniority_tags: tuple[str, ...] = ()
    source: str = ""
    reason: str = ""
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class RawResponse:
    status: int | None
    url: str
    final_url: str
    text: str
    headers: dict[str, str]
    error: str | None = None
    blocked: bool = False

    def json(self) -> Any | None:
        if not self.text:
            return None
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            return None


class PostingClient:
    """HTTP helper with a per-run URL cache."""

    def __init__(self, timeout: int = POSTING_TIMEOUT_SECONDS, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self._cache: dict[tuple[str, str, bool], RawResponse] = {}

    def request(self, method: str, url: str, *, allow_redirects: bool = True,
                headers: dict[str, str] | None = None, json_body: Any = None) -> RawResponse:
        key = (method.upper(), url, allow_redirects)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        request_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        }
        if headers:
            request_headers.update(headers)
        try:
            response = self.session.request(
                method, url, timeout=self.timeout, allow_redirects=allow_redirects,
                headers=request_headers, json=json_body,
            )
            raw = RawResponse(
                status=response.status_code,
                url=url,
                final_url=str(response.url),
                text=response.text or "",
                headers={k.lower(): v for k, v in response.headers.items()},
            )
            raw.blocked = _looks_blocked(raw)
        except requests.Timeout as error:
            raw = RawResponse(None, url, url, "", {}, error=f"timeout: {error}")
        except requests.RequestException as error:
            raw = RawResponse(None, url, url, "", {}, error=f"{type(error).__name__}: {error}")
        self._cache[key] = raw
        return raw


def _looks_blocked(raw: RawResponse) -> bool:
    server = (raw.headers.get("server") or "").lower()
    text_l = raw.text[:4000].lower()
    if raw.headers.get("cf-mitigated") or raw.headers.get("cf-ray") and raw.status in {403, 503}:
        return True
    if "cloudflare" in server and raw.status in {403, 503, 429}:
        return True
    if "just a moment" in text_l or "cf-browser-verification" in text_l:
        return True
    if "attention required" in text_l and "cloudflare" in text_l:
        return True
    return False


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _is_jobright(url: str) -> bool:
    host = _host(url)
    return any(host == domain or host.endswith("." + domain) for domain in JOBRIGHT_HOSTS)


def _job_tokens(url: str) -> set[str]:
    parts = urlsplit(url)
    tokens = set(DIGITS_RE.findall(parts.path))
    tokens.update(UUID_RE.findall(parts.path))
    query = parse_qs(parts.query)
    for key in ("gh_jid", "jobId", "job_id", "pid", "requisitionId"):
        tokens.update(query.get(key, []))
    return {token.lower() for token in tokens if token}


def _redirected_to_board(original: str, final: str) -> bool:
    """True when a posting URL lost its job identity and landed on a board/list page."""
    if not final or final.rstrip("/") == original.rstrip("/"):
        return False
    orig_parts, final_parts = urlsplit(original), urlsplit(final)
    orig_path = orig_parts.path.rstrip("/") or "/"
    final_path = final_parts.path.rstrip("/") or "/"
    orig_tokens = _job_tokens(original)
    final_tokens = _job_tokens(final)
    if orig_tokens and not (orig_tokens & final_tokens):
        query = parse_qs(final_parts.query)
        if query.get("error") or final_path.count("/") < orig_path.count("/"):
            return True
        if orig_path != final_path and orig_path.startswith(final_path.rstrip("/") + "/"):
            return True
        # Job id gone from path/query, e.g. /natera/jobs/123 -> /natera
        if orig_path != final_path:
            return True
    return False


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _closed_phrase(text: str) -> str | None:
    low = text.casefold()
    for phrase in CLOSED_PHRASES:
        if phrase in low:
            return phrase
    return None


def _greenhouse_ids(url: str) -> tuple[str, str] | None:
    match = GREENHOUSE_JOB.search(url)
    if match:
        return match.group(1), match.group(2)
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    job_id = (query.get("gh_jid") or [None])[0]
    if not job_id:
        path_match = re.search(r"/jobs?/(\d+)", parts.path)
        job_id = path_match.group(1) if path_match else None
    if not job_id:
        return None
    host = parts.hostname or ""
    token = None
    if "greenhouse.io" in host:
        token_match = re.search(r"greenhouse\.io/([^/]+)", url)
        token = token_match.group(1) if token_match else None
    return (token, job_id) if token and job_id else None


def _seniority_from_google_html(html: str) -> tuple[str, ...]:
    tags = []
    match = re.search(
        r'aria-label="(Mid|Senior|Internship|Entry.?level|Early)[^"]*experience filters',
        html, re.I,
    )
    if match:
        tags.append(match.group(1).casefold())
    # Scan visible copy only so font URLs like ".../ic2.woff2" are not tags.
    visible = _html_to_text(html)
    for ic in re.finditer(r"(?i)(?<![a-z0-9])IC\s*([1-8])(?![0-9])", visible):
        tags.append(f"IC{ic.group(1)}")
    return tuple(tags)


def _seniority_from_json(data: dict[str, Any] | None) -> tuple[str, ...]:
    if not data:
        return ()
    tags: list[str] = []
    keys = (
        "seniority", "jobLevel", "job_level", "experienceLevel", "experience_level",
        "careerStage", "career_stage", "level", "occupationalCategory",
    )
    stack: list[Any] = [data]
    seen = 0
    while stack and seen < 50:
        item = stack.pop()
        seen += 1
        if isinstance(item, dict):
            for key, value in item.items():
                if key in keys and isinstance(value, str) and value.strip():
                    tags.append(value.strip())
                elif isinstance(value, (dict, list)) and seen < 40:
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item[:10])
    return tuple(tags)


def _snapshot(*, url: str, openness: str, ats: str, source: str, reason: str,
              raw: RawResponse | None = None, text: str = "",
              json_data: dict[str, Any] | None = None,
              seniority_tags: tuple[str, ...] = (),
              error: str | None = None) -> PostingSnapshot:
    return PostingSnapshot(
        url=url,
        openness=openness,
        final_url=(raw.final_url if raw else url) or url,
        status_code=raw.status if raw else None,
        ats=ats,
        text=text,
        json_data=json_data,
        seniority_tags=seniority_tags,
        source=source,
        reason=reason,
        error=error or (raw.error if raw else None),
        headers=raw.headers if raw else {},
    )


def _unverifiable(url: str, ats: str, source: str, reason: str,
                  raw: RawResponse | None = None) -> PostingSnapshot:
    return _snapshot(
        url=url, openness=UNVERIFIABLE, ats=ats, source=source, reason=reason, raw=raw,
        error=raw.error if raw else reason,
    )


def _closed(url: str, ats: str, source: str, reason: str,
            raw: RawResponse | None = None, text: str = "",
            json_data: dict[str, Any] | None = None) -> PostingSnapshot:
    return _snapshot(
        url=url, openness=CLOSED, ats=ats, source=source, reason=reason, raw=raw,
        text=text, json_data=json_data,
    )


def _from_html(url: str, ats: str, client: PostingClient) -> PostingSnapshot:
    raw = client.request("GET", url)
    if raw.error:
        return _unverifiable(url, ats, "html", raw.error, raw)
    if raw.blocked:
        return _unverifiable(url, ats, "html", "cloudflare or bot wall", raw)
    if raw.status in {404, 410}:
        return _closed(url, ats, "html", f"HTTP {raw.status}", raw, text=raw.text)
    if raw.status is None or raw.status >= 500:
        return _unverifiable(url, ats, "html", f"HTTP {raw.status}", raw)
    if raw.status in {401, 403}:
        return _unverifiable(url, ats, "html", f"HTTP {raw.status}", raw)
    if _redirected_to_board(url, raw.final_url):
        return _closed(url, ats, "html", f"redirected to board page {raw.final_url}", raw, text=raw.text)
    phrase = _closed_phrase(raw.text)
    if phrase:
        return _closed(url, ats, "html", f"page text: {phrase}", raw, text=_html_to_text(raw.text))
    json_data = None
    ld_match = re.search(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw.text, re.I | re.S,
    )
    if ld_match:
        try:
            parsed = json.loads(ld_match.group(1))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            json_data = parsed
    seniority = _seniority_from_google_html(raw.text) + _seniority_from_json(
        json_data if isinstance(json_data, dict) else None
    )
    if isinstance(json_data, dict) and json_data.get("description"):
        # Prefer the JobPosting description over the full page (nav, privacy, cookies).
        title = str(json_data.get("title") or "")
        text = (title + "\n" if title else "") + str(json_data["description"])
    else:
        text = _html_to_text(raw.text)
    return _snapshot(
        url=url, openness=OPEN, ats=ats, source="html", reason="fetched html",
        raw=raw, text=text, json_data=json_data if isinstance(json_data, dict) else None,
        seniority_tags=seniority,
    )


def _fetch_greenhouse(url: str, client: PostingClient, ats: str) -> PostingSnapshot:
    ids = _greenhouse_ids(url)
    if not ids:
        return _from_html(url, ats, client)
    token, job_id = ids
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"
    raw = client.request("GET", api_url, headers={"Accept": "application/json"})
    if raw.error or raw.blocked:
        return _unverifiable(url, ats, "greenhouse-api", raw.error or "blocked", raw)
    if raw.status in {404, 410}:
        payload = raw.json() if raw.text else None
        reason = "greenhouse job not found"
        if isinstance(payload, dict) and payload.get("error"):
            reason = str(payload.get("error"))
        return _closed(url, ats, "greenhouse-api", reason, raw, json_data=payload if isinstance(payload, dict) else None)
    if raw.status != 200:
        return _unverifiable(url, ats, "greenhouse-api", f"HTTP {raw.status}", raw)
    data = raw.json()
    if not isinstance(data, dict):
        return _unverifiable(url, ats, "greenhouse-api", "invalid json", raw)
    content = data.get("content") or ""
    text = _html_to_text(str(content))
    title = str(data.get("title") or "")
    if title:
        text = title + "\n" + text
    return _snapshot(
        url=url, openness=OPEN, ats=ats, source="greenhouse-api", reason="greenhouse job found",
        raw=raw, text=text, json_data=data, seniority_tags=_seniority_from_json(data),
    )


def _fetch_lever(url: str, client: PostingClient, ats: str) -> PostingSnapshot:
    match = LEVER_JOB.search(url)
    if not match:
        return _from_html(url, ats, client)
    company, posting_id = match.groups()
    api_url = f"https://api.lever.co/v0/postings/{company}/{posting_id}"
    raw = client.request("GET", api_url, headers={"Accept": "application/json"})
    if raw.error or raw.blocked:
        return _unverifiable(url, ats, "lever-api", raw.error or "blocked", raw)
    if raw.status in {404, 410}:
        return _closed(url, ats, "lever-api", "lever posting not found", raw)
    if raw.status != 200:
        return _unverifiable(url, ats, "lever-api", f"HTTP {raw.status}", raw)
    data = raw.json()
    if not isinstance(data, dict):
        return _unverifiable(url, ats, "lever-api", "invalid json", raw)
    text = data.get("descriptionPlain") or _html_to_text(str(data.get("description") or ""))
    lists = data.get("lists") or []
    extra = []
    if isinstance(lists, list):
        for item in lists:
            if isinstance(item, dict):
                extra.append(str(item.get("text") or item.get("content") or ""))
    if extra:
        text = text + "\n" + "\n".join(extra)
    categories = data.get("categories") if isinstance(data.get("categories"), dict) else {}
    tags = _seniority_from_json(data)
    level = categories.get("commitment") or categories.get("level") if categories else None
    if isinstance(level, str):
        tags = tags + (level,)
    return _snapshot(
        url=url, openness=OPEN, ats=ats, source="lever-api", reason="lever posting found",
        raw=raw, text=text, json_data=data, seniority_tags=tags,
    )


def _fetch_ashby(url: str, client: PostingClient, ats: str) -> PostingSnapshot:
    match = ASHBY_JOB.search(url)
    if not match:
        return _from_html(url, ats, client)
    org, job_id = match.groups()
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{org}"
    raw = client.request("GET", api_url, headers={"Accept": "application/json"})
    if not raw.error and not raw.blocked and raw.status == 200:
        data = raw.json()
        jobs = []
        if isinstance(data, dict):
            jobs = data.get("jobs") or data.get("jobPostings") or []
        if isinstance(jobs, list):
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                ident = str(job.get("id") or job.get("jobId") or job.get("jobPostingId") or "")
                if ident.lower() != job_id.lower():
                    continue
                text = _html_to_text(str(job.get("descriptionHtml") or job.get("descriptionPlain") or job.get("description") or ""))
                title = str(job.get("title") or "")
                if title:
                    text = title + "\n" + text
                return _snapshot(
                    url=url, openness=OPEN, ats=ats, source="ashby-api", reason="ashby job found",
                    raw=raw, text=text, json_data=job, seniority_tags=_seniority_from_json(job),
                )
            return _closed(url, ats, "ashby-api", "ashby job not on board", raw)
    if raw.error or raw.blocked:
        return _unverifiable(url, ats, "ashby-api", raw.error or "blocked", raw)
    return _from_html(url, ats, client)


def _workday_cxs_url(url: str) -> str | None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    match = WORKDAY_HOST.match(host)
    if not match:
        return None
    tenant = match.group(1)
    segs = [seg for seg in parts.path.split("/") if seg]
    if "job" not in segs:
        return None
    job_idx = segs.index("job")
    if job_idx == 0:
        return None
    site = segs[job_idx - 1]
    rest = "/".join(segs[job_idx + 1:])
    if not rest:
        return None
    return f"https://{host}/wday/cxs/{tenant}/{site}/job/{rest}"


def _fetch_workday(url: str, client: PostingClient, ats: str) -> PostingSnapshot:
    cxs = _workday_cxs_url(url)
    if not cxs:
        return _from_html(url, ats, client)
    raw = client.request("GET", cxs, headers={"Accept": "application/json"})
    if raw.error or raw.blocked:
        return _unverifiable(url, ats, "workday-cxs", raw.error or "blocked", raw)
    if raw.status in {404, 410}:
        return _closed(url, ats, "workday-cxs", "workday job not found", raw)
    if raw.status != 200:
        return _unverifiable(url, ats, "workday-cxs", f"HTTP {raw.status}", raw)
    data = raw.json()
    if not isinstance(data, dict) or not data.get("jobPostingInfo"):
        return _closed(url, ats, "workday-cxs", "workday jobPostingInfo missing", raw, json_data=data if isinstance(data, dict) else None)
    info = data["jobPostingInfo"]
    if not isinstance(info, dict):
        return _closed(url, ats, "workday-cxs", "workday jobPostingInfo missing", raw, json_data=data)
    if info.get("canApply") is False:
        return _closed(url, ats, "workday-cxs", "workday canApply=false", raw, json_data=data)
    desc = info.get("jobDescription") or ""
    text = _html_to_text(str(desc))
    title = str(info.get("title") or "")
    if title:
        text = title + "\n" + text
    return _snapshot(
        url=url, openness=OPEN, ats=ats, source="workday-cxs", reason="workday job found",
        raw=raw, text=text, json_data=data, seniority_tags=_seniority_from_json(info),
    )


def fetch_posting(url: str, client: PostingClient | None = None) -> PostingSnapshot:
    """Fetch a posting. Never raises; unverifiable on transport/parser failure."""
    client = client or PostingClient()
    if not url:
        return _unverifiable("", "Unknown", "none", "missing url")
    if _is_jobright(url):
        return _unverifiable(url, "Unknown", "jobright", "jobright wrapper")
    ats = detect_ats(url)
    try:
        if ats == "Greenhouse":
            return _fetch_greenhouse(url, client, ats)
        if ats == "Lever":
            return _fetch_lever(url, client, ats)
        if ats == "Ashby":
            return _fetch_ashby(url, client, ats)
        if ats == "Workday":
            return _fetch_workday(url, client, ats)
        return _from_html(url, ats, client)
    except Exception as error:
        LOG.warning("Posting fetch failed for %s: %s", url, error)
        return _unverifiable(url, ats, "exception", str(error))
