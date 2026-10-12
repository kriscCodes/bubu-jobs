"""Browser-based fallback resolver for jobs not resolved by API methods.

This module uses Playwright to search for job postings via search engines,
looking for direct ATS apply URLs. It's designed as an optional fallback
that can be run separately from the main poll cycle.

The primary approach is to search for "company + job title" on DuckDuckGo
and look for ATS URLs in the search results. This mimics how a human would
find the actual job posting.

Usage:
    python -m src.browser_resolver [--cache-path PATH]

Or programmatically:
    from src.browser_resolver import BrowserResolver
    resolver = BrowserResolver(cache_path)
    result = resolver.resolve_via_browser(company, title, company_url, location)
"""
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import quote_plus, urlsplit

LOG = logging.getLogger(__name__)

ATS_DOMAINS = {
    "greenhouse.io": "Greenhouse",
    "boards.greenhouse.io": "Greenhouse",
    "job-boards.greenhouse.io": "Greenhouse",
    "myworkdayjobs.com": "Workday",
    "myworkdaysite.com": "Workday",
    "lever.co": "Lever",
    "jobs.lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "jobs.ashbyhq.com": "Ashby",
    "icims.com": "iCIMS",
    "smartrecruiters.com": "SmartRecruiters",
    "jobs.smartrecruiters.com": "SmartRecruiters",
}

WRAPPER_DOMAINS = {
    "jobright.ai",
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
}

RATE_LIMIT_DELAY = 3.0  # Seconds between browser searches
BROWSER_TIMEOUT = 25000  # 25 seconds
SEARCH_RESULTS_WAIT = 2000  # 2 seconds to wait for search results


@dataclass(frozen=True)
class BrowserResolvedUrl:
    """Result of browser-based URL resolution."""
    url: str | None
    ats: str
    status: str  # "resolved", "unresolved", "error"
    method: str  # "browser_careers", "browser_redirect"


def _detect_ats_from_url(url: str) -> str | None:
    """Detect ATS from URL domain."""
    host = (urlsplit(url).hostname or "").lower()
    for domain, ats in ATS_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return ats
    return None


def _is_wrapper_url(url: str) -> bool:
    """Check if URL is from a job aggregator/wrapper site."""
    host = (urlsplit(url).hostname or "").lower()
    for domain in WRAPPER_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _extract_job_id_from_url(url: str) -> str | None:
    """Extract job ID from an ATS URL if present."""
    patterns = [
        r"/jobs?/(\d+)",
        r"gh_jid=(\d+)",
        r"job[_-]?id=([a-zA-Z0-9_-]+)",
        r"/job/[^/]+/([a-zA-Z0-9_-]+)",
    ]
    for pat in patterns:
        match = re.search(pat, url)
        if match:
            return match.group(1)
    return None


def _normalize_title(title: str) -> str:
    """Normalize title for matching."""
    title = title.lower()
    title = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*", " ", title)
    title = re.sub(r"[^\w\s]", " ", title)
    return " ".join(title.split())


def _title_similarity(t1: str, t2: str) -> float:
    """Calculate word overlap similarity."""
    words1 = set(_normalize_title(t1).split())
    words2 = set(_normalize_title(t2).split())
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


def _find_career_links(page) -> Iterator[str]:
    """Find potential career page links on a page."""
    career_keywords = ["careers", "jobs", "work with us", "join us", "opportunities", "hiring"]
    
    try:
        links = page.locator("a").all()
        for link in links[:100]:
            try:
                text = link.inner_text().lower()
                href = link.get_attribute("href")
                if href and any(kw in text for kw in career_keywords):
                    yield href
            except Exception:
                pass
    except Exception:
        pass


def _search_duckduckgo(page, company: str, title: str) -> BrowserResolvedUrl | None:
    """Search DuckDuckGo for the job and look for ATS URLs in results.
    
    Uses JavaScript-enabled DuckDuckGo and interacts with the search box
    to better mimic human behavior and avoid blocks.
    
    Args:
        page: Playwright page object
        company: Company name
        title: Job title
    
    Returns:
        BrowserResolvedUrl if an ATS URL is found, None otherwise
    """
    query = f'{company} {title} job apply'
    
    try:
        LOG.debug("Searching DuckDuckGo: %s", query)
        
        page.goto("https://duckduckgo.com", wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        page.wait_for_timeout(1000)
        
        search_box = page.locator('input[name="q"]').first
        if search_box.is_visible():
            search_box.fill(query)
            search_box.press("Enter")
            page.wait_for_timeout(SEARCH_RESULTS_WAIT)
        else:
            search_url = f"https://duckduckgo.com/?q={quote_plus(query)}&ia=web"
            page.goto(search_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
            page.wait_for_timeout(SEARCH_RESULTS_WAIT)
        
        result_links = page.locator("a[href]").all()
        ats_candidates = []
        
        for link in result_links[:50]:
            try:
                href = link.get_attribute("href")
                if not href:
                    continue
                
                if href.startswith("//duckduckgo.com/l/"):
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    uddg = parsed.get("uddg", [])
                    if uddg:
                        href = urllib.parse.unquote(uddg[0])
                
                if not href.startswith("http"):
                    continue
                
                if _is_wrapper_url(href):
                    continue
                
                ats = _detect_ats_from_url(href)
                if ats:
                    ats_candidates.append((href, ats))
                    
            except Exception:
                continue
        
        if ats_candidates:
            best_url, best_ats = ats_candidates[0]
            LOG.info("Found ATS URL via search: %s (%s)", best_url, best_ats)
            return BrowserResolvedUrl(
                url=best_url,
                ats=best_ats,
                status="resolved",
                method="browser_search"
            )
        
        return None
        
    except Exception as e:
        LOG.debug("DuckDuckGo search error: %s", e)
        return None


def _search_with_site_operator(page, company: str, title: str, 
                                ats_domain: str) -> BrowserResolvedUrl | None:
    """Search for job on a specific ATS domain using site: operator.
    
    Args:
        page: Playwright page object
        company: Company name  
        title: Job title
        ats_domain: ATS domain to search (e.g., "greenhouse.io")
    
    Returns:
        BrowserResolvedUrl if found, None otherwise
    """
    query = f'site:{ats_domain} {company} "{title}"'
    search_url = f"https://duckduckgo.com/?q={quote_plus(query)}&ia=web"
    
    try:
        LOG.debug("Site search: %s", query)
        page.goto(search_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        page.wait_for_timeout(SEARCH_RESULTS_WAIT)
        
        result_links = page.locator("a[href]").all()
        
        for link in result_links[:30]:
            try:
                href = link.get_attribute("href")
                if not href:
                    continue
                
                if href.startswith("//duckduckgo.com/l/"):
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    uddg = parsed.get("uddg", [])
                    if uddg:
                        href = urllib.parse.unquote(uddg[0])
                
                if not href.startswith("http"):
                    continue
                
                ats = _detect_ats_from_url(href)
                if ats:
                    job_id = _extract_job_id_from_url(href)
                    if job_id:
                        LOG.info("Found ATS URL via site search: %s", href)
                        return BrowserResolvedUrl(
                            url=href,
                            ats=ats,
                            status="resolved",
                            method="browser_search"
                        )
            except Exception:
                continue
        
        return None
        
    except Exception as e:
        LOG.debug("Site search error for %s: %s", ats_domain, e)
        return None


def _search_bing(page, company: str, title: str) -> BrowserResolvedUrl | None:
    """Search Bing for the job and look for ATS URLs in results.
    
    Bing tends to be more tolerant of automated searches than Google.
    We extract actual URLs from the cite elements shown in results.
    
    Args:
        page: Playwright page object
        company: Company name
        title: Job title
    
    Returns:
        BrowserResolvedUrl if an ATS URL is found, None otherwise
    """
    query = f'{company} {title} job careers apply'
    search_url = f"https://www.bing.com/search?q={quote_plus(query)}"
    
    try:
        LOG.debug("Searching Bing: %s", query)
        page.goto(search_url, wait_until="networkidle", timeout=BROWSER_TIMEOUT)
        page.wait_for_timeout(1500)
        
        cite_elements = page.locator("li.b_algo cite").all()
        
        for cite in cite_elements[:15]:
            try:
                url_text = cite.inner_text().strip()
                if not url_text:
                    continue
                
                url_text = url_text.replace(" › ", "/").replace("›", "/")
                
                if not url_text.startswith("http"):
                    url_text = "https://" + url_text
                
                if _is_wrapper_url(url_text):
                    continue
                
                ats = _detect_ats_from_url(url_text)
                if ats:
                    LOG.info("Found ATS URL via Bing: %s (%s)", url_text, ats)
                    return BrowserResolvedUrl(
                        url=url_text,
                        ats=ats,
                        status="resolved",
                        method="browser_search"
                    )
                    
            except Exception:
                continue
        
        return None
        
    except Exception as e:
        LOG.debug("Bing search error: %s", e)
        return None


def _resolve_via_company_careers(page, company_url: str, title: str
                                   ) -> BrowserResolvedUrl | None:
    """Try to find ATS URL via company careers page.
    
    1. Visit company URL
    2. Find and click careers link
    3. Check if it redirects to an ATS
    4. Search for the job title
    """
    try:
        page.goto(company_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        page.wait_for_timeout(1000)
        
        # Check if landing page is already an ATS
        ats = _detect_ats_from_url(page.url)
        if ats:
            return BrowserResolvedUrl(
                url=page.url,
                ats=ats,
                status="resolved",
                method="browser_redirect"
            )
        
        # Find career links
        career_links = list(_find_career_links(page))
        
        for href in career_links[:3]:
            try:
                if href.startswith("/"):
                    base = re.match(r"https?://[^/]+", page.url)
                    if base:
                        href = base.group(0) + href
                elif not href.startswith("http"):
                    continue
                
                page.goto(href, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                page.wait_for_timeout(1000)
                
                # Check if career page is an ATS
                ats = _detect_ats_from_url(page.url)
                if ats:
                    return BrowserResolvedUrl(
                        url=page.url,
                        ats=ats,
                        status="resolved",
                        method="browser_careers"
                    )
                
                # Look for job links that match title
                job_links = page.locator("a").all()
                for link in job_links[:100]:
                    try:
                        link_href = link.get_attribute("href")
                        link_text = link.inner_text()
                        
                        if link_href and _title_similarity(title, link_text) >= 0.35:
                            ats = _detect_ats_from_url(link_href)
                            if ats:
                                return BrowserResolvedUrl(
                                    url=link_href,
                                    ats=ats,
                                    status="resolved",
                                    method="browser_careers"
                                )
                    except Exception:
                        pass
            except Exception:
                continue
        
        return None
        
    except Exception as e:
        LOG.debug("Browser error for %s: %s", company_url, e)
        return None


class BrowserResolver:
    """Browser-based fallback resolver using Playwright."""
    
    def __init__(self, cache_path: Path | None = None):
        self.cache_path = cache_path
        self._cache: dict[str, dict] = {}
        self._browser = None
        self._context = None
        self._page = None
        self._load_cache()
    
    def _load_cache(self) -> None:
        if self.cache_path and self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("version") == 1:
                    self._cache = data.get("browser_entries", {})
            except (json.JSONDecodeError, OSError):
                pass
    
    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            existing = {}
            if self.cache_path.exists():
                try:
                    existing = json.loads(self.cache_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    existing = {"version": 1, "entries": {}}
            
            existing["browser_entries"] = self._cache
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except OSError as e:
            LOG.warning("Failed to save browser cache: %s", e)
    
    def _cache_key(self, company: str, title: str) -> str:
        """Generate cache key."""
        import hashlib
        normalized = json.dumps([company.lower(), _normalize_title(title)])
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
    
    def _ensure_browser(self):
        """Ensure browser is initialized."""
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
                self._context = self._browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                self._page = self._context.new_page()
            except ImportError:
                raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")
    
    def close(self):
        """Close browser resources."""
        if self._browser:
            self._browser.close()
            self._playwright.stop()
            self._browser = None
            self._page = None
    
    def resolve_via_browser(self, company: str, title: str, company_url: str,
                            location: str | None = None) -> BrowserResolvedUrl:
        """Attempt to resolve a job URL using browser automation.
        
        Resolution order:
        1. Search DuckDuckGo for "company + title + careers apply"
        2. Site-specific searches on major ATS domains
        3. Visit company careers page and look for ATS redirects
        
        Args:
            company: Company name
            title: Job title
            company_url: Company website URL
            location: Optional job location
        
        Returns:
            BrowserResolvedUrl with the result
        """
        key = self._cache_key(company, title)
        if key in self._cache:
            entry = self._cache[key]
            LOG.debug("Browser cache hit for %s - %s", company, title)
            return BrowserResolvedUrl(
                url=entry.get("url"),
                ats=entry.get("ats", "Unknown"),
                status=entry.get("status", "unresolved"),
                method="cache"
            )
        
        LOG.info("Browser resolving: %s - %s", company, title)
        
        try:
            self._ensure_browser()
            
            # 1. Try general DuckDuckGo search first
            result = _search_duckduckgo(self._page, company, title)
            if result and result.status == "resolved":
                self._cache[key] = {
                    "url": result.url,
                    "ats": result.ats,
                    "status": result.status,
                    "method": result.method,
                    "cached_at": time.time(),
                }
                self._save_cache()
                return result
            
            time.sleep(1.5)
            
            # 2. Try Bing search
            result = _search_bing(self._page, company, title)
            if result and result.status == "resolved":
                self._cache[key] = {
                    "url": result.url,
                    "ats": result.ats,
                    "status": result.status,
                    "method": result.method,
                    "cached_at": time.time(),
                }
                self._save_cache()
                return result
            
            time.sleep(1.5)
            
            # 3. Try site-specific searches on major ATS platforms
            ats_domains = ["greenhouse.io", "lever.co", "myworkdayjobs.com"]
            for ats_domain in ats_domains:
                result = _search_with_site_operator(self._page, company, title, ats_domain)
                if result and result.status == "resolved":
                    self._cache[key] = {
                        "url": result.url,
                        "ats": result.ats,
                        "status": result.status,
                        "method": result.method,
                        "cached_at": time.time(),
                    }
                    self._save_cache()
                    return result
                time.sleep(1.0)
            
            # 4. Fall back to career page navigation
            if company_url:
                result = _resolve_via_company_careers(self._page, company_url, title)
                if result and result.status == "resolved":
                    self._cache[key] = {
                        "url": result.url,
                        "ats": result.ats,
                        "status": result.status,
                        "method": result.method,
                        "cached_at": time.time(),
                    }
                    self._save_cache()
                    return result
            
        except Exception as e:
            LOG.warning("Browser resolution error for %s: %s", company, e)
        
        # Cache negative result with reason
        self._cache[key] = {
            "url": None,
            "ats": "Unknown",
            "status": "unresolved",
            "method": "none",
            "cached_at": time.time(),
            "reason": "no_ats_url_found",
        }
        self._save_cache()
        
        return BrowserResolvedUrl(
            url=None,
            ats="Unknown",
            status="unresolved",
            method="none"
        )
    
    def resolve_batch(self, jobs: list[dict], rate_limit: float = RATE_LIMIT_DELAY
                      ) -> list[tuple[dict, BrowserResolvedUrl]]:
        """Resolve URLs for a batch of jobs using browser.
        
        Args:
            jobs: List of job dicts with company, title, company_url, location
            rate_limit: Delay between requests in seconds
        
        Returns:
            List of (job, BrowserResolvedUrl) tuples
        """
        results = []
        try:
            for i, job in enumerate(jobs):
                if i > 0:
                    time.sleep(rate_limit)
                
                result = self.resolve_via_browser(
                    company=job.get("company", ""),
                    title=job.get("title", ""),
                    company_url=job.get("company_url", ""),
                    location=job.get("location"),
                )
                results.append((job, result))
                
                if (i + 1) % 5 == 0:
                    LOG.info("Browser resolved %d/%d jobs", i + 1, len(jobs))
        finally:
            self.close()
        
        return results
