import html
import logging
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from ..config import RAW_URL, TIMEOUT_SECONDS, MAX_ATTEMPTS
from ..ats import detect_ats
from ..dedupe import job_id, normalize_url
from ..models import Job
from ..resolver import UrlResolver

LOG = logging.getLogger(__name__)
LINK = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\((https?://(?:[^\s()]|\([^()]*\))+)(?:\s+\"[^\"]*\")?\)")
HEADERS = ("company", "job title", "location", "work model", "date posted")


@dataclass(frozen=True)
class FetchResult:
    text: str | None
    etag: str | None


def fetch_readme(etag: str | None = None) -> FetchResult:
    headers = {"User-Agent": "bubu-jobs/1.0", "Accept": "text/plain"}
    if etag:
        headers["If-None-Match"] = etag
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urlopen(Request(RAW_URL, headers=headers), timeout=TIMEOUT_SECONDS) as response:
                return FetchResult(response.read().decode("utf-8"), response.headers.get("ETag"))
        except HTTPError as error:
            if error.code == 304:
                if not etag:
                    raise ValueError("Unexpected 304 without a cached ETag") from error
                return FetchResult(None, etag)
            if error.code not in {429, 500, 502, 503, 504} or attempt == MAX_ATTEMPTS - 1:
                raise
            retry_after = error.headers.get("Retry-After", "")
            delay = min(int(retry_after), 60) if retry_after.isdigit() else 2 ** attempt
        except (URLError, TimeoutError, ConnectionError):
            if attempt == MAX_ATTEMPTS - 1:
                raise
            delay = 2 ** attempt
        LOG.warning("README request failed; retrying in %s seconds", delay)
        time.sleep(delay)
    raise RuntimeError("Unreachable retry state")


def clean(value: str) -> str:
    value = LINK.sub(lambda match: match[1], value)
    value = re.sub(r"<br\s*/?>", ", ", value, flags=re.I)
    value = re.sub(r"<[^>]*>", "", value)
    return " ".join(html.unescape(value.replace("**", "").replace("`", "").replace(r"\|", "|")).split())


def cells(line: str) -> list[str]:
    return re.split(r"(?<!\\)\|", line.strip().strip("|"))


def parse_readme(text: str) -> list[Job]:
    """Parse the known Markdown schema; fail closed on malformed job tables."""
    jobs: list[Job] = []
    indexes: dict[str, int] | None = None
    company = ""
    found_table = False
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip().startswith("|"):
            indexes = None
            company = ""
            continue
        row = cells(line)
        labels = [clean(cell).casefold() for cell in row]
        if all(header in labels for header in HEADERS):
            indexes = {label: i for i, label in enumerate(labels)}
            found_table = True
            company = ""
            continue
        if indexes is None or all(re.fullmatch(r"\s*:?-+:?\s*", cell) for cell in row):
            continue
        try:
            values = {header: clean(row[indexes[header]]) for header in HEADERS}
            name = values["company"]
            if name != "↳":
                company = name
            if not company or not all(values.values()):
                raise ValueError("Missing required cell or orphan company continuation")
            links = LINK.findall(row[indexes["job title"]])
            if not links:
                raise ValueError("Missing job title link")
            source = normalize_url(html.unescape(links[0][1]))
            apply_links = []
            for label in ("apply", "apply link", "application"):
                if label in indexes:
                    apply_links.extend(LINK.findall(row[indexes[label]]))
            candidate = normalize_url(html.unescape(apply_links[0][1])) if apply_links else source
            host = urlsplit(candidate).hostname or ""
            canonical = None if host == "jobright.ai" or host.endswith(".jobright.ai") else candidate
            title, location = values["job title"], values["location"]
            jobs.append(Job(company, title, location, values["work model"], values["date posted"],
                            source, canonical, detect_ats(canonical or source),
                            job_id(company, title, location, canonical or source)))
        except (ValueError, IndexError) as error:
            raise ValueError(f"Malformed job row at line {number}: {error}") from error
    if not found_table:
        raise ValueError("Expected job table not found; upstream schema may have changed")
    return jobs


def resolve_jobs(jobs: list[Job], cache_path: Path | None = None,
                 rate_limit: float = 0.5) -> list[Job]:
    """Resolve Jobright wrapper URLs to direct ATS apply URLs.
    
    Args:
        jobs: List of Job objects to resolve
        cache_path: Path to cache file for resolved URLs
        rate_limit: Delay between API calls in seconds
    
    Returns:
        List of Job objects with resolved canonical_apply_url where possible
    """
    resolver = UrlResolver(cache_path=cache_path)
    resolved_jobs = []
    
    for i, job in enumerate(jobs):
        if job.canonical_apply_url is not None:
            resolved_jobs.append(job)
            continue
        
        if i > 0:
            time.sleep(rate_limit)
        
        result = resolver.resolve(
            company=job.company,
            title=job.title,
            source_url=job.source_url,
            location=job.location,
        )
        
        if result.status == "resolved" and result.url:
            new_job = Job(
                company=job.company,
                title=job.title,
                location=job.location,
                work_model=job.work_model,
                date_posted=job.date_posted,
                source_url=job.source_url,
                canonical_apply_url=result.url,
                ats=result.ats,
                job_id=job_id(job.company, job.title, job.location, result.url),
            )
            resolved_jobs.append(new_job)
            LOG.info("Resolved %s - %s: %s", job.company, job.title, result.url)
        else:
            resolved_jobs.append(job)
            if result.status == "error":
                LOG.warning("Failed to resolve %s - %s: %s", job.company, job.title, result.status)
    
    return resolved_jobs
