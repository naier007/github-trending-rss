"""Fetch trending GitHub repositories.

Primary source : github.com/trending HTML page (stdlib-only scraper)
                 https://github.com/trending?since=daily
                 Matches the "daily trending" semantics (sorted by stars
                 gained within the time window) that the Search API cannot
                 reproduce, and needs no token / no API rate limit.
Fallback source: GitHub Search API
                 https://docs.github.com/en/rest/search/search#search-repositories
                 Repositories created within the last N days, sorted by stars.
                 Used only when the trending page fails or yields 0 items.

Only the Python 3.8+ standard library is required (no third-party packages).
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import __version__

API_BASE = "https://api.github.com"
SEARCH_URL = API_BASE + "/search/repositories"
TRENDING_URL = "https://github.com/trending"
USER_AGENT = f"github-trending-rss/{__version__}"

SEARCH_ACCEPT = "application/vnd.github+json"
README_ACCEPT = "application/vnd.github.raw+json"

MAX_RETRIES = 3             # per-request retries for transient failures
BASE_BACKOFF = 2.0          # seconds, doubled on each retry
MAX_BACKOFF = 30.0          # seconds
MAX_RATE_LIMIT_WAIT = 60.0  # never wait longer than this for a rate limit
REQUEST_TIMEOUT = 30        # seconds
README_MAX_CHARS = 300      # chars of README text kept per item
SEARCH_MAX_LIMIT = 100      # GitHub Search API per_page cap


class GitHubError(Exception):
    """Base class for GitHub access errors."""


class RateLimitError(GitHubError):
    """GitHub API rate limit hit and no bounded wait is possible."""


class FetchError(GitHubError):
    """Every configured source failed."""


@dataclass
class Repo:
    """A repository as needed by the RSS generator."""

    full_name: str
    url: str
    description: str = ""
    summary: str = ""
    stars: int = 0
    forks: int = 0
    stars_today: int = 0  # stars gained in the trending window (trending page)
    language: Optional[str] = None
    created_at: str = ""  # ISO-8601 from the API
    topics: List[str] = field(default_factory=list)
    license: Optional[str] = None
    source: str = "unknown"


def _rate_limit_wait(retry_after: Optional[str], reset: Optional[str]) -> Optional[float]:
    """Seconds to wait before retrying, or None when unknown / unbounded."""
    now = time.time()
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    if reset:
        try:
            return max(0.0, float(reset) - now)
        except ValueError:
            pass
    return None


def _request_json(url: str, token: Optional[str] = None, accept: str = SEARCH_ACCEPT,
                  timeout: int = REQUEST_TIMEOUT):
    """GET *url* and return parsed JSON, or the raw body when it is not JSON
    (e.g. README text / HTML). Retries transient failures and waits out API
    rate limits up to MAX_RATE_LIMIT_WAIT. Raises GitHubError on failure."""
    headers = {
        "Accept": accept,
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body) if body.strip() else None
            except json.JSONDecodeError:
                return body
        except HTTPError as exc:
            last_error = exc
            status = exc.code
            body = exc.read().decode("utf-8", errors="replace")
            resp_headers = exc.headers or {}
            remaining = resp_headers.get("X-RateLimit-Remaining")
            reset = resp_headers.get("X-RateLimit-Reset")
            retry_after = resp_headers.get("Retry-After")

            # Bad / expired token: retry once without credentials (degraded mode).
            if status == 401 and token:
                token = None
                continue

            # API rate limit: wait when a bounded wait is possible.
            if status == 403 and (remaining == "0" or "rate limit" in body.lower()):
                wait = _rate_limit_wait(retry_after, reset)
                if wait is not None and wait <= MAX_RATE_LIMIT_WAIT:
                    time.sleep(wait)
                    continue
                raise RateLimitError(
                    f"GitHub API rate limit exceeded for {url} "
                    f"(X-RateLimit-Reset={reset}, Retry-After={retry_after})"
                ) from exc

            if status == 404:
                raise GitHubError(f"HTTP 404 not found: {url}") from exc

            # 429 / 5xx: retry with exponential backoff.
            if status == 429 or status >= 500:
                wait = _rate_limit_wait(retry_after, None)
                time.sleep(wait if wait is not None
                           else min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF))
                continue

            raise GitHubError(f"HTTP {status} for {url}: {body[:300]}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF))
            continue

    raise GitHubError(
        f"request to {url} failed after {MAX_RETRIES + 1} attempts: {last_error}"
    )


def _clean_description(text: str) -> str:
    """Strip markdown/HTML noise from a short repository description."""
    line = re.sub(r"<[^>]+>", " ", text or "")                      # HTML tags
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)                 # images ![..](..)
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)             # links [t](u) -> t
    line = re.sub(r"[*_`#~]", " ", line)                             # markdown noise
    return re.sub(r"\s+", " ", line).strip()


def _fetch_from_search_api(language: Optional[str], days: int, limit: int,
                           token: Optional[str], sort: str) -> List[Repo]:
    """Query the GitHub Search API: repositories created within the last
    *days* days, sorted by *sort* (stars|forks|updated) descending."""
    since = (date.today() - timedelta(days=days)).isoformat()
    query = f"created:>={since}"
    if language:
        query += f" language:{language}"
    url = (f"{SEARCH_URL}?q={quote(query, safe='')}&sort={quote(sort, safe='')}"
           f"&order=desc&per_page={min(limit, SEARCH_MAX_LIMIT)}")
    data = _request_json(url, token=token)
    if not isinstance(data, dict) or "items" not in data:
        raise GitHubError(f"unexpected response from search API for {url}")
    repos: List[Repo] = []
    for item in data.get("items", [])[:limit]:
        license_obj = item.get("license") or {}
        desc = _clean_description(item.get("description"))
        repos.append(Repo(
            full_name=item.get("full_name") or "",
            url=item.get("html_url") or "",
            description=desc,
            summary=desc,
            stars=item.get("stargazers_count") or 0,
            forks=item.get("forks_count") or 0,
            language=item.get("language"),
            created_at=item.get("created_at") or "",
            topics=list(item.get("topics") or []),
            license=license_obj.get("spdx_id"),
            source="search-api",
        ))
    return repos


def _summarize_readme(text: str, max_chars: int) -> str:
    """Extract a short plain-text summary from raw markdown README content."""
    paragraphs: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("```") or line.startswith("!["):
            continue
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)  # [text](url) -> text
        line = re.sub(r"<(https?://[^>]+)>", r"\1", line)      # <url> -> url
        line = re.sub(r"[*_`>#|~-]", " ", line)                # markdown noise
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            paragraphs.append(line)
    parts: List[str] = []
    total = 0
    for para in paragraphs[:6]:
        if total and total + len(para) + 1 > max_chars:
            break
        parts.append(para)
        total += len(para) + 1
    summary = " ".join(parts).strip()
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip() + "…"
    return summary


def fetch_readme_summary(full_name: str, token: Optional[str] = None,
                         max_chars: int = README_MAX_CHARS,
                         timeout: int = REQUEST_TIMEOUT) -> str:
    """Fetch and summarize a repository's README. Never raises; returns an
    empty string when the README cannot be fetched or has no useful text."""
    if not full_name or "/" not in full_name:
        return ""
    url = f"{API_BASE}/repos/{quote(full_name, safe='/')}/readme"
    try:
        content = _request_json(url, token=token, accept=README_ACCEPT, timeout=timeout)
    except GitHubError:
        return ""
    if not isinstance(content, str):
        return ""
    return _summarize_readme(content, max_chars)


def enrich_readme_summaries(repos: List[Repo], token: Optional[str] = None,
                            max_chars: int = README_MAX_CHARS,
                            max_workers: int = 8) -> List[Repo]:
    """Fill each repo's *summary* from its README (concurrently), falling back
    to the repository description when the README is unavailable."""
    if not repos:
        return repos
    workers = min(max_workers, max(1, len(repos)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(fetch_readme_summary, r.full_name, token, max_chars)
            for r in repos
        ]
        for repo, fut in zip(repos, futures):
            repo.summary = (fut.result() or "") or repo.description
    return repos


class _TrendingParser(HTMLParser):
    """Minimal stdlib scraper for github.com/trending <article class="Box-row">."""

    def __init__(self) -> None:
        super().__init__()
        self.repos: List[dict] = []
        self._in_article = False
        self._in_h2 = False
        self._in_desc_p = False
        self._desc_done = False
        self._in_stars_a = False
        self._in_forks_a = False
        self._in_today_span = False
        self._in_lang_span = False
        self._count_buf: List[str] = []
        self._lang_buf: List[str] = []
        self._current: Optional[dict] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "article" and "Box-row" in classes:
            self._in_article = True
            self._desc_done = False
            self._current = {"name": "", "desc": "", "stars": "", "forks": "",
                             "today": "", "language": ""}
        elif self._in_article and self._current is not None:
            if tag == "h2":
                self._in_h2 = True
            elif tag == "p" and not self._desc_done:
                self._in_desc_p = True
            elif tag == "a":
                href = attrs.get("href") or ""
                if href.endswith("/stargazers"):
                    self._in_stars_a = True
                    self._count_buf = []
                elif href.endswith("/forks"):
                    self._in_forks_a = True
                    self._count_buf = []
            elif tag == "span":
                if "float-sm-right" in classes:
                    self._in_today_span = True
                    self._count_buf = []
                elif attrs.get("itemprop") == "programmingLanguage":
                    self._in_lang_span = True
                    self._lang_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self._in_article:
            if self._current and self._current["name"]:
                self.repos.append(self._current)
            self._in_article = False
            self._current = None
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "p" and self._in_desc_p:
            self._in_desc_p = False
            self._desc_done = True
        elif tag == "a" and self._in_stars_a and self._current is not None:
            self._current["stars"] = "".join(self._count_buf)
            self._in_stars_a = False
        elif tag == "a" and self._in_forks_a and self._current is not None:
            self._current["forks"] = "".join(self._count_buf)
            self._in_forks_a = False
        elif tag == "span" and self._in_today_span and self._current is not None:
            self._current["today"] = "".join(self._count_buf)
            self._in_today_span = False
        elif tag == "span" and self._in_lang_span and self._current is not None:
            self._current["language"] = "".join(self._lang_buf).strip()
            self._in_lang_span = False

    def handle_data(self, data: str) -> None:
        if self._in_h2 and self._current is not None:
            self._current["name"] += data
        elif self._in_desc_p and self._current is not None:
            self._current["desc"] += data
        elif self._in_lang_span:
            self._lang_buf.append(data)
        elif (self._in_stars_a or self._in_forks_a or self._in_today_span) \
                and self._current is not None:
            self._count_buf.append(data)


def _parse_count(text: str) -> int:
    """Parse a GitHub count like '34.2k', '1.2m', '1,234' or '123' -> int."""
    s = re.sub(r"[^0-9.kKmMbB]", "", text or "").strip().lower()
    if not s:
        return 0
    multiplier = 1
    if s.endswith("k"):
        multiplier, s = 1000, s[:-1]
    elif s.endswith("m"):
        multiplier, s = 1_000_000, s[:-1]
    elif s.endswith("b"):
        multiplier, s = 1_000_000_000, s[:-1]
    try:
        return int(float(s) * multiplier)
    except ValueError:
        return 0


def _parse_today_count(text: str) -> int:
    """Parse '2,304 stars today' / '120 stars this week' -> int (0 when absent)."""
    m = re.search(r"([\d,.]+)\s*stars?\s+(?:today|this\s+\w+)", text or "", re.IGNORECASE)
    if not m:
        return 0
    return _parse_count(m.group(1))


def _fetch_from_trending_page(language: Optional[str], limit: int,
                              since: str = "daily") -> List[Repo]:
    """Scrape the github.com/trending page as the primary source.

    *since* is the trending window: daily | weekly | monthly.
    """
    url = TRENDING_URL
    if language:
        url += f"/{quote(language, safe='')}"
    url += f"?since={quote(since, safe='')}"
    html = _request_json(url, accept="text/html")
    if not isinstance(html, str):
        raise GitHubError(f"unexpected response from trending page {url}")
    parser = _TrendingParser()
    try:
        parser.feed(html)
    except Exception as exc:  # malformed HTML must never crash the primary source
        raise GitHubError(f"failed to parse trending page {url}: {exc}") from exc

    repos: List[Repo] = []
    for entry in parser.repos[:limit]:
        name = re.sub(r"\s+", "", entry["name"])
        parts = [p for p in name.split("/") if p]
        if len(parts) < 2:
            continue
        full_name = "/".join(parts[-2:])
        desc = re.sub(r"\s+", " ", entry["desc"]).strip()
        repos.append(Repo(
            full_name=full_name,
            url=f"https://github.com/{full_name}",
            description=desc,
            summary=desc,
            stars=_parse_count(entry["stars"]),
            forks=_parse_count(entry["forks"]),
            stars_today=_parse_today_count(entry["today"]),
            language=entry["language"].strip() or None,
            source="trending-page",
        ))
    return repos


def fetch_trending_repos(language: Optional[str] = None, days: int = 7, limit: int = 30,
                         token: Optional[str] = None, sort: str = "stars",
                         use_fallback: bool = True, since: str = "daily") -> List[Repo]:
    """Return up to *limit* trending repositories.

    Primary source : the github.com/trending page (window *since*), matching
                     the "trending" semantics (stars gained in the window).
    Fallback source: GitHub Search API (repositories created within the last
                     *days* days, sorted by *sort*) — used only when the
                     trending page fails or returns 0 items, and enabled via
                     *use_fallback*. Raises FetchError when every source fails.
    """
    errors: List[str] = []
    try:
        repos = _fetch_from_trending_page(language, limit, since)
        if repos:
            return repos
        errors.append("trending page returned 0 repositories")
    except GitHubError as exc:
        errors.append(f"trending page failed: {exc}")

    if use_fallback:
        try:
            return _fetch_from_search_api(language, days, limit, token, sort)
        except RateLimitError as exc:
            errors.append(f"search api rate limited: {exc}")
        except GitHubError as exc:
            errors.append(f"search api failed: {exc}")

    raise FetchError("; ".join(errors) if errors else "no repositories returned by any source")
