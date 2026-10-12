#!/usr/bin/env python3
"""Enrich jobs with pay range and application question data from ATS APIs.

This script queries Greenhouse, Lever, Workday APIs to fetch real pay data
and application question metadata for jobs in direct_apply_links.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ats_enrichment import enrich_job, get_known_pay_range, KNOWN_PAY_RANGES

DATA_PATH = Path(__file__).parent.parent / "data" / "direct_apply_links.json"


def main():
    jobs = json.loads(DATA_PATH.read_text())
    
    # Only process resolved jobs with direct URLs
    resolved_jobs = [j for j in jobs if j.get("status") == "resolved" and j.get("direct_url")]
    
    print(f"Enriching {len(resolved_jobs)} resolved jobs...\n")
    
    results = []
    for job in resolved_jobs:
        company = job.get("company", "")
        title = job.get("title", "")
        url = job.get("direct_url", "")
        
        # Check for known pay range first
        known_pay = get_known_pay_range(company)
        
        # Query ATS API
        enrichment = enrich_job(job, use_cache=True)
        
        pay_range = known_pay or enrichment.get("pay_range")
        pay_source = "Manual research" if known_pay else enrichment.get("pay_source", "Not found")
        
        has_questions = enrichment.get("has_written_questions")
        questions_source = enrichment.get("questions_source", "Not found")
        
        results.append({
            "company": company,
            "title": title[:50] + "..." if len(title) > 50 else title,
            "pay_range": pay_range or "Pay not listed",
            "pay_source": pay_source if pay_range else "No pay data found",
            "has_written_questions": has_questions,
            "questions_source": questions_source,
        })
        
        # Print progress
        q_badge = "Yes" if has_questions is True else ("No" if has_questions is False else "Unknown")
        print(f"✓ {company}: {title[:40]}...")
        print(f"  Pay: {pay_range or 'Not listed'} ({pay_source if pay_range else 'N/A'})")
        print(f"  Written questions: {q_badge} ({questions_source})")
        print()
    
    # Print summary table
    print("\n" + "=" * 100)
    print("ENRICHMENT RESULTS SUMMARY")
    print("=" * 100)
    print(f"{'Company':<25} {'Pay Range':<25} {'Questions':<10} {'Pay Source':<30}")
    print("-" * 100)
    
    for r in results:
        q = "Yes" if r["has_written_questions"] is True else ("No" if r["has_written_questions"] is False else "Unknown")
        print(f"{r['company'][:24]:<25} {r['pay_range'][:24]:<25} {q:<10} {r['pay_source'][:29]:<30}")
    
    print("-" * 100)
    
    # Count stats
    with_pay = sum(1 for r in results if r["pay_range"] != "Pay not listed")
    with_questions = sum(1 for r in results if r["has_written_questions"] is not None)
    
    print(f"\nTotal jobs: {len(results)}")
    print(f"With pay data: {with_pay}")
    print(f"With question data: {with_questions}")
    
    return results


if __name__ == "__main__":
    main()
