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

LOG = logging.getLogger(__name__)


def policy_fingerprint() -> str:
    # Bump parser version when normalization/parsing semantics change.
    value = ["parser-v1", config.ACCEPTED_TITLE_KEYWORDS, config.REJECTED_TITLE_KEYWORDS]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def run(state_path: Path, force: bool = False) -> None:
    with state_lock(state_path):
        state = load_state(state_path)
        policy = policy_fingerprint()
        cached = state["source"]
        use_cache = not force and cached.get("url") == config.RAW_URL and cached.get("policy") == policy
        result = fetch_readme(cached.get("etag") if use_cache else None)
        if result.text is None:
            print("Upstream README unchanged; no new matches.")
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
        save_state(state_path, state)
        LOG.info("Saved %d newly discovered matches", len(new))


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll Jobright product jobs")
    parser.add_argument("--state", type=Path, default=config.STATE_PATH)
    parser.add_argument("--force", action="store_true", help="Fetch even with a cached ETag")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")
    try:
        run(args.state, args.force)
    except (OSError, ValueError) as error:
        LOG.error("Poll failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
