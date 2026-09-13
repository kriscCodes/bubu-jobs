import argparse
import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from . import config
from .dedupe import load_state, save_state, state_lock
from .filters import is_relevant
from .sources.jobright import fetch_readme, parse_readme
from .notifications import TwilioClient, SmsError, load_dotenv, enqueue, deliver

LOG = logging.getLogger(__name__)


def policy_fingerprint() -> str:
    # Bump parser version when normalization/parsing semantics change.
    value = ["parser-v1", config.ACCEPTED_TITLE_KEYWORDS, config.REJECTED_TITLE_KEYWORDS]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def run(state_path: Path, force: bool = False, client: TwilioClient | None = None,
        test_sms: bool = False, retry_sms: str | None = None, resume_sms: bool = False) -> None:
    with state_lock(state_path):
        state = load_state(state_path)
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
        policy = policy_fingerprint()
        cached = state["source"]
        use_cache = not force and cached.get("url") == config.RAW_URL and cached.get("policy") == policy
        result = fetch_readme(cached.get("etag") if use_cache else None)
        if result.text is None:
            print("Upstream README unchanged; no new matches.")
            if client:
                deliver(state, state_path, client)
            return
        jobs = parse_readme(result.text)
        relevant = [job for job in jobs if is_relevant(job.title)]
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
        save_state(state_path, state)
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
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")
    try:
        client = None
        if args.sms or args.test_sms or args.retry_sms or args.resume_sms:
            load_dotenv(Path(__file__).resolve().parents[1] / ".env")
            client = TwilioClient.from_environment()
        run(args.state, args.force, client, args.test_sms, args.retry_sms, args.resume_sms)
    except (OSError, ValueError, SmsError) as error:
        LOG.error("Poll failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
