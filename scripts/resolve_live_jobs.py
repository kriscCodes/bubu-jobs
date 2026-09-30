#!/usr/bin/env python3
"""Resolve Jobright URLs for current PM new-grad jobs and generate artifact.

This script fetches the live Jobright README, parses relevant jobs, resolves
their URLs to direct ATS apply links, and outputs a machine-readable artifact.

Supports:
- Greenhouse API resolution
- Workday CXS API resolution
- Ashby API resolution
- Optional browser-based fallback (--browser flag)
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.filters import is_relevant
from src.sources.jobright import fetch_readme, parse_readme, resolve_jobs


def get_company_urls() -> dict[str, str]:
    """Fetch company URLs from the Jobright README."""
    url = 'https://raw.githubusercontent.com/jobright-ai/2026-Product-Management-New-Grad/master/README.md'
    headers = {'User-Agent': 'bubu-jobs/1.0'}
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as resp:
        content = resp.read().decode('utf-8')
    
    company_pattern = re.compile(r'\*\*\[([^\]]+)\]\((https?://[^\)]+)\)\*\*')
    companies = {}
    for match in company_pattern.finditer(content):
        name = match.group(1)
        company_url = match.group(2)
        if name != '↳' and name not in companies:
            companies[name] = company_url
    return companies


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve Jobright URLs to ATS apply links")
    parser.add_argument("--browser", action="store_true",
                        help="Enable browser-based search fallback for unresolved jobs")
    parser.add_argument("--jobright-browser", action="store_true",
                        help="Enable Jobright browser fallback (requires JOBRIGHT_EMAIL/PASSWORD)")
    args = parser.parse_args()
    
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
    print(f"Resolving URLs via API (cache: {cache_path})...")
    resolved_jobs = resolve_jobs(relevant_jobs, cache_path=cache_path, rate_limit=0.3)
    
    # Browser fallback for unresolved jobs
    browser_resolved = {}
    if args.browser:
        unresolved = [(orig, res) for orig, res in zip(relevant_jobs, resolved_jobs)
                      if res.canonical_apply_url is None]
        
        if unresolved:
            print(f"\nBrowser fallback for {len(unresolved)} unresolved jobs...")
            try:
                from src.browser_resolver import BrowserResolver
                
                company_urls = get_company_urls()
                browser_resolver = BrowserResolver(cache_path=cache_path)
                
                for i, (orig, _) in enumerate(unresolved):
                    company_url = company_urls.get(orig.company, "")
                    if not company_url:
                        continue
                    
                    result = browser_resolver.resolve_via_browser(
                        company=orig.company,
                        title=orig.title,
                        company_url=company_url,
                        location=orig.location,
                    )
                    
                    if result.status == "resolved":
                        browser_resolved[orig.job_id] = result
                        print(f"  Browser resolved: {orig.company} - {orig.title}")
                    
                    if (i + 1) % 10 == 0:
                        print(f"  Progress: {i + 1}/{len(unresolved)}")
                
                browser_resolver.close()
            except ImportError:
                print("  WARNING: Playwright not available, skipping browser fallback")
    
    # Jobright browser fallback (visits Jobright pages directly)
    jobright_browser_resolved = {}
    jobright_browser_stats = {"login_required": 0, "cloudflare_blocked": 0, "resolved": 0}
    
    if args.jobright_browser:
        # Re-check what's still unresolved after browser fallback
        still_unresolved = [(orig, res) for orig, res in zip(relevant_jobs, resolved_jobs)
                           if res.canonical_apply_url is None and orig.job_id not in browser_resolved]
        
        if still_unresolved:
            print(f"\nJobright browser fallback for {len(still_unresolved)} unresolved jobs...")
            try:
                from src.jobright_browser import JobrightBrowserResolver, extract_job_id
                
                jobright_resolver = JobrightBrowserResolver(cache_path=cache_path)
                print(f"  Credentials available: {jobright_resolver.has_credentials}")
                
                for i, (orig, _) in enumerate(still_unresolved):
                    job_id = extract_job_id(orig.source_url)
                    if not job_id:
                        continue
                    
                    result = jobright_resolver.resolve_via_jobright(
                        job_id=job_id,
                        company=orig.company,
                        title=orig.title,
                    )
                    
                    if result.status == "resolved":
                        jobright_browser_resolved[orig.job_id] = result
                        jobright_browser_stats["resolved"] += 1
                        print(f"  Jobright resolved: {orig.company} - {orig.title}")
                    elif result.status == "login_required":
                        jobright_browser_stats["login_required"] += 1
                        if i == 0:  # Only show blocker once
                            print(f"  Login required: {result.blocker_details}")
                    elif result.status == "cloudflare_blocked":
                        jobright_browser_stats["cloudflare_blocked"] += 1
                        print(f"  Cloudflare blocked: {orig.company}")
                    
                    if (i + 1) % 10 == 0:
                        print(f"  Progress: {i + 1}/{len(still_unresolved)}")
                    
                    # Stop if login required and no credentials
                    if result.status == "login_required" and not jobright_resolver.has_credentials:
                        print("  Stopping: login required and no credentials available")
                        break
                
                jobright_resolver.close()
            except ImportError:
                print("  WARNING: Playwright not available, skipping Jobright browser fallback")
    
    results = []
    resolved_count = 0
    unresolved_count = 0
    error_count = 0
    greenhouse_count = 0
    workday_count = 0
    ashby_count = 0
    browser_count = 0
    
    jobright_browser_count = 0
    
    for original, resolved in zip(relevant_jobs, resolved_jobs):
        # Check if browser resolved this job
        browser_result = browser_resolved.get(original.job_id)
        jobright_result = jobright_browser_resolved.get(original.job_id)
        
        entry = {
            "company": resolved.company,
            "title": resolved.title,
            "location": resolved.location,
            "jobright_url": original.source_url,
            "resolved_ats_url": resolved.canonical_apply_url,
            "ats": resolved.ats,
            "method": "api",
        }
        
        # Use Jobright browser result first (most direct method)
        if jobright_result and jobright_result.status == "resolved":
            entry["resolved_ats_url"] = jobright_result.url
            entry["ats"] = jobright_result.ats
            entry["method"] = jobright_result.method
            entry["status"] = "resolved"
            resolved_count += 1
            jobright_browser_count += 1
        # Then check browser search result
        elif browser_result and browser_result.status == "resolved":
            entry["resolved_ats_url"] = browser_result.url
            entry["ats"] = browser_result.ats
            entry["method"] = browser_result.method
            entry["status"] = "resolved"
            resolved_count += 1
            browser_count += 1
        elif resolved.canonical_apply_url and resolved.canonical_apply_url != original.source_url:
            entry["status"] = "resolved"
            entry["method"] = f"{resolved.ats.lower()}_api" if resolved.ats != "Unknown" else "api"
            resolved_count += 1
            if resolved.ats == "Greenhouse":
                greenhouse_count += 1
            elif resolved.ats == "Workday":
                workday_count += 1
            elif resolved.ats == "Ashby":
                ashby_count += 1
        elif resolved.ats == "Unknown" and resolved.canonical_apply_url is None:
            entry["status"] = "unresolved"
            entry["method"] = "none"
            unresolved_count += 1
        else:
            if resolved.canonical_apply_url:
                entry["status"] = "resolved"
                entry["method"] = f"{resolved.ats.lower()}_api" if resolved.ats != "Unknown" else "api"
                resolved_count += 1
                if resolved.ats == "Greenhouse":
                    greenhouse_count += 1
                elif resolved.ats == "Workday":
                    workday_count += 1
                elif resolved.ats == "Ashby":
                    ashby_count += 1
            else:
                entry["status"] = "unresolved"
                entry["method"] = "none"
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
        "resolved_greenhouse": greenhouse_count,
        "resolved_workday": workday_count,
        "resolved_ashby": ashby_count,
        "resolved_browser_search": browser_count,
        "resolved_jobright_browser": jobright_browser_count,
        "unresolved": unresolved_count,
        "errors": error_count,
        "methods": [
            "greenhouse_api", "workday_api", "ashby_api",
            "browser_search", "browser_jobright_manual_apply"
        ],
        "browser_search_enabled": args.browser,
        "jobright_browser_enabled": args.jobright_browser,
        "jobright_browser_stats": jobright_browser_stats if args.jobright_browser else None,
        "jobs": results,
    }
    
    artifact_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    print(f"\nArtifact written to: {artifact_path}")
    
    print("\n=== SUMMARY ===")
    print(f"Total relevant jobs: {len(relevant_jobs)}")
    print(f"Resolved to ATS: {resolved_count}")
    print(f"  - Greenhouse API: {greenhouse_count}")
    print(f"  - Workday API: {workday_count}")
    print(f"  - Ashby API: {ashby_count}")
    print(f"  - Browser Search: {browser_count}")
    print(f"  - Jobright Browser: {jobright_browser_count}")
    print(f"Unresolved: {unresolved_count}")
    print(f"Errors: {error_count}")
    
    if args.jobright_browser and jobright_browser_stats:
        print("\n=== JOBRIGHT BROWSER STATS ===")
        print(f"  Login required (no credentials): {jobright_browser_stats['login_required']}")
        print(f"  Cloudflare blocked: {jobright_browser_stats['cloudflare_blocked']}")
        print(f"  Resolved: {jobright_browser_stats['resolved']}")
    
    if greenhouse_count > 0:
        print("\n=== GREENHOUSE RESOLVED ===")
        for r in results:
            if r["status"] == "resolved" and r["ats"] == "Greenhouse":
                print(f"  {r['company']} - {r['title']}")
                print(f"    URL: {r['resolved_ats_url']}")
    
    if workday_count > 0:
        print("\n=== WORKDAY RESOLVED ===")
        for r in results:
            if r["status"] == "resolved" and r["ats"] == "Workday":
                print(f"  {r['company']} - {r['title']}")
                print(f"    URL: {r['resolved_ats_url']}")
    
    if ashby_count > 0:
        print("\n=== ASHBY RESOLVED ===")
        for r in results:
            if r["status"] == "resolved" and r["ats"] == "Ashby":
                print(f"  {r['company']} - {r['title']}")
                print(f"    URL: {r['resolved_ats_url']}")
    
    if browser_count > 0:
        print("\n=== BROWSER RESOLVED ===")
        for r in results:
            if r["status"] == "resolved" and "browser" in r.get("method", ""):
                print(f"  {r['company']} - {r['title']}")
                print(f"    URL: {r['resolved_ats_url']}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
