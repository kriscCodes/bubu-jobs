import re
import unicodedata
from .config import ACCEPTED_TITLE_KEYWORDS, REJECTED_TITLE_KEYWORDS


def words(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def is_relevant(title: str, accepted: tuple[str, ...] = ACCEPTED_TITLE_KEYWORDS,
                rejected: tuple[str, ...] = REJECTED_TITLE_KEYWORDS) -> bool:
    normalized = " " + words(title) + " "
    def contains(phrase: str) -> bool:
        return " " + words(phrase) + " " in normalized
    return not any(map(contains, rejected)) and any(map(contains, accepted))
