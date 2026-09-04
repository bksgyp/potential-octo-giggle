"""Adapters for communities that publish a documented JSON API.

Each adapter sticks to the site's own public read endpoint. None of them log
in, none of them page beyond the configured limit, and all of them inherit the
shared request delay from `FetchContext`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

from ..config import CommunityConfig
from ..models import RawPost
from .base import FetchContext, get_json, register, require
from .rss import strip_html


def _ts(value: Any) -> datetime:
    """Epoch seconds or an ISO-8601 string, whichever the API returned."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@register("reddit")
async def fetch_reddit(community: CommunityConfig, ctx: FetchContext) -> List[RawPost]:
    """Reddit's public listing endpoint. `options.subreddit` is required.

    Reddit blocks unidentified clients, so `http.user_agent` in the config must
    be a real, contactable identifier.
    """
    sub = require(community.options, "subreddit", community.name)
    listing = str(community.options.get("listing", "new"))
    url = f"https://www.reddit.com/r/{sub}/{listing}.json"
    data = await get_json(ctx, url, params={"limit": ctx.limit, "raw_json": 1})

    posts: List[RawPost] = []
    for child in (data.get("data") or {}).get("children") or []:
        d = child.get("data") or {}
        if d.get("stickied"):
            continue
        posts.append(
            RawPost(
                post_id=f"reddit:{d.get('id')}",
                community=community.name,
                title=d.get("title") or "(제목 없음)",
                body=(d.get("selftext") or "").strip(),
                url=f"https://www.reddit.com{d.get('permalink', '')}",
                author=d.get("author") or "",
                score=int(d.get("score") or 0),
                num_comments=int(d.get("num_comments") or 0),
                created_at=_ts(d.get("created_utc")),
            )
        )
    return posts


@register("hackernews")
async def fetch_hackernews(community: CommunityConfig, ctx: FetchContext) -> List[RawPost]:
    """Hacker News via the Algolia search API. No auth, no rate-limit key."""
    query = str(community.options.get("query", ""))
    tags = str(community.options.get("tags", "story"))
    params = {"tags": tags, "hitsPerPage": ctx.limit}
    if query:
        params["query"] = query
    data = await get_json(ctx, "https://hn.algolia.com/api/v1/search_by_date", params=params)

    posts: List[RawPost] = []
    for hit in data.get("hits") or []:
        object_id = hit.get("objectID")
        if not object_id:
            continue
        posts.append(
            RawPost(
                post_id=f"hn:{object_id}",
                community=community.name,
                title=hit.get("title") or hit.get("story_title") or "(제목 없음)",
                body=strip_html(hit.get("story_text") or hit.get("comment_text") or ""),
                url=f"https://news.ycombinator.com/item?id={object_id}",
                author=hit.get("author") or "",
                score=int(hit.get("points") or 0),
                num_comments=int(hit.get("num_comments") or 0),
                created_at=_ts(hit.get("created_at")),
            )
        )
    return posts


@register("lemmy")
async def fetch_lemmy(community: CommunityConfig, ctx: FetchContext) -> List[RawPost]:
    """Any Lemmy instance. `options.instance` is the base URL."""
    instance = require(community.options, "instance", community.name).rstrip("/")
    params: dict[str, Any] = {
        "sort": str(community.options.get("sort", "New")),
        "limit": ctx.limit,
        "type_": str(community.options.get("type", "All")),
    }
    if community.options.get("community_name"):
        params["community_name"] = str(community.options["community_name"])
    data = await get_json(ctx, f"{instance}/api/v3/post/list", params=params)

    posts: List[RawPost] = []
    for view in data.get("posts") or []:
        post = view.get("post") or {}
        counts = view.get("counts") or {}
        post_id = post.get("id")
        if post_id is None:
            continue
        posts.append(
            RawPost(
                post_id=f"lemmy:{instance}:{post_id}",
                community=community.name,
                title=post.get("name") or "(제목 없음)",
                body=(post.get("body") or "").strip(),
                url=post.get("ap_id") or f"{instance}/post/{post_id}",
                author=(view.get("creator") or {}).get("name") or "",
                score=int(counts.get("score") or 0),
                num_comments=int(counts.get("comments") or 0),
                created_at=_ts(post.get("published")),
            )
        )
    return posts


@register("discourse")
async def fetch_discourse(community: CommunityConfig, ctx: FetchContext) -> List[RawPost]:
    """Any Discourse forum. `options.base_url` is the forum root."""
    base = require(community.options, "base_url", community.name).rstrip("/")
    path = str(community.options.get("path", "/latest.json"))
    data = await get_json(ctx, f"{base}{path}")

    topics = ((data.get("topic_list") or {}).get("topics")) or []
    posts: List[RawPost] = []
    for topic in topics[: ctx.limit]:
        topic_id = topic.get("id")
        if topic_id is None or topic.get("pinned"):
            continue
        posts.append(
            RawPost(
                post_id=f"discourse:{base}:{topic_id}",
                community=community.name,
                title=topic.get("title") or "(제목 없음)",
                body=strip_html(topic.get("excerpt") or ""),
                url=f"{base}/t/{topic.get('slug', 't')}/{topic_id}",
                score=int(topic.get("like_count") or 0),
                num_comments=max(int(topic.get("posts_count") or 1) - 1, 0),
                created_at=_ts(topic.get("created_at")),
            )
        )
    return posts
