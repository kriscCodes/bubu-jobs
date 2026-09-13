from pathlib import Path

RAW_URL = "https://raw.githubusercontent.com/jobright-ai/2026-Product-Management-New-Grad/master/README.md"
STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "seen_jobs.json"
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
# Phrases match whole words, ignoring case, punctuation and whitespace.
ACCEPTED_TITLE_KEYWORDS = (
    "associate product manager", "product manager", "junior product manager",
    "graduate product manager", "product analyst", "product operations",
    "product operation", "product strategy", "product management",
)
REJECTED_TITLE_KEYWORDS = (
    "product demonstrator", "senior", "sr", "principal", "lead", "leader",
    "director", "technician", "retail educator", "product development scientist",
    "staff", "vice president", "vp", "head of",
)
