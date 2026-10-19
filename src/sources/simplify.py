"""SimplifyJobs New-Grad-Positions JSON source (primary)."""
import json
import logging

from ..config import (
    MAX_LISTING_AGE_DAYS,
    SIMPLIFY_TIMEOUT_SECONDS,
    SIMPLIFY_URL,
    SOURCE_SIMPLIFY,
)
from ..dates import format_posted_date, unix_ts
from ..filters import has_us_location, is_relevant
from ..http import FetchResult, conditional_get
from ..models import Job, build_job

LOG = logging.getLogger(__name__)
SECONDS_PER_DAY = 86400


def fetch_listings(etag: str | None = None, last_modified: str | None = None) -> FetchResult:
    return conditional_get(
        SIMPLIFY_URL,
        etag=etag,
        last_modified=last_modified,
        accept="application/json, text/plain;q=0.9, */*;q=0.8",
        timeout=SIMPLIFY_TIMEOUT_SECONDS,
    )


def parse_listings(text: str, now: int | None = None) -> list[Job]:
    """Parse SimplifyJobs listings.json. Fail closed on schema changes."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"SimplifyJobs listings are not valid JSON: {error}") from error
    if not isinstance(payload, list):
        raise ValueError("SimplifyJobs listings JSON must be a list")
    now_ts = int(now) if now is not None else None
    cutoff = None if now_ts is None else now_ts - MAX_LISTING_AGE_DAYS * SECONDS_PER_DAY
    jobs: list[Job] = []
    for entry in payload:
        job = _parse_entry(entry, cutoff)
        if job is not None:
            jobs.append(job)
    return jobs


def _parse_entry(entry, cutoff: int | None) -> Job | None:
    if not isinstance(entry, dict):
        raise ValueError("SimplifyJobs listing entry must be an object")
    if not entry.get("active") or not entry.get("is_visible"):
        return None
    posted = unix_ts(entry.get("date_posted"))
    if posted is None:
        return None
    if cutoff is not None and posted < cutoff:
        return None
    title = str(entry.get("title") or "").strip()
    company = str(entry.get("company_name") or "").strip()
    url = str(entry.get("url") or "").strip()
    if not title or not company or not url:
        return None
    if not is_relevant(title):
        return None
    locations = entry.get("locations") or []
    if isinstance(locations, str):
        locations = [locations]
    if not isinstance(locations, list) or not has_us_location(locations):
        return None
    location = ", ".join(str(item).strip() for item in locations if str(item).strip())
    try:
        return build_job(
            company=company,
            title=title,
            location=location,
            date_posted=format_posted_date(posted),
            url=url,
            source=SOURCE_SIMPLIFY,
            date_posted_ts=posted,
        )
    except ValueError as error:
        LOG.warning("Skipping SimplifyJobs listing %s: %s", entry.get("id"), error)
        return None
