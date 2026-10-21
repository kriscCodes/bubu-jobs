"""Deterministic entry-level classifier for job descriptions.

Drops a posting when required/minimum/basic qualifications ask for 3+ years,
or when the ATS tags the role Mid/Senior (not Senior Associate). Preferred /
nice-to-have years do not disqualify. Explicit early-career programs are kept
when they do not also require 3+ years.

An optional LLM classifier can be injected later behind a secret; none is
required, and none is called unless provided.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Protocol

from .config import ENTRY_LEVEL_MAX_REQUIRED_YEARS, PLAUSIBLE_EXPERIENCE_YEARS_MAX
from .posting_fetch import PostingSnapshot

LOG = logging.getLogger(__name__)

KEEP = "keep"
DROP = "drop"

YEAR_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20,
}

REQUIRED_HEADINGS = (
    "minimum qualifications", "minimum qualification",
    "basic qualifications", "basic qualification",
    "required qualifications", "required qualification",
    "required experience", "minimum requirements",
    "requirements", "what you'll bring", "what you will bring",
    "what you bring", "must have", "must-have",
)
PREFERRED_HEADINGS = (
    "preferred qualifications", "preferred qualification",
    "preferred experience", "nice to have", "nice-to-have",
    "desired qualifications", "bonus qualifications", "bonus",
    "preferred",
)
INLINE_HEADING_RE = re.compile(
    r"(?i)(minimum qualifications|basic qualifications|required qualifications|"
    r"preferred qualifications|nice to have|what you'll bring|what you will bring)\s*:"
)

YEAR_TOKEN = r"(?:\d{1,2}|" + "|".join(YEAR_WORDS) + r")"
YEARS_RE = re.compile(
    r"(?i)(?:(?:at\s+least|minimum(?:\s+of)?|min(?:imum)?|over|more\s+than)\s+)?"
    r"(?P<low>" + YEAR_TOKEN + r")"
    r"(?:(?:\s*[-–—]\s*|\s+to\s+)(?P<high>" + YEAR_TOKEN + r"))?"
    r"\s*\+?"
    r"(?:\s+or\s+more)?"
    r"\s*(?:years?|yrs?)"
    r"(?:\s+of)?(?:\s+(?:experience|exp\b|product|pm\b|in\b))?"
)

DROP_LEVEL_RE = re.compile(
    r"(?i)(?<![a-z])(?:mid(?:[\s-]?level)?|mid[\s-]?senior|senior|staff|principal|director|lead)(?![a-z])"
)
SENIOR_ASSOCIATE_RE = re.compile(r"(?i)senior\s+associate|sr\s+associate")
EARLY_CAREER_RE = re.compile(
    r"(?i)early[\s-]?career|new\s+grad(?:uate)?s?|graduate\s+(?:scheme|program|programme|role)|"
    r"rotation\s+program|associate\s+product\s+manager|\bapm\b|internships?\s+and\s+graduate|"
    r"graduate\s+schemes?\s+considered|university\s+grad"
)
LLM_KEY_NAMES = ("ENTRY_LEVEL_LLM_API_KEY", "OPENAI_API_KEY")


@dataclass(frozen=True)
class EntryLevelDecision:
    verdict: str
    reason: str
    required_years: int | None = None
    preferred_years: int | None = None
    seniority_tags: tuple[str, ...] = ()


class EntryLevelClassifier(Protocol):
    """Pluggable classifier. Rule-based by default; an LLM adapter may replace it."""

    def decide(self, snapshot: PostingSnapshot, title: str = "") -> EntryLevelDecision:
        ...


def llm_secret_configured() -> bool:
    return any(os.environ.get(name, "").strip() for name in LLM_KEY_NAMES)


def build_entry_level_classifier(
    llm: EntryLevelClassifier | None = None,
) -> EntryLevelClassifier:
    """Return the classifier to use. LLM is optional and unused unless injected."""
    if llm is not None:
        return llm
    if llm_secret_configured():
        LOG.info(
            "An LLM API key is set, but no LLM adapter was injected; "
            "using the rule-based entry-level classifier"
        )
    return RuleBasedEntryLevelClassifier()


def _parse_year(token: str | None) -> int | None:
    if not token:
        return None
    token = token.casefold().strip()
    if token.isdigit():
        value = int(token)
    else:
        value = YEAR_WORDS.get(token)
    if value is None:
        return None
    if value < 1 or value > PLAUSIBLE_EXPERIENCE_YEARS_MAX:
        return None
    return value


def _year_matches(text: str) -> list[re.Match[str]]:
    return list(YEARS_RE.finditer(text))


def _min_years_from_match(match: re.Match[str]) -> int | None:
    low = _parse_year(match.group("low"))
    high = _parse_year(match.group("high"))
    if low is None:
        return high
    return low


def _split_sections(text: str) -> tuple[str, str, str]:
    """Return (required, preferred, other) slices of the posting text."""
    if not text:
        return "", "", ""
    normalized = text.replace("\r\n", "\n")
    # Turn inline "Minimum qualifications:" into headings.
    normalized = INLINE_HEADING_RE.sub(lambda m: "\n" + m.group(1) + ":\n", normalized)
    lines = normalized.split("\n")
    required_parts: list[str] = []
    preferred_parts: list[str] = []
    other_parts: list[str] = []
    mode = "other"
    for line in lines:
        stripped = line.strip().strip(":").strip()
        key = re.sub(r"\s+", " ", stripped.casefold())
        if key in REQUIRED_HEADINGS:
            mode = "required"
            continue
        if key in PREFERRED_HEADINGS or key.rstrip(":") in PREFERRED_HEADINGS:
            mode = "preferred"
            continue
        if mode == "required":
            required_parts.append(line)
        elif mode == "preferred":
            preferred_parts.append(line)
        else:
            other_parts.append(line)
    return "\n".join(required_parts), "\n".join(preferred_parts), "\n".join(other_parts)


def _max_years(text: str) -> int | None:
    years = [value for value in (_min_years_from_match(match) for match in _year_matches(text)) if value is not None]
    return max(years) if years else None


def _nearby_is_preferred(text: str, match: re.Match[str], window: int = 90) -> bool:
    start = max(0, match.start() - window)
    prefix = text[start:match.start()].casefold()
    return bool(re.search(r"preferred|nice\s+to\s+have|nice-to-have|desired|bonus|plus\b", prefix))


_EXPERIENCE_CONTEXT_RE = re.compile(
    r"(?i)(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp\b|product|pm\b|in\b)"
)
_NON_QUAL_CONTEXT_RE = re.compile(
    r"(?i)\b(?:consent|privacy|cookie|gdpr|copyright|founded|history|anniversary)\b"
)


def _other_required_years(other: str) -> int | None:
    """When headings are missing, only count years tied to experience (not privacy copy)."""
    required: list[int] = []
    for match in _year_matches(other):
        if _nearby_is_preferred(other, match):
            continue
        snippet = other[max(0, match.start() - 40):match.end() + 40]
        if _NON_QUAL_CONTEXT_RE.search(snippet):
            continue
        if not _EXPERIENCE_CONTEXT_RE.search(match.group(0)) and not _EXPERIENCE_CONTEXT_RE.search(
            other[match.start():match.end() + 40]
        ):
            continue
        value = _min_years_from_match(match)
        if value is not None:
            required.append(value)
    return max(required) if required else None


def _drop_seniority_tags(tags: tuple[str, ...], title: str, text: str) -> str | None:
    haystack = " | ".join(tags)
    if SENIOR_ASSOCIATE_RE.search(haystack) or SENIOR_ASSOCIATE_RE.search(title):
        haystack = SENIOR_ASSOCIATE_RE.sub(" ", haystack)
    match = DROP_LEVEL_RE.search(haystack)
    if match:
        return match.group(0).lower()
    return None


class RuleBasedEntryLevelClassifier:
    def decide(self, snapshot: PostingSnapshot, title: str = "") -> EntryLevelDecision:
        text = snapshot.text or ""
        required_text, preferred_text, other_text = _split_sections(text)
        required_years = _max_years(required_text)
        preferred_years = _max_years(preferred_text)
        if required_years is None and not required_text.strip():
            required_years = _other_required_years(other_text)

        tags = snapshot.seniority_tags
        level = _drop_seniority_tags(tags, title, text)
        if level:
            return EntryLevelDecision(
                DROP, f"ATS seniority tagged {level}",
                required_years=required_years, preferred_years=preferred_years,
                seniority_tags=tags,
            )

        threshold = ENTRY_LEVEL_MAX_REQUIRED_YEARS
        if required_years is not None and required_years > threshold:
            return EntryLevelDecision(
                DROP, f"required qualifications ask for {required_years}+ years",
                required_years=required_years, preferred_years=preferred_years,
                seniority_tags=tags,
            )

        reason = "no 3+ year required-experience bar"
        combined = f"{title}\n{text}"
        if EARLY_CAREER_RE.search(combined):
            reason = "explicit early-career / new-grad / APM / rotation signal"
        return EntryLevelDecision(
            KEEP, reason,
            required_years=required_years, preferred_years=preferred_years,
            seniority_tags=tags,
        )


def classify_entry_level(
    snapshot: PostingSnapshot,
    title: str = "",
    classifier: EntryLevelClassifier | None = None,
) -> EntryLevelDecision:
    chosen = classifier or build_entry_level_classifier()
    return chosen.decide(snapshot, title=title)
