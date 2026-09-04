"""RSS / Atom adapter.

This is the adapter of first resort: a feed is the one interface a site owner
has explicitly offered for machine reading.

`options.url` accepts either a single address or a list of candidates. Feed
addresses move when a site is redesigned, and a community whose feed moved
should degrade to "try the next address", not to "this source is dead". The
first candidate that parses into at least one entry wins; if none do, the
error names every address that was tried and why each failed.
"""

from __future__ import annotations

import re
from calendar import timegm
from datetime import datetime, timezone
from typing import List

import feedparser

from ..config import CommunityConfig
from ..models import RawPost
from .base import FetchContext, SourceError, get_bytes, register

_TAG = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", text or "")).strip()


def _entry_time(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _candidates(community: CommunityConfig) -> List[str]:
    raw = community.options.get("url")
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if isinstance(raw, list):
        urls = [str(item).strip() for item in raw if str(item).strip()]
        if urls:
            return urls
    raise SourceError(
        f"'{community.name}' 설정에 options.url이 필요합니다 (문자열 또는 주소 목록)."
    )


def parse_feed(raw: bytes, community: CommunityConfig, limit: int) -> List[RawPost]:
    body_field = str(community.options.get("body_field", "summary"))
    feed = feedparser.parse(raw)

    posts: List[RawPost] = []
    for entry in feed.entries[:limit]:
        link = getattr(entry, "link", "")
        post_id = getattr(entry, "id", "") or link or getattr(entry, "title", "")
        if not post_id:
            continue
        body = strip_html(getattr(entry, body_field, "") or getattr(entry, "summary", ""))
        posts.append(
            RawPost(
                post_id=str(post_id),
                community=community.name,
                title=strip_html(getattr(entry, "title", "")) or "(제목 없음)",
                body=body,
                url=link,
                author=str(getattr(entry, "author", "")),
                created_at=_entry_time(entry),
            )
        )
    return posts


@register("rss")
async def fetch_rss(community: CommunityConfig, ctx: FetchContext) -> List[RawPost]:
    failures: List[str] = []
    for url in _candidates(community):
        try:
            raw = await get_bytes(ctx, url)
        except SourceError as exc:
            failures.append(str(exc))
            continue
        posts = parse_feed(raw, community, ctx.limit)
        if posts:
            return posts
        failures.append(f"{url}: 피드는 받았으나 항목이 없습니다 (주소가 바뀌었을 수 있습니다)")
    raise SourceError(
        f"'{community.name}' 후보 주소를 모두 시도했습니다. " + " / ".join(failures)
    )
