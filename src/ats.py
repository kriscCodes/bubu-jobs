"""ATS (Applicant Tracking System) detection and application question checking.

This module detects which ATS platform a job posting uses and can check
whether the application requires written responses (essays, short-answer questions).
"""
import logging
import re
from typing import Optional
from urllib.parse import urlsplit, parse_qs

import requests

LOG = logging.getLogger(__name__)

ATS_DOMAINS = {
    "Greenhouse": ("greenhouse.io",),
    "Workday": ("myworkdayjobs.com", "myworkdaysite.com"),
    "Lever": ("lever.co",),
    "Ashby": ("ashbyhq.com",),
    "iCIMS": ("icims.com",),
    "SmartRecruiters": ("smartrecruiters.com",),
}

ATS_PARAMS = {
    "gh_jid": "Greenhouse",
}


def detect_ats(url: str) -> str:
    """Detect the ATS platform from a URL.
    
    Checks both domain-based detection and query parameter patterns
    for custom-domain integrations.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    
    for ats, domains in ATS_DOMAINS.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return ats
    
    query = parse_qs(parts.query)
    for param, ats in ATS_PARAMS.items():
        if param in query:
            return ats
    
    return "Unknown"


def _extract_greenhouse_job_id(url: str) -> Optional[str]:
    """Extract Greenhouse job ID from URL."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    
    if "gh_jid" in query:
        return query["gh_jid"][0]
    
    match = re.search(r'/jobs?/(\d+)', parts.path)
    if match:
        return match.group(1)
    
    return None


def _extract_lever_posting_id(url: str) -> Optional[str]:
    """Extract Lever posting ID from URL."""
    match = re.search(r'/([a-f0-9-]{36})', url)
    if match:
        return match.group(1)
    return None


def _extract_ashby_job_id(url: str) -> Optional[str]:
    """Extract Ashby job ID from URL."""
    match = re.search(r'/([a-f0-9-]{36})', url)
    if match:
        return match.group(1)
    return None


def _check_greenhouse_questions(url: str) -> Optional[bool]:
    """Check Greenhouse job for application questions.
    
    Uses the Greenhouse public API to check if a job has custom questions
    that require written responses (text, textarea types).
    
    Returns:
        True if written questions exist, False if not, None if can't determine
    """
    job_id = _extract_greenhouse_job_id(url)
    if not job_id:
        return None
    
    parts = urlsplit(url)
    host = parts.hostname or ""
    
    board_token = None
    if "job-boards.greenhouse.io" in host:
        match = re.search(r'job-boards\.greenhouse\.io/([^/]+)', url)
        if match:
            board_token = match.group(1)
    elif "boards.greenhouse.io" in host:
        match = re.search(r'boards\.greenhouse\.io/([^/]+)', url)
        if match:
            board_token = match.group(1)
    else:
        match = re.search(r'gh_jid=\d+', url)
        if match:
            path_match = re.search(r'//([^/]+)', url)
            if path_match:
                pass
    
    if not board_token:
        return None
    
    try:
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        questions = data.get("questions", [])
        
        for q in questions:
            q_type = q.get("type", "").lower()
            if q_type in ("short_text", "long_text", "textarea", "text"):
                return True
        
        return False
        
    except Exception as e:
        LOG.debug("Greenhouse API error for %s: %s", url, e)
        return None


def _check_lever_questions(url: str) -> Optional[bool]:
    """Check Lever job for application questions.
    
    Lever's public postings API exposes application questions.
    
    Returns:
        True if written questions exist, False if not, None if can't determine
    """
    posting_id = _extract_lever_posting_id(url)
    if not posting_id:
        return None
    
    parts = urlsplit(url)
    host = parts.hostname or ""
    
    company = None
    if "jobs.lever.co" in host:
        match = re.search(r'jobs\.lever\.co/([^/]+)', url)
        if match:
            company = match.group(1)
    elif "lever.co" in host:
        match = re.search(r'lever\.co/([^/]+)', url)
        if match:
            company = match.group(1)
    
    if not company:
        return None
    
    try:
        api_url = f"https://api.lever.co/v0/postings/{company}/{posting_id}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        lists = data.get("lists", [])
        
        for lst in lists:
            if lst.get("type") in ("textarea", "text"):
                return True
        
        return False
        
    except Exception as e:
        LOG.debug("Lever API error for %s: %s", url, e)
        return None


def _check_ashby_questions(url: str) -> Optional[bool]:
    """Check Ashby job for application questions.
    
    Returns:
        True if written questions exist, False if not, None if can't determine
    """
    return None


def _check_workday_questions(url: str) -> Optional[bool]:
    """Check Workday job for application questions.
    
    Workday's public job postings sometimes expose questionnaire info,
    but it's highly variable. Returns None for most cases.
    
    Returns:
        True if written questions exist, False if not, None if can't determine
    """
    return None


def check_application_questions(url: str, ats: Optional[str] = None) -> Optional[bool]:
    """Check if a job application requires written responses.
    
    Queries the ATS's public API when available to determine if the
    application includes essay or short-answer questions.
    
    Args:
        url: The direct apply URL
        ats: Optional ATS name (will be detected if not provided)
    
    Returns:
        True: Application definitely requires written responses
        False: Application is quick-apply (no essays)
        None: Cannot determine (show "Unknown" in UI)
    """
    if not url:
        return None
    
    if ats is None:
        ats = detect_ats(url)
    
    if ats == "Greenhouse":
        return _check_greenhouse_questions(url)
    elif ats == "Lever":
        return _check_lever_questions(url)
    elif ats == "Ashby":
        return _check_ashby_questions(url)
    elif ats == "Workday":
        return _check_workday_questions(url)
    
    return None
