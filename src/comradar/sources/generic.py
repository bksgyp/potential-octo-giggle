"""Generic JSON adapter for APIs that have no dedicated adapter yet.

Point it at a URL, tell it where the array of items lives and which key holds
which field. This is the escape hatch that keeps "add a community" a config
change rather than a pull request.
"""

from __future__ import annotations

from typing import Any, List

from ..config import CommunityConfig
from ..models import RawPost
from .apis import _ts
from .base import FetchContext, SourceError, get_json, register, require
from .rss import strip_html


def _dig(data: Any, path: str) -> Any:
    """Walk a dotted path. An empty path returns the document itself."""
    if not path:
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)] if int(part) < len(current) else None
        else:
            return None
    return current


@register("json")
async def fetch_json(community: CommunityConfig, ctx: FetchContext) -> List[RawPost]:
    url = require(community.options, "url", community.name)
    items_path = str(community.options.get("items_path", ""))
    fields: dict[str, str] = dict(community.options.get("fields") or {})
    params = dict(community.options.get("params") or {})

    data = await get_json(ctx, url, params=params or None)
    items = _dig(data, items_path)
    if not isinstance(items, list):
        raise SourceError(
            f"'{community.name}': items_path '{items_path}'가 배열을 가리키지 않습니다."
        )

    id_key = fields.get("id", "id")
    title_key = fields.get("title", "title")
    posts: List[RawPost] = []
    for item in items[: ctx.limit]:
        raw_id = _dig(item, id_key)
        if raw_id is None:
            continue
        posts.append(
            RawPost(
                post_id=f"{community.slug}:{raw_id}",
                community=community.name,
                title=str(_dig(item, title_key) or "(제목 없음)"),
                body=strip_html(str(_dig(item, fields.get("body", "body")) or "")),
                url=str(_dig(item, fields.get("url", "url")) or ""),
                author=str(_dig(item, fields.get("author", "author")) or ""),
                score=int(_dig(item, fields.get("score", "score")) or 0),
                num_comments=int(_dig(item, fields.get("comments", "comments")) or 0),
                created_at=_ts(_dig(item, fields.get("created_at", "created_at"))),
            )
        )
    return posts
