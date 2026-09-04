"""Adapter tests. Every fetch helper is stubbed; nothing leaves the process."""

import pytest

from comradar.config import CommunityConfig, HttpConfig
from comradar.sources import FetchContext, SourceError, available_sources, get_adapter
from comradar.sources import apis, generic, rss

CTX = FetchContext(client=None, http=HttpConfig(request_delay_seconds=0.0), limit=10)

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title>
<item>
  <title>세탁기 소음 민원</title>
  <link>https://example.com/1</link>
  <guid>g1</guid>
  <description>&lt;p&gt;밤에 &lt;b&gt;소리가&lt;/b&gt; 큽니다&lt;/p&gt;</description>
  <pubDate>Thu, 04 Sep 2026 01:00:00 +0000</pubDate>
</item>
</channel></rss>"""


def test_registry_lists_builtin_adapters():
    assert {"rss", "reddit", "hackernews", "lemmy", "discourse", "json"} <= set(
        available_sources()
    )


def test_unknown_source_names_the_alternatives():
    with pytest.raises(SourceError, match="사용 가능"):
        get_adapter("no-such-source")


async def test_rss_strips_markup_and_keeps_link(monkeypatch):
    async def fake_bytes(ctx, url):
        return FEED.encode("utf-8")

    monkeypatch.setattr(rss, "get_bytes", fake_bytes)
    community = CommunityConfig(name="C", source="rss", options={"url": "https://x/feed"})
    posts = await rss.fetch_rss(community, CTX)

    assert len(posts) == 1
    assert posts[0].title == "세탁기 소음 민원"
    assert posts[0].body == "밤에 소리가 큽니다"  # HTML 태그가 제거된다
    assert posts[0].url == "https://example.com/1"
    assert posts[0].created_at.year == 2026


async def test_rss_requires_url():
    with pytest.raises(SourceError, match="options.url"):
        await rss.fetch_rss(CommunityConfig(name="C", source="rss"), CTX)


async def test_reddit_skips_stickied_and_builds_permalink(monkeypatch):
    async def fake_json(ctx, url, params=None):
        return {
            "data": {
                "children": [
                    {"data": {"id": "a1", "title": "공지", "stickied": True}},
                    {
                        "data": {
                            "id": "a2",
                            "title": "전세 계약 갱신이 헷갈림",
                            "selftext": "본문",
                            "permalink": "/r/korea/comments/a2/x/",
                            "score": 12,
                            "num_comments": 7,
                            "created_utc": 1_780_000_000,
                        }
                    },
                ]
            }
        }

    monkeypatch.setattr(apis, "get_json", fake_json)
    community = CommunityConfig(name="C", source="reddit", options={"subreddit": "korea"})
    posts = await apis.fetch_reddit(community, CTX)

    assert [p.post_id for p in posts] == ["reddit:a2"]
    assert posts[0].url == "https://www.reddit.com/r/korea/comments/a2/x/"
    assert posts[0].engagement() == 12 + 2 * 7


async def test_hackernews_maps_hits(monkeypatch):
    async def fake_json(ctx, url, params=None):
        return {
            "hits": [
                {
                    "objectID": "42",
                    "title": "Ask HN: 병원 예약",
                    "story_text": "<p>전화만 됩니다</p>",
                    "points": 30,
                    "num_comments": 11,
                    "created_at": "2026-09-04T02:00:00.000Z",
                }
            ]
        }

    monkeypatch.setattr(apis, "get_json", fake_json)
    posts = await apis.fetch_hackernews(CommunityConfig(name="HN", source="hackernews"), CTX)
    assert posts[0].url == "https://news.ycombinator.com/item?id=42"
    assert posts[0].body == "전화만 됩니다"


async def test_generic_json_uses_field_mapping(monkeypatch):
    async def fake_json(ctx, url, params=None):
        return {"data": {"items": [{"no": 7, "subject": "주차 시비", "writer": {"nick": "kim"}}]}}

    monkeypatch.setattr(generic, "get_json", fake_json)
    community = CommunityConfig(
        name="예시",
        source="json",
        options={
            "url": "https://x/api",
            "items_path": "data.items",
            "fields": {"id": "no", "title": "subject", "author": "writer.nick"},
        },
    )
    posts = await generic.fetch_json(community, CTX)
    assert posts[0].title == "주차 시비"
    assert posts[0].author == "kim"
    assert posts[0].post_id.endswith(":7")


async def test_generic_json_reports_bad_items_path(monkeypatch):
    async def fake_json(ctx, url, params=None):
        return {"data": {}}

    monkeypatch.setattr(generic, "get_json", fake_json)
    community = CommunityConfig(
        name="예시", source="json", options={"url": "https://x", "items_path": "data.items"}
    )
    with pytest.raises(SourceError, match="items_path"):
        await generic.fetch_json(community, CTX)
