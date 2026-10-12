"""Browser-based resolver that visits Jobright pages to capture apply URLs.

This module uses Playwright to visit Jobright job pages and click "APPLY NOW"
to capture the destination apply URL. This requires Jobright authentication
because the apply URLs are hidden behind login.

Authentication Requirements:
---------------------------
Jobright hides actual apply URLs behind authentication. To use this resolver,
you need to provide credentials via environment variables:

    JOBRIGHT_EMAIL - Your Jobright account email
    JOBRIGHT_PASSWORD - Your Jobright account password

Without credentials, this resolver will document that login is required
but cannot capture apply URLs.

If Cloudflare challenges or CAPTCHA appear, manual intervention is required.
The resolver will save screenshots and document the blocker URL.

Usage:
    from src.jobright_browser import JobrightBrowserResolver
    resolver = JobrightBrowserResolver(cache_path)
    result = resolver.resolve_via_jobright(job_id, company, title)
"""
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

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

CACHE_TTL_SECONDS = 86400 * 7  # 7 days
RATE_LIMIT_DELAY = 2.0  # Seconds between requests


@dataclass(frozen=True)
class JobrightResolvedUrl:
    """Result of Jobright browser resolution."""
    url: str | None
    ats: str
    status: str  # "resolved", "login_required", "cloudflare_blocked", "error"
    method: str  # "browser_jobright_manual_apply", "none"
    blocker_details: str | None = None


def _detect_ats(url: str) -> str:
    """Detect ATS from URL domain."""
    host = (urlsplit(url).hostname or "").lower()
    for domain, ats in ATS_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return ats
    return "Company"


def _is_valid_apply_url(url: str) -> bool:
    """Check if URL is a valid apply destination (not a wrapper site)."""
    if not url or not url.startswith("http"):
        return False
    host = (urlsplit(url).hostname or "").lower()
    wrapper_domains = ["jobright.ai", "linkedin.com", "indeed.com", "glassdoor.com"]
    for d in wrapper_domains:
        if host == d or host.endswith("." + d):
            return False
    return True


class JobrightBrowserResolver:
    """Browser-based resolver that visits Jobright pages to capture apply URLs.
    
    Requires Jobright authentication to access apply URLs. Without credentials,
    documents the login requirement but cannot resolve URLs.
    """
    
    def __init__(self, cache_path: Path | None = None):
        self.cache_path = cache_path
        self._cache: dict[str, dict] = {}
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False
        self._load_cache()
        
        # Check for credentials
        self.email = os.environ.get("JOBRIGHT_EMAIL", "")
        self.password = os.environ.get("JOBRIGHT_PASSWORD", "")
        self.has_credentials = bool(self.email and self.password)
    
    def _load_cache(self) -> None:
        if self.cache_path and self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("version") == 1:
                    self._cache = data.get("jobright_browser_entries", {})
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
            
            existing["jobright_browser_entries"] = self._cache
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except OSError as e:
            LOG.warning("Failed to save Jobright browser cache: %s", e)
    
    def _cache_key(self, job_id: str) -> str:
        """Generate cache key from job ID."""
        return f"jobright_{job_id}"
    
    def _is_cache_valid(self, entry: dict) -> bool:
        """Check if cache entry is still valid."""
        cached_at = entry.get("cached_at", 0)
        return time.time() - cached_at < CACHE_TTL_SECONDS
    
    def _ensure_browser(self):
        """Ensure browser is initialized."""
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
                self._context = self._browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    viewport={"width": 1920, "height": 1080},
                )
                self._page = self._context.new_page()
            except ImportError:
                raise RuntimeError(
                    "Playwright not installed. Run: pip install playwright && playwright install chromium"
                )
    
    def close(self):
        """Close browser resources."""
        if self._browser:
            self._browser.close()
            self._playwright.stop()
            self._browser = None
            self._page = None
            self._logged_in = False
    
    def _check_cloudflare(self, page) -> bool:
        """Check if Cloudflare challenge is present."""
        content = page.content().lower()
        return "cloudflare" in content and ("challenge" in content or "captcha" in content)
    
    def _check_login_required(self, page) -> bool:
        """Check if login is required to proceed."""
        content = page.content().lower()
        url = page.url.lower()
        return (
            "sign in" in content or 
            "log in" in content or 
            "/login" in url or
            "/signin" in url
        )
    
    def _login(self) -> bool:
        """Attempt to log into Jobright."""
        if not self.has_credentials:
            LOG.warning("No Jobright credentials available")
            return False
        
        if self._logged_in:
            return True
        
        try:
            self._ensure_browser()
            LOG.info("Attempting Jobright login...")
            
            self._page.goto("https://jobright.ai/login", wait_until="networkidle", timeout=30000)
            time.sleep(2)
            
            # Check for Cloudflare
            if self._check_cloudflare(self._page):
                LOG.warning("Cloudflare challenge on login page")
                self._page.screenshot(path="/tmp/jobright_cloudflare_login.png")
                return False
            
            # Find and fill email
            email_input = self._page.locator('input[type="email"], input[name="email"]').first
            if email_input.is_visible():
                email_input.fill(self.email)
            
            # Find and fill password
            password_input = self._page.locator('input[type="password"]').first
            if password_input.is_visible():
                password_input.fill(self.password)
            
            # Click login button
            login_btn = self._page.locator('button[type="submit"], button:has-text("Sign in"), button:has-text("Log in")').first
            if login_btn.is_visible():
                login_btn.click()
                time.sleep(3)
            
            # Check if login successful
            if "/login" not in self._page.url.lower() and "/signin" not in self._page.url.lower():
                self._logged_in = True
                LOG.info("Jobright login successful")
                return True
            else:
                LOG.warning("Jobright login may have failed")
                self._page.screenshot(path="/tmp/jobright_login_failed.png")
                return False
                
        except Exception as e:
            LOG.error("Jobright login error: %s", e)
            return False
    
    def _capture_apply_url(self, job_id: str) -> JobrightResolvedUrl:
        """Visit Jobright job page and capture apply URL."""
        job_url = f"https://jobright.ai/jobs/info/{job_id}"
        
        try:
            self._ensure_browser()
            
            LOG.debug("Visiting Jobright job: %s", job_url)
            self._page.goto(job_url, wait_until="networkidle", timeout=30000)
            time.sleep(2)
            
            # Check for Cloudflare
            if self._check_cloudflare(self._page):
                self._page.screenshot(path=f"/tmp/jobright_cloudflare_{job_id}.png")
                return JobrightResolvedUrl(
                    url=None,
                    ats="Unknown",
                    status="cloudflare_blocked",
                    method="none",
                    blocker_details=f"Cloudflare challenge at {job_url}. Screenshot: /tmp/jobright_cloudflare_{job_id}.png"
                )
            
            # Find APPLY NOW button
            apply_btn = self._page.locator('button').filter(has_text='APPLY NOW').first
            
            if not apply_btn.is_visible():
                apply_btn = self._page.locator('button, a').filter(has_text='Apply').first
            
            if not apply_btn.is_visible():
                return JobrightResolvedUrl(
                    url=None,
                    ats="Unknown",
                    status="error",
                    method="none",
                    blocker_details="No apply button found on page"
                )
            
            # Try to click and capture destination
            captured_url = None
            
            # Set up popup handler
            popup_url = None
            def on_popup(popup):
                nonlocal popup_url
                try:
                    popup.wait_for_load_state("domcontentloaded", timeout=10000)
                    popup_url = popup.url
                except:
                    pass
            
            self._context.on("page", on_popup)
            
            # Click apply button
            apply_btn.click()
            time.sleep(3)
            
            # Check if popup opened with apply URL
            if popup_url and _is_valid_apply_url(popup_url):
                captured_url = popup_url
            
            # Check if login prompt appeared (for users without login)
            if not captured_url and self._check_login_required(self._page):
                if not self._logged_in and not self.has_credentials:
                    self._page.screenshot(path=f"/tmp/jobright_login_required_{job_id}.png")
                    return JobrightResolvedUrl(
                        url=None,
                        ats="Unknown",
                        status="login_required",
                        method="none",
                        blocker_details=(
                            f"Jobright requires login to access apply URL. "
                            f"Set JOBRIGHT_EMAIL and JOBRIGHT_PASSWORD environment variables. "
                            f"Screenshot: /tmp/jobright_login_required_{job_id}.png"
                        )
                    )
                elif self.has_credentials and not self._logged_in:
                    # Try to log in and retry
                    if self._login():
                        return self._capture_apply_url(job_id)
                    else:
                        return JobrightResolvedUrl(
                            url=None,
                            ats="Unknown",
                            status="login_required",
                            method="none",
                            blocker_details="Jobright login failed. Check credentials."
                        )
            
            if captured_url:
                ats = _detect_ats(captured_url)
                return JobrightResolvedUrl(
                    url=captured_url,
                    ats=ats,
                    status="resolved",
                    method="browser_jobright_manual_apply"
                )
            
            return JobrightResolvedUrl(
                url=None,
                ats="Unknown",
                status="error",
                method="none",
                blocker_details="Could not capture apply URL after clicking button"
            )
            
        except Exception as e:
            LOG.error("Error capturing apply URL for %s: %s", job_id, e)
            return JobrightResolvedUrl(
                url=None,
                ats="Unknown",
                status="error",
                method="none",
                blocker_details=f"Error: {str(e)}"
            )
    
    def resolve_via_jobright(self, job_id: str, company: str, title: str
                             ) -> JobrightResolvedUrl:
        """Resolve a job's apply URL by visiting its Jobright page.
        
        Args:
            job_id: Jobright job ID (from URL path)
            company: Company name (for logging)
            title: Job title (for logging)
        
        Returns:
            JobrightResolvedUrl with the result
        """
        key = self._cache_key(job_id)
        
        # Check cache
        if key in self._cache and self._is_cache_valid(self._cache[key]):
            entry = self._cache[key]
            LOG.debug("Cache hit for Jobright job %s", job_id)
            return JobrightResolvedUrl(
                url=entry.get("url"),
                ats=entry.get("ats", "Unknown"),
                status=entry.get("status", "unresolved"),
                method="cache",
                blocker_details=entry.get("blocker_details")
            )
        
        LOG.info("Resolving via Jobright browser: %s - %s", company, title)
        
        result = self._capture_apply_url(job_id)
        
        # Cache the result
        self._cache[key] = {
            "url": result.url,
            "ats": result.ats,
            "status": result.status,
            "method": result.method,
            "blocker_details": result.blocker_details,
            "cached_at": time.time(),
            "company": company,
            "title": title,
        }
        self._save_cache()
        
        return result
    
    def resolve_batch(self, jobs: list[dict], rate_limit: float = RATE_LIMIT_DELAY
                      ) -> list[tuple[dict, JobrightResolvedUrl]]:
        """Resolve URLs for a batch of jobs by visiting Jobright pages.
        
        Args:
            jobs: List of job dicts with job_id, company, title
            rate_limit: Delay between requests in seconds
        
        Returns:
            List of (job, JobrightResolvedUrl) tuples
        """
        results = []
        
        # Check credentials first
        if not self.has_credentials:
            LOG.warning(
                "No Jobright credentials found. Set JOBRIGHT_EMAIL and JOBRIGHT_PASSWORD "
                "environment variables to resolve apply URLs."
            )
        
        try:
            for i, job in enumerate(jobs):
                if i > 0:
                    time.sleep(rate_limit)
                
                result = self.resolve_via_jobright(
                    job_id=job.get("job_id", ""),
                    company=job.get("company", ""),
                    title=job.get("title", ""),
                )
                results.append((job, result))
                
                if result.status == "login_required" and not self.has_credentials:
                    LOG.info("Login required and no credentials available. Stopping batch.")
                    # Mark remaining as login_required
                    for remaining_job in jobs[i+1:]:
                        results.append((remaining_job, JobrightResolvedUrl(
                            url=None,
                            ats="Unknown",
                            status="login_required",
                            method="none",
                            blocker_details="Skipped - login required"
                        )))
                    break
                
                if (i + 1) % 5 == 0:
                    LOG.info("Resolved %d/%d Jobright jobs", i + 1, len(jobs))
        
        finally:
            self.close()
        
        return results


def extract_job_id(jobright_url: str) -> str | None:
    """Extract job ID from a Jobright URL.
    
    Args:
        jobright_url: URL like https://jobright.ai/jobs/info/6aa02a5ba2266b538d22e7ca
    
    Returns:
        Job ID string or None if not found
    """
    match = re.search(r'/jobs/info/([a-f0-9]+)', jobright_url)
    return match.group(1) if match else None
