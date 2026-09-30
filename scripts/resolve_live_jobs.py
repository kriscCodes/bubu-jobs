#!/usr/bin/env python3
"""Resolve Jobright URLs for current PM new-grad jobs and generate artifact.

This script fetches the live Jobright README, parses relevant jobs, resolves
their URLs to direct ATS apply links, and outputs a machine-readable artifact.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.filters import is_relevant
from src.sources.jobright import fetch_readme, parse_readme, resolve_jobs


def main() -> int:
    print("Fetching live Jobright README...")
    result = fetch_readme()
    if result.text is None:
        print("ERROR: Failed to fetch README")
        return 1
    
    print("Parsing jobs...")
    all_jobs = parse_readme(result.text)
    print(f"Total jobs parsed: {len(all_jobs)}")
    
    relevant_jobs = [job for job in all_jobs if is_relevant(job.title)]
    print(f"Relevant jobs (matching PM filters): {len(relevant_jobs)}")
    
    if not relevant_jobs:
        print("No relevant jobs found")
        return 0
    
    cache_path = Path(__file__).resolve().parents[1] / "data" / "resolver_cache.json"
    print(f"Resolving URLs (cache: {cache_path})...")
    resolved_jobs = resolve_jobs(relevant_jobs, cache_path=cache_path, rate_limit=0.3)
    
    results = []
    resolved_count = 0
    unresolved_count = 0
    error_count = 0
    
    for original, resolved in zip(relevant_jobs, resolved_jobs):
        entry = {
            "company": resolved.company,
            "title": resolved.title,
            "location": resolved.location,
            "jobright_url": original.source_url,
            "resolved_ats_url": resolved.canonical_apply_url,
            "ats": resolved.ats,
        }
        
        if resolved.canonical_apply_url and resolved.canonical_apply_url != original.source_url:
            entry["status"] = "resolved"
            resolved_count += 1
        elif resolved.ats == "Unknown" and resolved.canonical_apply_url is None:
            entry["status"] = "unresolved"
            unresolved_count += 1
        else:
            if resolved.canonical_apply_url:
                entry["status"] = "resolved"
                resolved_count += 1
            else:
                entry["status"] = "unresolved"
                unresolved_count += 1
        
        results.append(entry)
    
    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    artifact_path = artifact_dir / "resolved_apply_links.json"
    
    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_jobs": len(all_jobs),
        "relevant_jobs": len(relevant_jobs),
        "resolved": resolved_count,
        "unresolved": unresolved_count,
        "errors": error_count,
        "method": "greenhouse_api",
        "jobs": results,
    }
    
    artifact_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    print(f"\nArtifact written to: {artifact_path}")
    
    print("\n=== SUMMARY ===")
    print(f"Total relevant jobs: {len(relevant_jobs)}")
    print(f"Resolved to ATS: {resolved_count}")
    print(f"Unresolved: {unresolved_count}")
    print(f"Errors: {error_count}")
    
    if resolved_count > 0:
        print("\n=== RESOLVED JOBS ===")
        for r in results:
            if r["status"] == "resolved":
                print(f"  {r['company']} - {r['title']}")
                print(f"    ATS: {r['ats']}")
                print(f"    URL: {r['resolved_ats_url']}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
