from urllib.parse import urlsplit, parse_qs

ATS_DOMAINS = {
    "Greenhouse": ("greenhouse.io",),
    "Workday": ("myworkdayjobs.com", "myworkdaysite.com"),
    "Lever": ("lever.co",),
    "Ashby": ("ashbyhq.com",),
    "iCIMS": ("icims.com",),
    "SmartRecruiters": ("smartrecruiters.com",),
}

# Query parameters that indicate a specific ATS (for custom domains)
ATS_PARAMS = {
    "gh_jid": "Greenhouse",  # Greenhouse job ID parameter
}


def detect_ats(url: str) -> str:
    """Detect the ATS platform from a URL.
    
    Checks both domain-based detection and query parameter patterns
    for custom-domain integrations.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    
    # First check domain-based detection
    for ats, domains in ATS_DOMAINS.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return ats
    
    # Check query parameters for custom domain integrations
    query = parse_qs(parts.query)
    for param, ats in ATS_PARAMS.items():
        if param in query:
            return ats
    
    return "Unknown"
