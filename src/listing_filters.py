"""Screen jobs that are about to be emailed: still-open, then entry-level.

Dropped jobs are left marked seen by the caller (classify_jobs already wrote
them). Fetch failures fail-open: the job is kept and logged as unverifiable.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .config import POSTING_MAX_WORKERS
from .entry_level import DROP, classify_entry_level, build_entry_level_classifier
from .models import Job
from .posting_fetch import CLOSED, UNVERIFIABLE, PostingClient, fetch_posting

LOG = logging.getLogger(__name__)

DROP_CLOSED = "closed"
DROP_NOT_ENTRY = "not-entry-level"
KEEP = "keep"
KEEP_UNVERIFIABLE = "unverifiable"


@dataclass
class ScreenStats:
    checked: int = 0
    dropped_closed: int = 0
    dropped_not_entry_level: int = 0
    unverifiable_kept: int = 0

    def summary_lines(self) -> list[str]:
        return [
            f"JD checked {self.checked}",
            f"Dropped closed {self.dropped_closed}",
            f"Dropped not entry-level {self.dropped_not_entry_level}",
            f"Unverifiable kept {self.unverifiable_kept}",
        ]


@dataclass
class ScreenResult:
    job: Job
    action: str
    reason: str


def apply_url(job: Job) -> str:
    return job.canonical_apply_url or job.source_url or ""


def screen_one(
    job: Job,
    client: PostingClient,
    classifier=None,
) -> ScreenResult:
    url = apply_url(job)
    snapshot = fetch_posting(url, client=client)
    if snapshot.openness == UNVERIFIABLE:
        LOG.info("JD unverifiable, keeping %s %s: %s", job.company, job.title, snapshot.reason)
        return ScreenResult(job, KEEP_UNVERIFIABLE, snapshot.reason)
    if snapshot.openness == CLOSED:
        LOG.info("Dropping closed posting %s %s: %s", job.company, job.title, snapshot.reason)
        return ScreenResult(job, DROP_CLOSED, snapshot.reason)
    decision = classify_entry_level(snapshot, title=job.title, classifier=classifier)
    if decision.verdict == DROP:
        LOG.info("Dropping not-entry-level %s %s: %s", job.company, job.title, decision.reason)
        return ScreenResult(job, DROP_NOT_ENTRY, decision.reason)
    return ScreenResult(job, KEEP, decision.reason)


def screen_candidates(
    jobs: list[Job],
    client: PostingClient | None = None,
    max_workers: int = POSTING_MAX_WORKERS,
    classifier=None,
) -> tuple[list[Job], ScreenStats, list[ScreenResult]]:
    """Return jobs to email, plus counts. Preserves input order among kept jobs."""
    stats = ScreenStats(checked=len(jobs))
    if not jobs:
        return [], stats, []
    client = client or PostingClient()
    classifier = classifier or build_entry_level_classifier()
    workers = max(1, min(max_workers, len(jobs)))
    results: list[ScreenResult | None] = [None] * len(jobs)
    if workers == 1 or len(jobs) == 1:
        for index, job in enumerate(jobs):
            results[index] = screen_one(job, client, classifier)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(screen_one, job, client, classifier): index
                for index, job in enumerate(jobs)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                try:
                    results[index] = future.result()
                except Exception as error:
                    job = jobs[index]
                    LOG.warning("JD check failed open for %s %s: %s", job.company, job.title, error)
                    results[index] = ScreenResult(job, KEEP_UNVERIFIABLE, str(error))
    ordered = [item for item in results if item is not None]
    kept: list[Job] = []
    for item in ordered:
        if item.action == DROP_CLOSED:
            stats.dropped_closed += 1
        elif item.action == DROP_NOT_ENTRY:
            stats.dropped_not_entry_level += 1
        elif item.action == KEEP_UNVERIFIABLE:
            stats.unverifiable_kept += 1
            kept.append(item.job)
        else:
            kept.append(item.job)
    LOG.info(
        "JD screen: checked=%d closed=%d not-entry=%d unverifiable=%d kept=%d",
        stats.checked, stats.dropped_closed, stats.dropped_not_entry_level,
        stats.unverifiable_kept, len(kept),
    )
    return kept, stats, ordered
