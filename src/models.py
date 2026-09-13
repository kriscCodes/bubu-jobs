from dataclasses import dataclass


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
