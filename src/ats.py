from urllib.parse import urlsplit

ATS_DOMAINS = {
    "Greenhouse": ("greenhouse.io",),
    "Workday": ("myworkdayjobs.com", "myworkdaysite.com"),
    "Lever": ("lever.co",),
    "Ashby": ("ashbyhq.com",),
    "iCIMS": ("icims.com",),
    "SmartRecruiters": ("smartrecruiters.com",),
}


def detect_ats(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for ats, domains in ATS_DOMAINS.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return ats
    return "Unknown"
