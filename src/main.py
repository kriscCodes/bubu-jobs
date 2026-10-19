import argparse
import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from . import config
from .config import (
    FIRST_RUN_SEED_DAYS,
    NEW_SOURCES,
    RAW_URL,
    SIMPLIFY_URL,
    SOURCE_FYRF,
    SOURCE_JOBRIGHT,
    SOURCE_LABELS,
    SOURCE_SIMPLIFY,
)
from .dedupe import (
    build_seen_index,
    dedupe_jobs,
    is_seen_job,
    load_state,
    remember_job,
    save_state,
    state_lock,
)
from .filters import is_relevant
from .http import FetchResult
from .models import Job
from .notifications import TwilioClient, SmsError, load_dotenv, enqueue, deliver
from .sources.findyourrolefirst import fetch_entry_level, parse_entry_level
from .sources.jobright import fetch_readme, parse_readme, resolve_jobs
from .sources.simplify import fetch_listings, parse_listings

from .email_notifications import (GmailClient, EmailError, enqueue_email,
                                  deliver_email, migrate_unsent_sms, send_test_email_to)

LOG = logging.getLogger(__name__)
SECONDS_PER_DAY = 86400


def policy_fingerprint(resolve_urls: bool = False) -> str:
    # Bump parser version when normalization/parsing semantics change.
    # Bump resolver version when URL resolution logic changes.
    value = ["parser-v2", "sources-v1", "resolver-v1" if resolve_urls else None,
             config.ACCEPTED_TITLE_KEYWORDS, config.REJECTED_TITLE_KEYWORDS]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def _source_slot(state: dict, name: str) -> dict:
    return state.setdefault("sources", {}).setdefault(name, {})


def _cache_validators(state: dict, name: str, policy: str, force: bool) -> tuple[str | None, str | None]:
    if force:
        return None, None
    slot = state.get("sources", {}).get(name) or {}
    cached_policy = slot.get("policy")
    etag = slot.get("etag")
    last_modified = slot.get("last_modified")
    if name == SOURCE_JOBRIGHT:
        legacy = state.get("source") or {}
        cached_policy = cached_policy or legacy.get("policy")
        etag = etag or legacy.get("etag")
    if cached_policy != policy:
        return None, None
    return etag, last_modified


def _record_source_meta(state: dict, name: str, url: str, result: FetchResult, policy: str) -> None:
    slot = _source_slot(state, name)
    slot["url"] = url
    slot["policy"] = policy
    if result.etag:
        slot["etag"] = result.etag
    if result.last_modified:
        slot["last_modified"] = result.last_modified
    if name == SOURCE_JOBRIGHT:
        state["source"] = {"url": url, "etag": result.etag, "policy": policy}


def unseeded_sources(state: dict) -> set[str]:
    seeded = {
        name for name, meta in state.get("sources", {}).items()
        if isinstance(meta, dict) and meta.get("seeded")
    }
    return {name for name in NEW_SOURCES if name not in seeded}


def _is_stale_for_first_run(job: Job, now_ts: int) -> bool:
    if job.source not in NEW_SOURCES:
        return False
    if job.date_posted_ts is None:
        return True
    return (now_ts - job.date_posted_ts) > FIRST_RUN_SEED_DAYS * SECONDS_PER_DAY


def collect_jobs(state: dict, force: bool, policy: str, now_ts: int
                 ) -> tuple[list[Job], bool, set[str]]:
    """Fetch and parse all sources. Primary, then secondary (fail-soft), then Jobright.

    Returns (jobs, any_downloaded, downloaded_new_sources). A source is recorded
    as downloaded only when a fresh body was parsed so first-run seeding can
    be marked after classify_jobs uses the pre-fetch unseeded snapshot.
    """
    jobs: list[Job] = []
    downloaded = False
    downloaded_new_sources: set[str] = set()

    simplify_etag, simplify_modified = _cache_validators(state, SOURCE_SIMPLIFY, policy, force)
    simplify = fetch_listings(simplify_etag, simplify_modified)
    if simplify.text is None:
        LOG.info("SimplifyJobs listings unchanged")
        _record_source_meta(state, SOURCE_SIMPLIFY, SIMPLIFY_URL, simplify, policy)
    else:
        jobs.extend(parse_listings(simplify.text, now=now_ts))
        downloaded = True
        downloaded_new_sources.add(SOURCE_SIMPLIFY)
        _record_source_meta(state, SOURCE_SIMPLIFY, SIMPLIFY_URL, simplify, policy)

    fyrf_etag, fyrf_modified = _cache_validators(state, SOURCE_FYRF, policy, force)
    try:
        fyrf = fetch_entry_level(fyrf_etag, fyrf_modified)
        if fyrf.text is None:
            LOG.info("FindYourRoleFirst listings unchanged")
            _record_source_meta(state, SOURCE_FYRF, config.FYRF_URL, fyrf, policy)
        else:
            jobs.extend(parse_entry_level(fyrf.text, now=now_ts))
            downloaded = True
            downloaded_new_sources.add(SOURCE_FYRF)
            _record_source_meta(state, SOURCE_FYRF, config.FYRF_URL, fyrf, policy)
    except Exception as error:
        LOG.warning("FindYourRoleFirst source failed; continuing without it: %s", error)

    jobright_etag, jobright_modified = _cache_validators(state, SOURCE_JOBRIGHT, policy, force)
    jobright = fetch_readme(jobright_etag, jobright_modified)
    if jobright.text is None:
        LOG.info("Jobright README unchanged")
        _record_source_meta(state, SOURCE_JOBRIGHT, RAW_URL, jobright, policy)
    else:
        jobs.extend(parse_readme(jobright.text))
        downloaded = True
        _record_source_meta(state, SOURCE_JOBRIGHT, RAW_URL, jobright, policy)

    return jobs, downloaded, downloaded_new_sources


def classify_jobs(jobs: list[Job], state: dict, now_ts: int,
                  first_run_sources: set[str] | None = None) -> tuple[list[Job], int, int]:
    """Split into new alerts vs already-seen vs first-run seed (no email)."""
    index = build_seen_index(state["jobs"])
    first_run_sources = first_run_sources if first_run_sources is not None else unseeded_sources(state)
    new: list[Job] = []
    already_seen = 0
    seeded = 0
    for job in jobs:
        if is_seen_job(job, index):
            already_seen += 1
            continue
        if job.source in first_run_sources and _is_stale_for_first_run(job, now_ts):
            state["jobs"][job.job_id] = asdict(job)
            remember_job(job, index)
            seeded += 1
            continue
        new.append(job)
        state["jobs"][job.job_id] = asdict(job)
        remember_job(job, index)
    return new, already_seen, seeded


def run(state_path: Path, force: bool = False, client: TwilioClient | None = None,
        test_sms: bool = False, retry_sms: str | None = None, resume_sms: bool = False,
        email_client: GmailClient | None = None, queue_email: bool = False,
        test_email: bool = False, retry_email: str | None = None,
        resolve_urls: bool = False, resolver_cache_path: Path | None = None,
        now_ts: int | None = None) -> None:
    with state_lock(state_path):
        state = load_state(state_path)
        email_enabled = email_client is not None or queue_email
        if client and email_enabled:
            raise ValueError("Choose email or SMS, not both")
        if email_enabled:
            enqueue_email(state, [], test=test_email)
            migrate_unsent_sms(state)
            if retry_email:
                item = state["email"].get(retry_email)
                if not item or item["status"] not in {"blocked", "uncertain"}:
                    raise ValueError("Retry ID must identify a blocked or uncertain email")
                item.update(status="pending", attempts=0)
            save_state(state_path, state)
        if client:
            if resume_sms:
                state.pop("sms_paused", None)
            enqueue(state, [], test=test_sms)
            if retry_sms:
                item = state["sms"].get(retry_sms)
                if not item or item["status"] not in {"blocked", "uncertain"}:
                    raise ValueError("Retry ID must identify a blocked or uncertain SMS")
                item.update(status="pending", attempts=0)
            save_state(state_path, state)
        policy = policy_fingerprint(resolve_urls)
        clock = int(now_ts if now_ts is not None else time.time())
        first_run_sources = unseeded_sources(state)
        jobs, downloaded, downloaded_new_sources = collect_jobs(state, force, policy, clock)
        if not downloaded:
            print("Upstream sources unchanged; no new matches.")
            if client:
                deliver(state, state_path, client)
            if email_client:
                deliver_email(state, state_path, email_client)
            save_state(state_path, state)
            return
        titled = [job for job in jobs if is_relevant(job.title)]
        if resolve_urls:
            LOG.info("Resolving URLs for %d relevant jobs...", len(titled))
            titled = resolve_jobs(titled, cache_path=resolver_cache_path)
        relevant = dedupe_jobs(titled)
        new, already_seen, seeded = classify_jobs(titled, state, clock, first_run_sources)
        for name in downloaded_new_sources:
            _source_slot(state, name)["seeded"] = True
        by_source: dict[str, int] = {}
        for job in relevant:
            by_source[job.source] = by_source.get(job.source, 0) + 1
        source_summary = ", ".join(
            f"{SOURCE_LABELS.get(name, name)} {count}" for name, count in sorted(by_source.items())
        ) or "none"
        lines = [f"Found {len(jobs)} listings", f"Rejected {len(jobs) - len(titled)}",
                 f"Deduped to {len(relevant)} ({source_summary})",
                 f"Already seen {already_seen}",
                 f"First-run seeded {seeded}", "", "NEW MATCHES:"]
        for job in new:
            lines.extend(["", "[NEW]", f"Company: {job.company}", f"Title: {job.title}",
                          f"Location: {job.location}", f"Work Model: {job.work_model}",
                          f"Date Posted: {job.date_posted}", f"ATS: {job.ats}",
                          f"Source: {SOURCE_LABELS.get(job.source, job.source)}",
                          f"Apply: {job.canonical_apply_url or job.source_url}"])
        if not new:
            lines.append("None.")
        # Print before marking seen: failures may repeat alerts, never silently lose them.
        print("\n".join(lines), flush=True)
        if client:
            enqueue(state, [asdict(job) for job in new])
        if email_enabled:
            enqueue_email(state, [asdict(job) for job in new])
        save_state(state_path, state)
        if email_client:
            deliver_email(state, state_path, email_client)
        if client:
            deliver(state, state_path, client)
        LOG.info("Saved %d newly discovered matches (%d first-run seeded)", len(new), seeded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll product-management jobs from SimplifyJobs, FindYourRoleFirst, and Jobright")
    parser.add_argument("--state", type=Path, default=config.STATE_PATH)
    parser.add_argument("--force", action="store_true", help="Fetch even with a cached ETag")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--sms", action="store_true", help="Send digests through Twilio")
    parser.add_argument("--test-sms", action="store_true", help="Queue a one-time connection test; implies --sms")
    parser.add_argument("--retry-sms", help="Explicitly retry a blocked/uncertain outbox ID; implies --sms")
    parser.add_argument("--resume-sms", action="store_true", help="Resume paused SMS after fixing sender registration")
    parser.add_argument("--email", action="store_true", help="Send Gmail email digests")
    parser.add_argument("--queue-email", action="store_true", help="Queue email without credentials or sending")
    parser.add_argument("--test-email", action="store_true", help="Queue one-time SMTP test; implies --email")
    parser.add_argument("--test-to", metavar="EMAIL", help="Send a single design test email to this address only; implies --email")
    parser.add_argument("--retry-email", help="Retry a blocked or uncertain email after inspecting Sent mail")
    parser.add_argument("--resolve-urls", action="store_true",
                        help="Resolve Jobright wrapper URLs to direct ATS apply URLs")
    parser.add_argument("--resolver-cache", type=Path, default=config.STATE_PATH.parent / "resolver_cache.json",
                        help="Path to resolver cache file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")
    try:
        email_client = None
        if args.email or args.test_email or args.retry_email or args.test_to:
            load_dotenv(Path(__file__).resolve().parents[1] / ".env")
            email_client = GmailClient.from_environment()
        
        # Handle --test-to: send a single design test email and exit
        if args.test_to:
            send_test_email_to(args.test_to, email_client)
            print(f"Test email sent to {args.test_to}")
            return 0
        
        if args.queue_email:
            LOG.warning("Email queue-only mode: no messages will be sent")
        client = None
        if args.sms or args.test_sms or args.retry_sms or args.resume_sms:
            load_dotenv(Path(__file__).resolve().parents[1] / ".env")
            client = TwilioClient.from_environment()
        run(args.state, args.force, client, args.test_sms, args.retry_sms, args.resume_sms,
            email_client, args.queue_email, args.test_email, args.retry_email,
            args.resolve_urls, args.resolver_cache if args.resolve_urls else None)
    except (OSError, ValueError, SmsError, EmailError) as error:
        LOG.error("Poll failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
