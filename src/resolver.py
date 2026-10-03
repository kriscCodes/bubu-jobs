"""Resolve Jobright wrapper URLs to direct ATS apply URLs.

This module searches public ATS (Applicant Tracking System) APIs to find direct
apply links for jobs that only have Jobright wrapper URLs. It supports Greenhouse
and Workday, falling back gracefully when no match is found.

Resolution order:
1. Greenhouse public API (boards-api.greenhouse.io)
2. Workday CXS API (for companies with known configurations)
"""
import hashlib
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .ats import detect_ats

LOG = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
CACHE_TTL_SECONDS = 86400 * 7  # Cache resolved URLs for 7 days
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 0.5  # Seconds between API requests
WORKDAY_PAGE_LIMIT = 20  # Workday API page size
WORKDAY_MAX_PAGES = 15  # Max pages to fetch (300 jobs)

# Known Workday configurations: company_name -> (subdomain, wd_number, site_name)
# These are verified to have public CXS APIs accessible without authentication.
WORKDAY_CONFIGS: dict[str, tuple[str, str, str]] = {
    "Mastercard": ("mastercard", "wd1", "CorporateCareers"),
    "The Walt Disney Company": ("disney", "wd5", "disneycareer"),
    "Adobe": ("adobe", "wd5", "external_experienced"),
}

# Known Ashby configurations: company_name -> slug
# These are verified to have public Ashby job boards.
ASHBY_CONFIGS: dict[str, str] = {
    "Alchemy": "alchemy",
}


@dataclass(frozen=True)
class ResolvedUrl:
    """Result of URL resolution attempt."""
    url: str | None
    ats: str
    status: str  # "resolved", "unresolved", "error"
    method: str  # "greenhouse_api", "cache", "none"


def normalize_company_name(name: str) -> str:
    """Normalize company name for board token lookup."""
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"\s*(Inc\.?|LLC|Corp\.?|Corporation|Ltd\.?|Co\.?|Holdings?|Group|Company)\s*$",
                  "", name, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", name.lower())


def normalize_title(title: str) -> str:
    """Normalize job title for comparison."""
    title = unicodedata.normalize("NFKC", title).lower()
    title = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*", " ", title)
    title = re.sub(r"[^\w\s]", " ", title)
    return " ".join(title.split())


def title_similarity(t1: str, t2: str) -> float:
    """Calculate Jaccard similarity between normalized titles."""
    words1 = set(normalize_title(t1).split())
    words2 = set(normalize_title(t2).split())
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)


def _fetch_json(url: str, timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    """Fetch JSON from URL with error handling."""
    headers = {"User-Agent": "bubu-jobs/1.0", "Accept": "application/json"}
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
        LOG.debug("Failed to fetch %s: %s", url, e)
        return None


def _post_json(url: str, body: dict, timeout: int = REQUEST_TIMEOUT) -> dict | None:
    """POST JSON to URL and return JSON response."""
    headers = {
        "User-Agent": "bubu-jobs/1.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        data = json.dumps(body).encode("utf-8")
        req = Request(url, data=data, headers=headers, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
        LOG.debug("Failed to POST %s: %s", url, e)
        return None


def _company_token_variants(company: str) -> Iterator[str]:
    """Generate potential Greenhouse board tokens for a company name."""
    base = normalize_company_name(company)
    yield base
    if not base.endswith("s"):
        yield base + "careers"
    yield base.replace("and", "")
    if len(base) > 3:
        yield base[:len(base)//2]


def search_greenhouse(company: str, title: str, location: str | None = None) -> ResolvedUrl:
    """Search Greenhouse API for a matching job.
    
    Args:
        company: Company name
        title: Job title to match
        location: Optional location for filtering
    
    Returns:
        ResolvedUrl with the result
    """
    for token in _company_token_variants(company):
        url = GREENHOUSE_API.format(token=token)
        data = _fetch_json(url)
        if not data or not isinstance(data, dict):
            continue
        
        jobs = data.get("jobs", [])
        if not jobs:
            continue
        
        LOG.debug("Found Greenhouse board for %s at token %s with %d jobs",
                  company, token, len(jobs))
        
        best_match = None
        best_score = 0.0
        
        for job in jobs:
            gh_title = job.get("title", "")
            score = title_similarity(title, gh_title)
            
            if location:
                gh_location = job.get("location", {}).get("name", "")
                if location.lower() in gh_location.lower():
                    score += 0.1
            
            if score > best_score:
                best_score = score
                best_match = job
        
        if best_match and best_score >= 0.35:
            apply_url = best_match.get("absolute_url")
            if apply_url:
                return ResolvedUrl(
                    url=apply_url,
                    ats=detect_ats(apply_url),
                    status="resolved",
                    method="greenhouse_api"
                )
        
        time.sleep(RATE_LIMIT_DELAY)
    
    return ResolvedUrl(url=None, ats="Unknown", status="unresolved", method="none")


def _get_ashby_slug(company: str) -> str | None:
    """Get Ashby slug for a company if known."""
    if company in ASHBY_CONFIGS:
        return ASHBY_CONFIGS[company]
    
    normalized = normalize_company_name(company)
    for known_company, slug in ASHBY_CONFIGS.items():
        if normalize_company_name(known_company) == normalized:
            return slug
    return None


def search_ashby(company: str, title: str, location: str | None = None) -> ResolvedUrl:
    """Search Ashby API for a matching job.
    
    Args:
        company: Company name (must have known Ashby configuration)
        title: Job title to match
        location: Optional location for filtering
    
    Returns:
        ResolvedUrl with the result
    """
    slug = _get_ashby_slug(company)
    if not slug:
        return ResolvedUrl(url=None, ats="Unknown", status="unresolved", method="none")
    
    url = ASHBY_API.format(slug=slug)
    data = _fetch_json(url)
    
    if not data or not isinstance(data, dict):
        return ResolvedUrl(url=None, ats="Unknown", status="unresolved", method="none")
    
    jobs = data.get("jobs", [])
    if not jobs:
        LOG.debug("No jobs found on Ashby for %s", company)
        return ResolvedUrl(url=None, ats="Unknown", status="unresolved", method="none")
    
    LOG.debug("Found %d Ashby jobs for %s", len(jobs), company)
    
    best_match = None
    best_score = 0.0
    
    for job in jobs:
        ashby_title = job.get("title", "")
        score = title_similarity(title, ashby_title)
        
        if location:
            ashby_location = job.get("location", "")
            if location.lower() in ashby_location.lower():
                score += 0.1
        
        if score > best_score:
            best_score = score
            best_match = job
    
    if best_match and best_score >= 0.35:
        job_url = best_match.get("jobUrl")
        if job_url:
            return ResolvedUrl(
                url=job_url,
                ats="Ashby",
                status="resolved",
                method="ashby_api"
            )
    
    return ResolvedUrl(url=None, ats="Unknown", status="unresolved", method="none")


def _get_workday_config(company: str) -> tuple[str, str, str] | None:
    """Get Workday configuration for a company if known."""
    if company in WORKDAY_CONFIGS:
        return WORKDAY_CONFIGS[company]
    
    normalized = normalize_company_name(company)
    for known_company, config in WORKDAY_CONFIGS.items():
        if normalize_company_name(known_company) == normalized:
            return config
    return None


def search_workday(company: str, title: str, location: str | None = None) -> ResolvedUrl:
    """Search Workday CXS API for a matching job.
    
    Args:
        company: Company name (must have known Workday configuration)
        title: Job title to match
        location: Optional location for filtering
    
    Returns:
        ResolvedUrl with the result
    """
    config = _get_workday_config(company)
    if not config:
        return ResolvedUrl(url=None, ats="Unknown", status="unresolved", method="none")
    
    subdomain, wd_num, site = config
    base_url = f"https://{subdomain}.{wd_num}.myworkdayjobs.com"
    cxs_url = f"{base_url}/wday/cxs/{subdomain}/{site}/jobs"
    
    LOG.debug("Searching Workday for %s at %s", company, cxs_url)
    
    all_jobs: list[dict] = []
    offset = 0
    
    for _ in range(WORKDAY_MAX_PAGES):
        body = {
            "appliedFacets": {},
            "limit": WORKDAY_PAGE_LIMIT,
            "offset": offset,
            "searchText": ""
        }
        
        data = _post_json(cxs_url, body)
        if not data:
            break
        
        jobs = data.get("jobPostings", [])
        if not jobs:
            break
        
        all_jobs.extend(jobs)
        total = data.get("total", 0)
        offset += WORKDAY_PAGE_LIMIT
        
        if offset >= total:
            break
        
        time.sleep(RATE_LIMIT_DELAY)
    
    if not all_jobs:
        LOG.debug("No jobs found on Workday for %s", company)
        return ResolvedUrl(url=None, ats="Unknown", status="unresolved", method="none")
    
    LOG.debug("Found %d Workday jobs for %s", len(all_jobs), company)
    
    best_match = None
    best_score = 0.0
    
    for job in all_jobs:
        wd_title = job.get("title", "")
        score = title_similarity(title, wd_title)
        
        if location:
            wd_location = job.get("locationsText", "")
            if location.lower() in wd_location.lower():
                score += 0.1
        
        if score > best_score:
            best_score = score
            best_match = job
    
    if best_match and best_score >= 0.35:
        external_path = best_match.get("externalPath", "")
        if external_path:
            apply_url = f"{base_url}/en-US/{site}{external_path}"
            return ResolvedUrl(
                url=apply_url,
                ats="Workday",
                status="resolved",
                method="workday_api"
            )
    
    return ResolvedUrl(url=None, ats="Unknown", status="unresolved", method="none")


class UrlResolver:
    """Resolves Jobright URLs to direct ATS apply URLs with caching."""
    
    def __init__(self, cache_path: Path | None = None):
        self.cache_path = cache_path
        self._cache: dict[str, dict] = {}
        self._load_cache()
    
    def _load_cache(self) -> None:
        if self.cache_path and self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("version") == 1:
                    self._cache = data.get("entries", {})
            except (json.JSONDecodeError, OSError) as e:
                LOG.warning("Failed to load resolver cache: %s", e)
    
    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps({
                "version": 1,
                "entries": self._cache
            }, indent=2, ensure_ascii=False)
            self.cache_path.write_text(content, encoding="utf-8")
        except OSError as e:
            LOG.warning("Failed to save resolver cache: %s", e)
    
    def _cache_key(self, company: str, title: str, source_url: str) -> str:
        """Generate cache key from job identifiers."""
        normalized = json.dumps([
            normalize_company_name(company),
            normalize_title(title),
            source_url
        ], ensure_ascii=False)
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
    
    def _is_cache_valid(self, entry: dict) -> bool:
        """Check if cache entry is still valid."""
        cached_at = entry.get("cached_at", 0)
        return time.time() - cached_at < CACHE_TTL_SECONDS
    
    def resolve(self, company: str, title: str, source_url: str,
                location: str | None = None) -> ResolvedUrl:
        """Resolve a Jobright URL to a direct ATS apply URL.
        
        Args:
            company: Company name
            title: Job title
            source_url: Original Jobright URL
            location: Optional job location
        
        Returns:
            ResolvedUrl with the resolution result
        """
        host = (urlsplit(source_url).hostname or "").lower()
        if host != "jobright.ai" and not host.endswith(".jobright.ai"):
            ats = detect_ats(source_url)
            return ResolvedUrl(url=source_url, ats=ats, status="resolved", method="none")
        
        key = self._cache_key(company, title, source_url)
        if key in self._cache and self._is_cache_valid(self._cache[key]):
            entry = self._cache[key]
            LOG.debug("Cache hit for %s - %s", company, title)
            return ResolvedUrl(
                url=entry.get("url"),
                ats=entry.get("ats", "Unknown"),
                status=entry.get("status", "unresolved"),
                method="cache"
            )
        
        LOG.debug("Resolving URL for %s - %s", company, title)
        
        try:
            # Try Greenhouse first
            result = search_greenhouse(company, title, location)
            
            # If Greenhouse didn't resolve, try Workday
            if result.status != "resolved":
                workday_result = search_workday(company, title, location)
                if workday_result.status == "resolved":
                    result = workday_result
            
            # If still not resolved, try Ashby
            if result.status != "resolved":
                ashby_result = search_ashby(company, title, location)
                if ashby_result.status == "resolved":
                    result = ashby_result
        except Exception as e:
            LOG.warning("Resolution error for %s - %s: %s", company, title, e)
            result = ResolvedUrl(url=None, ats="Unknown", status="error", method="none")
        
        self._cache[key] = {
            "url": result.url,
            "ats": result.ats,
            "status": result.status,
            "method": result.method,
            "cached_at": time.time(),
            "company": company,
            "title": title,
            "source_url": source_url,
        }
        self._save_cache()
        
        return result
    
    def resolve_batch(self, jobs: list[dict], rate_limit: float = RATE_LIMIT_DELAY
                      ) -> list[tuple[dict, ResolvedUrl]]:
        """Resolve URLs for a batch of jobs.
        
        Args:
            jobs: List of job dicts with company, title, source_url, location
            rate_limit: Delay between API calls in seconds
        
        Returns:
            List of (job, ResolvedUrl) tuples
        """
        results = []
        for i, job in enumerate(jobs):
            if i > 0:
                time.sleep(rate_limit)
            
            result = self.resolve(
                company=job.get("company", ""),
                title=job.get("title", ""),
                source_url=job.get("source_url", ""),
                location=job.get("location"),
            )
            results.append((job, result))
            
            if (i + 1) % 10 == 0:
                LOG.info("Resolved %d/%d jobs", i + 1, len(jobs))
        
        return results
