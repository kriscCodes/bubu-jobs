import re
import unicodedata

from .config import (
    ACCEPTED_TITLE_KEYWORDS,
    REJECTED_TITLE_KEYWORDS,
    SENIORITY_EXCEPTIONS,
    SENIORITY_REJECTS,
)

US_STATE_ABBREVS = frozenset({
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo",
    "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa",
    "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "pr",
})
US_STATE_NAMES = frozenset({
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia", "puerto rico",
})
US_CITY_ALIASES = frozenset({
    "nyc", "n.y.c", "sf", "la", "dc", "d.c", "new york city",
})
# Two-letter tokens that are USPS codes AND common English words / non-US codes.
AMBIGUOUS_STATE_ABBREVS = frozenset({"in", "or", "me", "ok", "hi", "id", "la"})


def words(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def is_relevant(title: str, accepted: tuple[str, ...] = ACCEPTED_TITLE_KEYWORDS,
                rejected: tuple[str, ...] = REJECTED_TITLE_KEYWORDS) -> bool:
    normalized = " " + words(title) + " "
    seniority_haystack = normalized
    for exception in SENIORITY_EXCEPTIONS:
        seniority_haystack = seniority_haystack.replace(" " + words(exception) + " ", " ")

    def contains(phrase: str, haystack: str = normalized) -> bool:
        return " " + words(phrase) + " " in haystack

    for phrase in rejected:
        haystack = seniority_haystack if words(phrase) in SENIORITY_REJECTS else normalized
        if contains(phrase, haystack):
            return False
    return any(contains(phrase) for phrase in accepted)


def _has_explicit_us(low: str) -> bool:
    if re.search(r"\bunited states\b", low) or re.search(r"\busa\b", low):
        return True
    if re.search(r"\bu\.s\.a?\.?\b", low):
        return True
    if re.search(r"\bremote(?:\s+in|\s*[-–])?\s*us\b", low):
        return True
    if re.search(r"(?:^|[\s,;/(])us(?:$|[\s,;)/])", low):
        return True
    return False


def is_us_location(location: str) -> bool:
    """True when a single location string is in the United States."""
    text = (location or "").strip()
    if not text:
        return False
    low = text.casefold()
    if _has_explicit_us(low):
        return True
    compact = re.sub(r"[^a-z]+", " ", low).strip()
    if compact in US_CITY_ALIASES or low in US_CITY_ALIASES:
        return True
    for name in US_STATE_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", low):
            return True
    for match in re.finditer(r"(?:^|[,/;|\s])\s*([A-Za-z]{2})\b", text):
        token = match.group(1)
        abbrev = token.casefold()
        if abbrev not in US_STATE_ABBREVS:
            continue
        comma_before = bool(re.search(r",\s*$", text[:match.start(1)]))
        if abbrev in AMBIGUOUS_STATE_ABBREVS and not (token.isupper() or comma_before):
            continue
        if token.isupper() or comma_before or abbrev not in AMBIGUOUS_STATE_ABBREVS:
            return True
    return False


def has_us_location(locations: list[str] | str | None) -> bool:
    """True when at least one location is in the United States."""
    if not locations:
        return False
    items = [locations] if isinstance(locations, str) else [str(item) for item in locations]
    return any(is_us_location(item) for item in items)
