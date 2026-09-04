"""Find a site's real feed address.

Feed URLs are the most fragile part of this framework: they are undocumented on
most Korean community sites and they move when a site is redesigned. Guessing
them from memory produces configurations that look right and silently collect
nothing.

So the framework does not guess. `comradar discover <게시판 주소>` asks the page
itself. It reads the `<link rel="alternate">` declarations that browsers and
readers use for exactly this purpose, then tries the handful of conventional
paths, and validates every candidate by actually parsing it. What comes back is
a config snippet you can paste, not a suggestion to verify by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List
from urllib.parse import urljoin, urlparse

import feedparser
import httpx2 as httpx

FEED_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/rdf+xml",
    "application/xml",
    "text/xml",
}

# 사이트가 아무것도 선언하지 않았을 때 시도해 볼 관용적 경로.
COMMON_PATHS = ["/rss", "/rss.xml", "/feed", "/feed.xml", "/atom.xml", "/index.xml", "/rss/"]


@dataclass
class FeedCandidate:
    url: str
    source: str  # "선언" | "관용 경로" | "입력"
    ok: bool = False
    entries: int = 0
    title: str = ""
    sample: str = ""
    error: str = ""


class _LinkParser(HTMLParser):
    """Collects <link rel=alternate type=…feed…> hrefs, plus <a> feed links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        href = attributes.get("href", "").strip()
        if not href:
            return
        if tag == "link":
            rel = attributes.get("rel", "").lower()
            type_ = attributes.get("type", "").lower().split(";")[0].strip()
            if "alternate" in rel and type_ in FEED_TYPES:
                self.hrefs.append(href)
        elif tag == "a" and re.search(r"(^|/)(rss|feed|atom)(\.xml|/|$|\?)", href, re.I):
            self.hrefs.append(href)


def declared_feeds(html: str, base_url: str) -> List[str]:
    """Feed addresses the page declares, resolved against the page URL."""
    parser = _LinkParser()
    try:
        parser.feed(html)
    except Exception:  # malformed markup is common; keep whatever was parsed
        pass
    seen: set[str] = set()
    resolved: List[str] = []
    for href in parser.hrefs:
        url = urljoin(base_url, href)
        if url not in seen:
            seen.add(url)
            resolved.append(url)
    return resolved


def _looks_like_feed(raw: bytes) -> tuple[bool, int, str, str]:
    """Parse bytes as a feed. Returns (ok, entry count, feed title, sample title)."""
    parsed = feedparser.parse(raw)
    entries = getattr(parsed, "entries", []) or []
    if not entries:
        return False, 0, "", ""
    feed_title = str(getattr(parsed.feed, "title", "") or "")
    sample = str(getattr(entries[0], "title", "") or "")
    return True, len(entries), feed_title, sample


async def _check(client: httpx.AsyncClient, candidate: FeedCandidate) -> FeedCandidate:
    try:
        response = await client.get(candidate.url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        candidate.error = f"HTTP {exc.response.status_code}"
        return candidate
    except Exception as exc:
        candidate.error = str(exc)
        return candidate

    ok, entries, title, sample = _looks_like_feed(response.content)
    if not ok:
        candidate.error = "피드로 해석되지 않거나 항목이 없음"
        return candidate
    candidate.ok = True
    candidate.entries = entries
    candidate.title = title
    candidate.sample = sample
    return candidate


async def discover(
    page_url: str,
    *,
    user_agent: str,
    timeout: float = 20.0,
    try_common_paths: bool = True,
) -> List[FeedCandidate]:
    """Return every candidate feed for `page_url`, validated.

    The page URL itself is checked first: pointing this at an address that is
    already a feed should confirm it rather than fail.
    """
    headers = {"User-Agent": user_agent, "Accept-Language": "ko,en;q=0.8"}
    results: List[FeedCandidate] = []
    async with httpx.AsyncClient(
        headers=headers, timeout=timeout, follow_redirects=True
    ) as client:
        direct = await _check(client, FeedCandidate(url=page_url, source="입력"))
        if direct.ok:
            return [direct]

        html = ""
        try:
            response = await client.get(page_url)
            response.raise_for_status()
            html = response.text
        except Exception as exc:
            return [FeedCandidate(url=page_url, source="입력", error=f"페이지를 열지 못했습니다: {exc}")]

        candidates = [FeedCandidate(url=u, source="선언") for u in declared_feeds(html, page_url)]
        if try_common_paths:
            known = {c.url for c in candidates}
            root = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
            for path in COMMON_PATHS:
                url = root + path
                if url not in known:
                    known.add(url)
                    candidates.append(FeedCandidate(url=url, source="관용 경로"))

        for candidate in candidates:
            results.append(await _check(client, candidate))
    # 선언된 주소를 관용 경로보다 앞에 두고, 동작하는 것을 먼저 보여 준다.
    results.sort(key=lambda c: (not c.ok, c.source != "선언", -c.entries))
    return results


def config_snippet(name: str, candidates: List[FeedCandidate]) -> str:
    """A pasteable communities.yaml entry listing every working candidate."""
    working = [c for c in candidates if c.ok]
    if not working:
        return ""
    lines = [
        f"  - name: {name}",
        "    source: rss",
        "    locale: ko",
        "    options:",
        "      url:",
    ]
    lines += [f"        - {c.url}" for c in working]
    return "\n".join(lines)
