"""피드 자동 발견. HTTP는 전부 대체하고, 파싱 규칙만 검증한다."""

import pytest

from comradar import discover as discover_mod
from comradar.discover import FeedCandidate, config_snippet, declared_feeds, discover

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>유머 게시판</title>
<item><title>첫 글</title><link>https://x/1</link><guid>1</guid></item>
</channel></rss>""".encode("utf-8")

PAGE = """
<html><head>
  <link rel="stylesheet" href="/style.css">
  <link rel="alternate" type="application/rss+xml" title="피드" href="/board/300143/rss">
  <link rel="alternate" type="application/atom+xml" href="https://other.example/atom.xml">
</head><body><a href="/legacy/feed">구 피드</a></body></html>
"""


def test_declared_feeds_resolves_relative_urls():
    urls = declared_feeds(PAGE, "https://bbs.example.com/community/board/300143")
    assert "https://bbs.example.com/board/300143/rss" in urls
    assert "https://other.example/atom.xml" in urls
    assert "https://bbs.example.com/legacy/feed" in urls
    # 스타일시트는 피드가 아니다.
    assert not any("style.css" in u for u in urls)


def test_declared_feeds_survives_broken_markup():
    assert declared_feeds("<html><head><link rel=alternate", "https://x/") == []


def test_config_snippet_lists_only_working_candidates():
    snippet = config_snippet(
        "루리웹",
        [
            FeedCandidate(url="https://x/dead", source="관용 경로", error="HTTP 404"),
            FeedCandidate(url="https://x/live", source="선언", ok=True, entries=20),
        ],
    )
    assert "https://x/live" in snippet
    assert "https://x/dead" not in snippet
    assert "source: rss" in snippet


def test_config_snippet_is_empty_when_nothing_works():
    assert config_snippet("x", [FeedCandidate(url="https://x", source="입력")]) == ""


class FakeResponse:
    def __init__(self, content: bytes = b"", status: int = 200, text: str = ""):
        self.content = content
        self.status_code = status
        self.text = text or content.decode("utf-8", "ignore")

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx2 as httpx

            raise httpx.HTTPStatusError("boom", request=None, response=self)


class FakeClient:
    def __init__(self, routes: dict):
        self.routes = routes
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self.requested.append(url)
        if url in self.routes:
            return self.routes[url]
        return FakeResponse(status=404)


@pytest.fixture
def patch_client(monkeypatch):
    def apply(routes):
        client = FakeClient(routes)
        monkeypatch.setattr(discover_mod.httpx, "AsyncClient", lambda **kw: client)
        return client

    return apply


async def test_discover_confirms_a_url_that_is_already_a_feed(patch_client):
    client = patch_client({"https://x/rss": FakeResponse(FEED)})
    results = await discover("https://x/rss", user_agent="test")
    assert len(results) == 1 and results[0].ok
    assert results[0].source == "입력"
    assert results[0].entries == 1 and results[0].sample == "첫 글"
    # 이미 피드였으므로 관용 경로를 헛되이 두드리지 않는다.
    assert client.requested == ["https://x/rss"]


async def test_discover_prefers_the_declared_feed(patch_client):
    patch_client(
        {
            "https://bbs.example.com/board/1": FakeResponse(text=PAGE, content=PAGE.encode()),
            "https://bbs.example.com/board/300143/rss": FakeResponse(FEED),
            "https://bbs.example.com/rss": FakeResponse(FEED),
        }
    )
    results = await discover("https://bbs.example.com/board/1", user_agent="test")
    working = [c for c in results if c.ok]
    assert working[0].source == "선언"
    assert working[0].url == "https://bbs.example.com/board/300143/rss"


async def test_discover_falls_back_to_common_paths(patch_client):
    bare = "<html><head></head><body>no feed link</body></html>"
    patch_client(
        {
            "https://x/board": FakeResponse(text=bare, content=bare.encode()),
            "https://x/feed": FakeResponse(FEED),
        }
    )
    results = await discover("https://x/board", user_agent="test")
    working = [c for c in results if c.ok]
    assert [c.url for c in working] == ["https://x/feed"]
    assert working[0].source == "관용 경로"


async def test_discover_can_skip_common_paths(patch_client):
    bare = "<html><head></head><body></body></html>"
    client = patch_client({"https://x/board": FakeResponse(text=bare, content=bare.encode())})
    await discover("https://x/board", user_agent="test", try_common_paths=False)
    # 입력 확인 1회 + 페이지 1회. 추측은 하지 않는다.
    assert client.requested == ["https://x/board", "https://x/board"]


async def test_discover_reports_an_unreachable_page(patch_client):
    patch_client({})
    results = await discover("https://x/gone", user_agent="test")
    assert len(results) == 1 and not results[0].ok
    assert "페이지를 열지 못했습니다" in results[0].error
