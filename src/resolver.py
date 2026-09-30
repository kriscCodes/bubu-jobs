"""Resolve Jobright wrapper URLs to direct ATS apply URLs.

This module searches public ATS (Applicant Tracking System) APIs to find direct
apply links for jobs that only have Jobright wrapper URLs. It supports Greenhouse
and falls back gracefully when no match is found.
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
CACHE_TTL_SECONDS = 86400 * 7  # Cache resolved URLs for 7 days
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 0.5  # Seconds between API requests


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
            result = search_greenhouse(company, title, location)
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
