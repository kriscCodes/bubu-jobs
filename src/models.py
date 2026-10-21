from dataclasses import dataclass

from .ats import detect_ats
from .dedupe import job_id, normalize_apply_url


@dataclass(frozen=True)
class Job:
    company: str
    title: str
    location: str
    work_model: str
    date_posted: str
    source_url: str
    canonical_apply_url: str | None
    ats: str
    job_id: str
    source: str = "jobright"
    date_posted_ts: int | None = None


def build_job(
    *,
    company: str,
    title: str,
    location: str,
    date_posted: str,
    url: str,
    source: str,
    work_model: str = "",
    date_posted_ts: int | None = None,
    canonical: bool = True,
) -> Job:
    """Build a Job from source fields. `canonical` is True for direct ATS URLs."""
    apply_url = normalize_apply_url(url)
    canonical_apply_url = apply_url if canonical else None
    identity_url = canonical_apply_url or apply_url
    return Job(
        company=company,
        title=title,
        location=location,
        work_model=work_model,
        date_posted=date_posted,
        source_url=apply_url,
        canonical_apply_url=canonical_apply_url,
        ats=detect_ats(identity_url),
        job_id=job_id(company, title, location, identity_url),
        source=source,
        date_posted_ts=date_posted_ts,
    )
