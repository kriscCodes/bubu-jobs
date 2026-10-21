from pathlib import Path

RAW_URL = "https://raw.githubusercontent.com/jobright-ai/2026-Product-Management-New-Grad/master/README.md"
SIMPLIFY_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/"
    ".github/scripts/listings.json"
)
FYRF_URL = "https://findyourrolefirst.click/api/public/entry-level"
STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "seen_jobs.json"
TIMEOUT_SECONDS = 30
SIMPLIFY_TIMEOUT_SECONDS = 90
MAX_ATTEMPTS = 3

SOURCE_SIMPLIFY = "simplify"
SOURCE_FYRF = "findyourrolefirst"
SOURCE_JOBRIGHT = "jobright"
NEW_SOURCES = (SOURCE_SIMPLIFY, SOURCE_FYRF)
SOURCE_LABELS = {
    SOURCE_SIMPLIFY: "SimplifyJobs",
    SOURCE_FYRF: "FindYourRoleFirst",
    SOURCE_JOBRIGHT: "Jobright",
}

# Recency windows. First-run seeding is documented in docs/SETUP.md:
# brand-new sources mark listings older than FIRST_RUN_SEED_DAYS as seen
# without emailing, so the first deploy after adding a source cannot flood.
MAX_LISTING_AGE_DAYS = 14
FIRST_RUN_SEED_DAYS = 3

# Live posting checks (still-open + entry-level) for jobs about to be emailed.
POSTING_TIMEOUT_SECONDS = 12
POSTING_MAX_WORKERS = 3
ENTRY_LEVEL_MAX_REQUIRED_YEARS = 2  # drop when required/minimum years are 3+
PLAUSIBLE_EXPERIENCE_YEARS_MAX = 20

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
# "Senior Associate" is an entry-level title at Capital One, LSEG, Amex, etc.
# Strip these phrases before applying the senior/sr rejection terms.
SENIORITY_EXCEPTIONS = ("senior associate", "sr associate")
SENIORITY_REJECTS = frozenset({"senior", "sr"})
