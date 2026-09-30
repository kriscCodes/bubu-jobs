import argparse
import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from . import config
from .dedupe import load_state, save_state, state_lock
from .filters import is_relevant
from .sources.jobright import fetch_readme, parse_readme, resolve_jobs
from .notifications import TwilioClient, SmsError, load_dotenv, enqueue, deliver

from .email_notifications import (GmailClient, EmailError, enqueue_email,
                                  deliver_email, migrate_unsent_sms)

LOG = logging.getLogger(__name__)


def policy_fingerprint(resolve_urls: bool = False) -> str:
    # Bump parser version when normalization/parsing semantics change.
    # Bump resolver version when URL resolution logic changes.
    value = ["parser-v1", "resolver-v1" if resolve_urls else None,
             config.ACCEPTED_TITLE_KEYWORDS, config.REJECTED_TITLE_KEYWORDS]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def run(state_path: Path, force: bool = False, client: TwilioClient | None = None,
        test_sms: bool = False, retry_sms: str | None = None, resume_sms: bool = False,
        email_client: GmailClient | None = None, queue_email: bool = False,
        test_email: bool = False, retry_email: str | None = None,
        resolve_urls: bool = False, resolver_cache_path: Path | None = None) -> None:
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
        cached = state["source"]
        use_cache = not force and cached.get("url") == config.RAW_URL and cached.get("policy") == policy
        result = fetch_readme(cached.get("etag") if use_cache else None)
        if result.text is None:
            print("Upstream README unchanged; no new matches.")
            if client:
                deliver(state, state_path, client)
            if email_client:
                deliver_email(state, state_path, email_client)
            return
        jobs = parse_readme(result.text)
        relevant = [job for job in jobs if is_relevant(job.title)]
        if resolve_urls:
            LOG.info("Resolving URLs for %d relevant jobs...", len(relevant))
            relevant = resolve_jobs(relevant, cache_path=resolver_cache_path)
        new = []
        already_seen = 0
        for job in relevant:
            if job.job_id in state["jobs"]:
                already_seen += 1
            else:
                new.append(job)
                state["jobs"][job.job_id] = asdict(job)
        state["source"] = {"url": config.RAW_URL, "etag": result.etag, "policy": policy}
        lines = [f"Found {len(jobs)} listings", f"Rejected {len(jobs) - len(relevant)}",
                 f"Already seen {already_seen}", "", "NEW MATCHES:"]
        for job in new:
            lines.extend(["", "[NEW]", f"Company: {job.company}", f"Title: {job.title}",
                          f"Location: {job.location}", f"Work Model: {job.work_model}",
                          f"Date Posted: {job.date_posted}", f"ATS: {job.ats}",
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
        LOG.info("Saved %d newly discovered matches", len(new))


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll Jobright product jobs")
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
    parser.add_argument("--retry-email", help="Retry a blocked/uncertain email after inspecting Sent mail")
    parser.add_argument("--resolve-urls", action="store_true",
                        help="Resolve Jobright wrapper URLs to direct ATS apply URLs")
    parser.add_argument("--resolver-cache", type=Path, default=config.STATE_PATH.parent / "resolver_cache.json",
                        help="Path to resolver cache file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")
    try:
        email_client = None
        if args.email or args.test_email or args.retry_email:
            load_dotenv(Path(__file__).resolve().parents[1] / ".env")
            email_client = GmailClient.from_environment()
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
