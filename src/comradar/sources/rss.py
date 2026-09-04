"""RSS / Atom adapter.

This is the adapter of first resort. Most forums, blogs and Korean community
boards publish a feed, and a feed is the one interface a site owner has
explicitly offered for machine reading.
"""

from __future__ import annotations

import re
from calendar import timegm
from datetime import datetime, timezone
from typing import List

import feedparser

from ..config import CommunityConfig
from ..models import RawPost
from .base import FetchContext, get_bytes, register, require

_TAG = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", text or "")).strip()


def _entry_time(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
    return datetime.now(timezone.utc)


@register("rss")
async def fetch_rss(community: CommunityConfig, ctx: FetchContext) -> List[RawPost]:
    url = require(community.options, "url", community.name)
    body_field = str(community.options.get("body_field", "summary"))
    raw = await get_bytes(ctx, url)
    feed = feedparser.parse(raw)

    posts: List[RawPost] = []
    for entry in feed.entries[: ctx.limit]:
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
