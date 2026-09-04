"""Naver Search API adapter.

Korea's largest user-generated forums are not reachable by RSS. 클리앙,
디시인사이드 and 오늘의유머 publish no official feed, and 뽐뿌 publishes feeds
only for its deal boards, so pointing an RSS adapter at any of them is a guess
that breaks silently.

Naver's Search API is the documented way in. It covers 네이버 카페 글
(`cafearticle`) and 지식iN (`kin`), which together are the highest-volume
Korean user-generated text there is, and 지식iN in particular is a place people
go precisely because something in daily life is not working.

It is a search API, not a feed, so it needs seed queries. That is a real
sampling bias and the framework says so in the report rather than hiding it:
you see the friction that people phrase the way your queries do.

Credentials: register an application at https://developers.naver.com and put
the client id and secret in the environment variables named by
`options.client_id_env` / `options.client_secret_env`.
"""

from __future__ import annotations

import html
import os
import re
from typing import Any, List

from ..config import CommunityConfig
from ..models import RawPost
from .base import FetchContext, SourceError, get_json, register

API_ROOT = "https://openapi.naver.com/v1/search"

# 서비스별 항목 수. 검색 API는 최대 100건까지 돌려준다.
MAX_DISPLAY = 100

SERVICES = {
    "cafearticle": "카페글",
    "kin": "지식iN",
    "blog": "블로그",
    "webkr": "웹문서",
}

_TAG = re.compile(r"<[^>]+>")

# 씨앗 질의 기본값. 사람들이 불편을 말할 때 실제로 쓰는 표현들이다.
DEFAULT_QUERIES = [
    "너무 불편해요",
    "방법 없을까요",
    "매번 이래야 하나요",
    "짜증나서 못 쓰겠어요",
]


def clean(text: str) -> str:
    """Search results carry <b> highlight tags and HTML entities."""
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", text or ""))).strip()


def _credentials(options: dict, community: str) -> tuple[str, str]:
    id_env = str(options.get("client_id_env", "NAVER_CLIENT_ID"))
    secret_env = str(options.get("client_secret_env", "NAVER_CLIENT_SECRET"))
    client_id = os.environ.get(id_env, "").strip()
    client_secret = os.environ.get(secret_env, "").strip()
    if not client_id or not client_secret:
        raise SourceError(
            f"'{community}': 환경변수 {id_env}와 {secret_env}가 필요합니다. "
            "https://developers.naver.com 에서 애플리케이션을 등록해 발급받으세요."
        )
    return client_id, client_secret


def _post_id(service: str, link: str) -> str:
    return f"naver:{service}:{link}"


def _to_post(item: dict[str, Any], community: CommunityConfig, service: str) -> RawPost | None:
    link = str(item.get("link") or "").strip()
    title = clean(str(item.get("title") or ""))
    if not link or not title:
        return None
    # 카페글은 어느 카페에서 왔는지가 신호이므로 작성자 자리에 카페 이름을 둔다.
    author = clean(str(item.get("cafename") or item.get("bloggername") or ""))
    return RawPost(
        post_id=_post_id(service, link),
        community=community.name,
        title=title,
        body=clean(str(item.get("description") or "")),
        url=link,
        author=author,
    )


@register("naver")
async def fetch_naver(community: CommunityConfig, ctx: FetchContext) -> List[RawPost]:
    options = community.options
    service = str(options.get("service", "cafearticle"))
    if service not in SERVICES:
        raise SourceError(
            f"'{community.name}': 알 수 없는 service {service!r}. "
            f"사용 가능: {', '.join(sorted(SERVICES))}"
        )
    client_id, client_secret = _credentials(options, community.name)

    queries = [str(q).strip() for q in (options.get("queries") or DEFAULT_QUERIES) if str(q).strip()]
    if not queries:
        raise SourceError(f"'{community.name}': options.queries가 비어 있습니다.")

    # 질의 하나당 한 번 호출한다. 전체 상한을 질의 수로 나눠 배분하되,
    # 검색 API가 허용하는 건수를 넘기지 않는다.
    per_query = max(1, min(MAX_DISPLAY, ctx.limit // len(queries) or 1))
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}

    posts: List[RawPost] = []
    seen: set[str] = set()
    failures: List[str] = []
    for query in queries:
        if len(posts) >= ctx.limit:
            break
        try:
            payload = await get_json(
                ctx,
                f"{API_ROOT}/{service}.json",
                params={
                    "query": query,
                    "display": per_query,
                    "sort": str(options.get("sort", "date")),
                },
                headers=headers,
            )
        except SourceError as exc:
            failures.append(f"{query}: {exc}")
            continue
        for item in payload.get("items") or []:
            post = _to_post(item, community, service)
            if post is None or post.post_id in seen:
                continue
            seen.add(post.post_id)
            posts.append(post)

    if not posts and failures:
        raise SourceError(f"'{community.name}' 질의를 모두 실패했습니다. " + " / ".join(failures))
    return posts[: ctx.limit]
