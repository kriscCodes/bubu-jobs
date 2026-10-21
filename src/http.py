"""HTTP helpers with retries and conditional GET (ETag / If-Modified-Since)."""
import logging
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import MAX_ATTEMPTS, TIMEOUT_SECONDS

LOG = logging.getLogger(__name__)
USER_AGENT = "bubu-jobs/1.0"


@dataclass(frozen=True)
class FetchResult:
    text: str | None
    etag: str | None
    last_modified: str | None = None


def conditional_get(
    url: str,
    etag: str | None = None,
    last_modified: str | None = None,
    accept: str = "*/*",
    timeout: int = TIMEOUT_SECONDS,
) -> FetchResult:
    """GET with If-None-Match / If-Modified-Since. HTTP 304 returns text=None."""
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urlopen(Request(url, headers=headers), timeout=timeout) as response:
                return FetchResult(
                    response.read().decode("utf-8"),
                    response.headers.get("ETag"),
                    response.headers.get("Last-Modified"),
                )
        except HTTPError as error:
            if error.code == 304:
                if not etag and not last_modified:
                    raise ValueError("Unexpected 304 without a cached validator") from error
                return FetchResult(None, etag, last_modified)
            if error.code not in {429, 500, 502, 503, 504} or attempt == MAX_ATTEMPTS - 1:
                raise
            retry_after = error.headers.get("Retry-After", "")
            delay = min(int(retry_after), 60) if retry_after.isdigit() else 2 ** attempt
        except (URLError, TimeoutError, ConnectionError):
            if attempt == MAX_ATTEMPTS - 1:
                raise
            delay = 2 ** attempt
        LOG.warning("Request to %s failed; retrying in %s seconds", url, delay)
        time.sleep(delay)
    raise RuntimeError("Unreachable retry state")
