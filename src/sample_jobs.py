"""Canned sample jobs for the design-test email.

Live screening uses the same still-open / entry-level filters as the poller.
If a fetch is unverifiable (Cloudflare, timeout), the bundled snapshot is used
so Google (3 years + Mid) and Natera (closed) stay dropped.
"""
from __future__ import annotations

from .config import SOURCE_FYRF, SOURCE_JOBRIGHT, SOURCE_SIMPLIFY
from .entry_level import CONFIRMED, DROP
from .listing_filters import (
    BUCKET_ENTRY,
    BUCKET_NOT_STATED,
    BUCKET_TOO_SENIOR,
    DROP_CLOSED,
    DROP_NOT_ENTRY,
    KEEP,
    KEEP_UNVERIFIABLE,
    ScreenResult,
    apply_url,
    screen_candidates,
)
from .models import Job, build_job
from .posting_fetch import CLOSED, OPEN, PostingClient, PostingSnapshot

FIGMA_URL = "https://boards.greenhouse.io/figma/jobs/6180116004"
LSEG_URL = (
    "https://lseg.wd3.myworkdayjobs.com/en-US/Careers/job/New-York-City-United-States/"
    "Senior-Associate-Product-Manager--Enterprise-AI_R0124288"
)
MICROSOFT_URL = "https://apply.careers.microsoft.com/careers/job/1970393557027388"
GOOGLE_URL = "https://www.google.com/about/careers/applications/jobs/results/98591892920246982"
NATERA_URL = "https://job-boards.greenhouse.io/natera/jobs/6217258004"
CAPITAL_ONE_URL = "https://jobright.ai/jobs/info/6ac7ebb1a444ac5d36f869fe"

FIGMA_FALLBACK = PostingSnapshot(
    url=FIGMA_URL,
    openness=OPEN,
    ats="Greenhouse",
    source="fixture",
    reason="bundled figma snapshot",
    text=(
        "Early Career, Associate Product Manager (2027)\n"
        "We're looking for user-driven and deeply technical Associate Product Managers "
        "to join our rotation program.\n"
        "We'd love to hear from you if you have:\n"
        "Comfortability working on deep, technically complex problems\n"
    ),
)
LSEG_FALLBACK = PostingSnapshot(
    url=LSEG_URL,
    openness=OPEN,
    ats="Workday",
    source="fixture",
    reason="bundled lseg snapshot",
    text=(
        "Senior Associate Product Manager, Enterprise AI\n"
        "This is a great opportunity for an early-career product manager to develop their craft.\n"
        "WHAT YOU'LL BRING:\n"
        "Bachelor's degree in Finance, Computer Science, Engineering, Information Systems "
        "or equivalent experience.\n"
        "Early career experience in Product Management, Business Analysis, Engineering or "
        "a related field (internships and graduate schemes considered).\n"
        "Preferred:\n"
        "Exposure to financial data, analytics systems or enterprise-scale data workflows.\n"
        "Career Stage:\nSenior Associate\n"
    ),
)
MICROSOFT_FALLBACK = PostingSnapshot(
    url=MICROSOFT_URL,
    openness=OPEN,
    ats="Unknown",
    source="fixture",
    reason="bundled microsoft snapshot",
    text=(
        "Product Manager, CoreAI\n"
        "Career level: IC2\n"
        "Bachelor's Degree or equivalent experience. Bachelor's Degree and 2+ years "
        "experience in product/service/program management or software development or "
        "equivalent experience. 1+ year(s) experience improving product metrics for a "
        "product, feature, or experience in a market."
    ),
    seniority_tags=("IC2",),
)
GOOGLE_FALLBACK = PostingSnapshot(
    url=GOOGLE_URL,
    openness=OPEN,
    ats="Unknown",
    source="fixture",
    reason="bundled google snapshot",
    text=(
        "Product Manager I, Ads Sellside Apps\n"
        "Minimum qualifications:\n"
        "Bachelor's degree or equivalent practical experience.\n"
        "3 years of experience in product management or related technical role.\n"
        "1 year of experience taking technical products from conception to launch.\n"
        "Preferred qualifications:\n"
        "2 years of experience working cross-functionally with engineering, UX/UI, "
        "sales finance, and other stakeholders.\n"
    ),
    seniority_tags=("Mid",),
)
NATERA_FALLBACK = PostingSnapshot(
    url=NATERA_URL,
    openness=CLOSED,
    ats="Greenhouse",
    source="fixture",
    reason="Job not found",
    status_code=404,
)

FALLBACKS = {
    FIGMA_URL: FIGMA_FALLBACK,
    LSEG_URL: LSEG_FALLBACK,
    MICROSOFT_URL: MICROSOFT_FALLBACK,
    GOOGLE_URL: GOOGLE_FALLBACK,
    NATERA_URL: NATERA_FALLBACK,
}


def sample_job_list() -> list[Job]:
    return [
        build_job(
            company="Google",
            title="Product Manager I, Ads Sellside Apps",
            location="Mountain View, CA, USA",
            date_posted="Oct 16",
            url=GOOGLE_URL,
            source=SOURCE_FYRF,
        ),
        build_job(
            company="Microsoft",
            title="Product Manager",
            location="Remote in USA",
            date_posted="Oct 15",
            url=MICROSOFT_URL,
            source=SOURCE_SIMPLIFY,
        ),
        build_job(
            company="LSEG",
            title="Senior Associate Product Manager - Enterprise AI",
            location="NYC",
            date_posted="Oct 13",
            url=LSEG_URL,
            source=SOURCE_SIMPLIFY,
        ),
        build_job(
            company="Natera",
            title="(Associate) Product Manager, Organ Health",
            location="Austin, TX",
            date_posted="Oct 13",
            url=NATERA_URL,
            source=SOURCE_FYRF,
        ),
        build_job(
            company="Figma",
            title="Associate Product Manager",
            location="SF",
            date_posted="Oct 7",
            url=FIGMA_URL,
            source=SOURCE_SIMPLIFY,
        ),
        build_job(
            company="Capital One",
            title="Senior Associate, Product Manager - Business Cards & Payments",
            location="New York, NY, United States",
            date_posted="Oct 20",
            url=CAPITAL_ONE_URL,
            source=SOURCE_JOBRIGHT,
            canonical=False,
        ),
    ]


def decide_from_snapshot(job: Job, snapshot: PostingSnapshot) -> ScreenResult:
    from .entry_level import classify_entry_level
    from .posting_fetch import CLOSED, UNVERIFIABLE

    if snapshot.openness == UNVERIFIABLE:
        return ScreenResult(job, KEEP_UNVERIFIABLE, snapshot.reason, BUCKET_NOT_STATED)
    if snapshot.openness == CLOSED:
        return ScreenResult(job, DROP_CLOSED, snapshot.reason, "")
    decision = classify_entry_level(snapshot, title=job.title)
    if decision.verdict == DROP:
        return ScreenResult(job, DROP_NOT_ENTRY, decision.reason, BUCKET_TOO_SENIOR)
    if decision.verdict == CONFIRMED:
        return ScreenResult(job, KEEP, decision.reason, BUCKET_ENTRY)
    return ScreenResult(job, KEEP, decision.reason, BUCKET_NOT_STATED)


def screen_sample_jobs(
    jobs: list[Job] | None = None,
    client: PostingClient | None = None,
    use_fallback: bool = True,
) -> tuple[list[Job], list[ScreenResult]]:
    jobs = jobs if jobs is not None else sample_job_list()
    client = client or PostingClient()
    _kept, _stats, results = screen_candidates(jobs, client=client)
    resolved: list[ScreenResult] = []
    kept: list[Job] = []
    for result in results:
        if result.action == KEEP_UNVERIFIABLE and use_fallback:
            fallback = FALLBACKS.get(apply_url(result.job))
            if fallback is not None:
                result = decide_from_snapshot(result.job, fallback)
        resolved.append(result)
        if result.action in {KEEP, KEEP_UNVERIFIABLE}:
            kept.append(result.job)
    return kept, resolved
