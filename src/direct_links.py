"""Direct apply link lookup for jobs.

This module loads manually verified direct apply links and provides lookup
functionality to find the best matching link for a job by company, title,
and location.
"""
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger(__name__)

DEFAULT_LINKS_PATH = Path(__file__).parent.parent / "data" / "direct_apply_links.json"


@dataclass(frozen=True)
class DirectLink:
    """A verified direct apply link."""
    company: str
    title: str
    location: str
    direct_url: str
    jobright_url: str
    status: str
    note: str


def _normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def _normalize_company(company: str) -> str:
    """Normalize company name for matching."""
    company = _normalize_text(company)
    company = re.sub(r"\s*(inc|llc|corp|corporation|ltd|co|holdings?|group|company)\s*$", "", company)
    return company.strip()


def _title_similarity(t1: str, t2: str) -> float:
    """Calculate word overlap similarity between titles."""
    words1 = set(_normalize_text(t1).split())
    words2 = set(_normalize_text(t2).split())
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


def _location_match_score(loc1: str, loc2: str) -> float:
    """Score location match (0.0 to 1.0)."""
    l1 = _normalize_text(loc1)
    l2 = _normalize_text(loc2)
    
    if l1 == l2:
        return 1.0
    
    if l1 in l2 or l2 in l1:
        return 0.8
    
    words1 = set(l1.split())
    words2 = set(l2.split())
    if words1 & words2:
        return len(words1 & words2) / len(words1 | words2)
    
    return 0.0


class DirectLinkLookup:
    """Lookup service for direct apply links."""
    
    def __init__(self, links_path: Path | None = None):
        self.links_path = links_path or DEFAULT_LINKS_PATH
        self._links: list[DirectLink] = []
        self._index: dict[str, list[DirectLink]] = {}
        self._load_links()
    
    def _load_links(self) -> None:
        """Load links from JSON file."""
        if not self.links_path.exists():
            LOG.warning("Direct links file not found: %s", self.links_path)
            return
        
        try:
            data = json.loads(self.links_path.read_text(encoding="utf-8"))
            
            for entry in data:
                if entry.get("status") != "resolved":
                    continue
                if not entry.get("direct_url"):
                    continue
                
                link = DirectLink(
                    company=entry.get("company", ""),
                    title=entry.get("title", ""),
                    location=entry.get("location", ""),
                    direct_url=entry.get("direct_url", ""),
                    jobright_url=entry.get("jobright", ""),
                    status=entry.get("status", ""),
                    note=entry.get("note", ""),
                )
                self._links.append(link)
                
                key = _normalize_company(link.company)
                if key not in self._index:
                    self._index[key] = []
                self._index[key].append(link)
            
            LOG.info("Loaded %d direct links from %s", len(self._links), self.links_path)
            
        except (json.JSONDecodeError, OSError) as e:
            LOG.error("Failed to load direct links: %s", e)
    
    def lookup(self, company: str, title: str, location: str = ""
               ) -> DirectLink | None:
        """Find the best matching direct link for a job.
        
        Args:
            company: Company name
            title: Job title
            location: Job location (used as tiebreaker)
        
        Returns:
            DirectLink if found, None otherwise
        """
        if not self._links:
            return None
        
        key = _normalize_company(company)
        candidates = self._index.get(key, [])
        
        if not candidates:
            return None
        
        best_match = None
        best_score = 0.0
        
        for link in candidates:
            title_score = _title_similarity(title, link.title)
            
            if title_score < 0.5:
                continue
            
            location_score = _location_match_score(location, link.location) if location else 0.5
            combined_score = title_score * 0.7 + location_score * 0.3
            
            if combined_score > best_score:
                best_score = combined_score
                best_match = link
        
        if best_match and best_score >= 0.5:
            LOG.debug("Found direct link for %s - %s (score: %.2f)", company, title, best_score)
            return best_match
        
        return None
    
    def get_all_links(self) -> list[DirectLink]:
        """Get all loaded direct links."""
        return list(self._links)
    
    def get_link_count(self) -> int:
        """Get number of loaded links."""
        return len(self._links)


_default_lookup: DirectLinkLookup | None = None


def get_direct_link(company: str, title: str, location: str = "") -> DirectLink | None:
    """Get direct link for a job using the default lookup.
    
    Args:
        company: Company name
        title: Job title  
        location: Job location (used as tiebreaker)
    
    Returns:
        DirectLink if found, None otherwise
    """
    global _default_lookup
    if _default_lookup is None:
        _default_lookup = DirectLinkLookup()
    
    try:
        return _default_lookup.lookup(company, title, location)
    except Exception as e:
        LOG.warning("Direct link lookup failed: %s", e)
        return None
