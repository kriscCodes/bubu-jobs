"""FindYourRoleFirst public entry-level JSON source (secondary, fail-soft)."""
import json
import logging

from ..config import FYRF_URL, MAX_LISTING_AGE_DAYS, SOURCE_FYRF
from ..dates import format_posted_date, parse_iso_to_ts
from ..filters import has_us_location, is_relevant
from ..http import FetchResult, conditional_get
from ..models import Job, build_job

LOG = logging.getLogger(__name__)
SECONDS_PER_DAY = 86400


def fetch_entry_level(etag: str | None = None, last_modified: str | None = None) -> FetchResult:
    return conditional_get(
        FYRF_URL,
        etag=etag,
        last_modified=last_modified,
        accept="application/json",
    )


def parse_entry_level(text: str, now: int | None = None) -> list[Job]:
    """Parse tracks.product.jobs[]. Raises ValueError on unexpected shape."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"FindYourRoleFirst response is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("FindYourRoleFirst JSON must be an object")
    tracks = payload.get("tracks")
    if not isinstance(tracks, dict):
        raise ValueError("FindYourRoleFirst JSON is missing tracks")
    product = tracks.get("product")
    if not isinstance(product, dict):
        raise ValueError("FindYourRoleFirst JSON is missing tracks.product")
    raw_jobs = product.get("jobs")
    if not isinstance(raw_jobs, list):
        raise ValueError("FindYourRoleFirst tracks.product.jobs must be a list")
    now_ts = int(now) if now is not None else None
    cutoff = None if now_ts is None else now_ts - MAX_LISTING_AGE_DAYS * SECONDS_PER_DAY
    jobs: list[Job] = []
    for entry in raw_jobs:
        job = _parse_job(entry, cutoff)
        if job is not None:
            jobs.append(job)
    return jobs


def _parse_job(entry, cutoff: int | None) -> Job | None:
    if not isinstance(entry, dict):
        LOG.warning("Skipping FindYourRoleFirst job with unexpected shape")
        return None
    title = str(entry.get("title") or "").strip()
    company = str(entry.get("company") or "").strip()
    url = str(entry.get("url") or "").strip()
    location = str(entry.get("location") or "").strip()
    if not title or not company or not url:
        return None
    if not is_relevant(title):
        return None
    if not has_us_location(location):
        return None
    posted = parse_iso_to_ts(str(entry.get("posted") or ""))
    if posted is None:
        return None
    if cutoff is not None and posted < cutoff:
        return None
    try:
        return build_job(
            company=company,
            title=title,
            location=location,
            date_posted=format_posted_date(posted),
            url=url,
            source=SOURCE_FYRF,
            date_posted_ts=posted,
        )
    except ValueError as error:
        LOG.warning("Skipping FindYourRoleFirst job %s: %s", title, error)
        return None
