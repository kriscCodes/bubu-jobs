"""ATS enrichment module for fetching pay range and application questions.

Queries Greenhouse, Lever, Ashby, and Workday APIs to enrich job data with:
- Pay range from compensation fields or job description
- Application questions (whether written responses are required)
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import requests

LOG = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent.parent / "data" / "ats_enrichment_cache.json"
REQUEST_TIMEOUT = 15


def _load_cache() -> dict:
    """Load enrichment cache from disk."""
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    """Save enrichment cache to disk."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _extract_pay_from_text(text: str) -> Optional[str]:
    """Extract pay range from job description text."""
    if not text:
        return None
    
    patterns = [
        # $XX,XXX - $XX,XXX or $XXX,XXX - $XXX,XXX
        r'\$[\d,]+\s*[-–—to]+\s*\$[\d,]+(?:\s*(?:per\s+)?(?:year|annually|yr|/yr))?',
        # $XX - $XX/hr or /hour
        r'\$[\d.]+\s*[-–—to]+\s*\$[\d.]+\s*(?:per\s+)?(?:hour|hr|/hr)',
        # $XXk - $XXXk
        r'\$\d+[kK]\s*[-–—to]+\s*\$\d+[kK]',
        # XXX,XXX - XXX,XXX USD
        r'[\d,]+\s*[-–—to]+\s*[\d,]+\s*(?:USD|CAD|GBP)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    
    return None


def _enrich_greenhouse(url: str) -> dict:
    """Enrich job data from Greenhouse API."""
    result = {"pay_range": None, "has_written_questions": None, "source": "greenhouse"}
    
    # Extract board token and job ID
    parts = urlsplit(url)
    host = parts.hostname or ""
    
    board_token = None
    job_id = None
    
    if "job-boards.greenhouse.io" in host:
        match = re.search(r'job-boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', url)
        if match:
            board_token, job_id = match.groups()
    elif "boards.greenhouse.io" in host:
        match = re.search(r'boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', url)
        if match:
            board_token, job_id = match.groups()
    elif "gh_jid=" in url:
        match = re.search(r'gh_jid=(\d+)', url)
        if match:
            job_id = match.group(1)
        # Try to get board from path
        path_match = re.search(r'careers\.([^.]+)\.', url)
        if path_match:
            board_token = path_match.group(1)
    
    if not board_token or not job_id:
        # Try extracting from various URL patterns
        job_match = re.search(r'/jobs?/(\d+)', url)
        if job_match:
            job_id = job_match.group(1)
        
        # Common patterns for board token in URL
        for pattern in [r'greenhouse\.io/([^/]+)', r'careers/([^/]+)/']:
            match = re.search(pattern, url)
            if match:
                board_token = match.group(1)
                break
    
    if not job_id:
        return result
    
    # Try known board tokens for companies
    board_tokens_to_try = [board_token] if board_token else []
    
    # Add company-specific board tokens
    if "roblox" in url.lower():
        board_tokens_to_try.append("roblox")
    elif "databricks" in url.lower():
        board_tokens_to_try.append("databricks")
    elif "impact" in url.lower():
        board_tokens_to_try.append("impact")
    elif "instawork" in url.lower():
        board_tokens_to_try.append("instawork")
    elif "openeye" in url.lower():
        board_tokens_to_try.append("openeye")
    elif "verse" in url.lower():
        board_tokens_to_try.append("verse")
    elif "8451" in url.lower() or "84.51" in url.lower():
        board_tokens_to_try.append("8451")
    
    for token in board_tokens_to_try:
        if not token:
            continue
        try:
            api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"
            resp = requests.get(api_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            
            data = resp.json()
            
            # Check pay_input_ranges
            pay_ranges = data.get("pay_input_ranges", [])
            if pay_ranges:
                pr = pay_ranges[0]
                min_val = pr.get("min_cents", 0) / 100
                max_val = pr.get("max_cents", 0) / 100
                interval = pr.get("interval", "yearly")
                if interval == "yearly":
                    result["pay_range"] = f"${min_val:,.0f} - ${max_val:,.0f}/year"
                elif interval == "hourly":
                    result["pay_range"] = f"${min_val:.2f} - ${max_val:.2f}/hour"
                result["pay_source"] = "Greenhouse pay_input_ranges API"
            
            # Check content for pay if not in structured field
            if not result["pay_range"]:
                content = data.get("content", "")
                pay = _extract_pay_from_text(content)
                if pay:
                    result["pay_range"] = pay
                    result["pay_source"] = "Greenhouse job content"
            
            # Check for questions
            questions = data.get("questions", [])
            has_text_questions = False
            for q in questions:
                q_type = q.get("type", "").lower()
                if q_type in ("short_text", "long_text", "textarea", "text"):
                    has_text_questions = True
                    break
            
            result["has_written_questions"] = has_text_questions
            result["questions_source"] = "Greenhouse questions API"
            
            return result
            
        except Exception as e:
            LOG.debug("Greenhouse API error for %s: %s", url, e)
            continue
    
    return result


def _enrich_lever(url: str) -> dict:
    """Enrich job data from Lever API."""
    result = {"pay_range": None, "has_written_questions": None, "source": "lever"}
    
    # Extract company and posting ID
    match = re.search(r'lever\.co/([^/]+)/([a-f0-9-]{36})', url)
    if not match:
        return result
    
    company, posting_id = match.groups()
    
    try:
        api_url = f"https://api.lever.co/v0/postings/{company}/{posting_id}"
        resp = requests.get(api_url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return result
        
        data = resp.json()
        
        # Check salaryRange
        salary = data.get("salaryRange", {})
        if salary:
            min_val = salary.get("min")
            max_val = salary.get("max")
            currency = salary.get("currency", "USD")
            interval = salary.get("interval", "per-year-salary")
            
            if min_val and max_val:
                if "hour" in interval.lower():
                    result["pay_range"] = f"${min_val:.2f} - ${max_val:.2f}/hour"
                else:
                    result["pay_range"] = f"${min_val:,.0f} - ${max_val:,.0f}/year"
                result["pay_source"] = "Lever salaryRange API"
        
        # Check description for pay
        if not result["pay_range"]:
            desc = data.get("descriptionPlain", "") or data.get("description", "")
            pay = _extract_pay_from_text(desc)
            if pay:
                result["pay_range"] = pay
                result["pay_source"] = "Lever job description"
        
        # Check for text questions in lists
        lists = data.get("lists", [])
        has_text_questions = False
        for lst in lists:
            if lst.get("type") in ("textarea", "text"):
                has_text_questions = True
                break
        
        result["has_written_questions"] = has_text_questions
        result["questions_source"] = "Lever lists API"
        
    except Exception as e:
        LOG.debug("Lever API error for %s: %s", url, e)
    
    return result


def _enrich_workday(url: str) -> dict:
    """Enrich job data from Workday job page."""
    result = {"pay_range": None, "has_written_questions": None, "source": "workday"}
    
    # Workday doesn't have a public API, but we can try to fetch the job page
    # and extract pay info from the HTML/JSON
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BubuJobs/1.0)"
        })
        if resp.status_code != 200:
            return result
        
        text = resp.text
        
        # Try to find pay in the page content
        pay = _extract_pay_from_text(text)
        if pay:
            result["pay_range"] = pay
            result["pay_source"] = "Workday job page"
        
        # Workday applications typically have questions, but we can't easily detect
        # Set to None (unknown) since we can't reliably determine
        result["has_written_questions"] = None
        result["questions_source"] = "Workday (could not determine)"
        
    except Exception as e:
        LOG.debug("Workday fetch error for %s: %s", url, e)
    
    return result


def _enrich_generic(url: str) -> dict:
    """Try to enrich from generic job page."""
    result = {"pay_range": None, "has_written_questions": None, "source": "generic"}
    
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BubuJobs/1.0)"
        })
        if resp.status_code != 200:
            return result
        
        text = resp.text
        pay = _extract_pay_from_text(text)
        if pay:
            result["pay_range"] = pay
            result["pay_source"] = f"Job page text"
        
    except Exception as e:
        LOG.debug("Generic fetch error for %s: %s", url, e)
    
    return result


def enrich_job(job: dict, use_cache: bool = True) -> dict:
    """Enrich a single job with pay range and application questions.
    
    Args:
        job: Job dict with at least 'direct_url' field
        use_cache: Whether to use cached results
    
    Returns:
        Dict with pay_range, has_written_questions, and source fields
    """
    url = job.get("direct_url", "")
    if not url:
        return {"pay_range": None, "has_written_questions": None, "source": "no_url"}
    
    cache = _load_cache() if use_cache else {}
    
    if url in cache:
        return cache[url]
    
    # Determine ATS type and call appropriate enrichment function
    url_lower = url.lower()
    
    if "greenhouse.io" in url_lower or "gh_jid=" in url_lower:
        result = _enrich_greenhouse(url)
    elif "lever.co" in url_lower:
        result = _enrich_lever(url)
    elif "myworkdayjobs.com" in url_lower or "workday" in url_lower:
        result = _enrich_workday(url)
    else:
        result = _enrich_generic(url)
    
    # Cache the result
    cache[url] = result
    _save_cache(cache)
    
    return result


def enrich_all_jobs(jobs: list[dict], use_cache: bool = True) -> list[dict]:
    """Enrich all jobs with pay and question data.
    
    Args:
        jobs: List of job dicts
        use_cache: Whether to use cached results
    
    Returns:
        List of enrichment results for each job
    """
    results = []
    for job in jobs:
        result = enrich_job(job, use_cache=use_cache)
        result["company"] = job.get("company", "")
        result["title"] = job.get("title", "")
        results.append(result)
    return results


# Known pay ranges from manual research (user mentioned these)
KNOWN_PAY_RANGES = {
    "Drive Medical": "$72,000 - $110,000/year",
    "The Upper Deck Company": "$32 - $34/hour",
    "Sun Hydraulics": "$75,000 - $85,000/year",  # Helios
    "Enovation Controls": "$75,000 - $85,000/year",  # Helios
    "H&R Block": "$34.52 - $51.78/hour",
}


def get_known_pay_range(company: str) -> Optional[str]:
    """Get manually researched pay range for a company."""
    return KNOWN_PAY_RANGES.get(company)
