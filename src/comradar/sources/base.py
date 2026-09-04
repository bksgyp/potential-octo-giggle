"""Source adapter registry.

A source adapter turns one `CommunityConfig` into a list of `RawPost`. Adapters
are async, get a shared HTTP client, and are responsible for nothing else: no
filtering, no dedupe, no analysis. That keeps each adapter small enough to be
obviously correct.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List

import httpx2 as httpx

from ..config import CommunityConfig, HttpConfig
from ..models import RawPost


class SourceError(RuntimeError):
    """A community could not be fetched. Never fatal to the whole run."""


@dataclass
class FetchContext:
    client: httpx.AsyncClient
    http: HttpConfig
    limit: int


Adapter = Callable[[CommunityConfig, FetchContext], Awaitable[List[RawPost]]]

_REGISTRY: Dict[str, Adapter] = {}


def register(name: str) -> Callable[[Adapter], Adapter]:
    def decorator(fn: Adapter) -> Adapter:
        _REGISTRY[name] = fn
        return fn

    return decorator


def get_adapter(name: str) -> Adapter:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise SourceError(
            f"알 수 없는 source '{name}'. 사용 가능: {', '.join(sorted(_REGISTRY))}"
        ) from None


def available_sources() -> List[str]:
    return sorted(_REGISTRY)


def require(options: dict, key: str, community: str) -> str:
    value = options.get(key)
    if not value:
        raise SourceError(f"'{community}' 설정에 options.{key}가 필요합니다.")
    return str(value)


async def get_json(ctx: FetchContext, url: str, params: dict | None = None):
    """GET a JSON document, converting transport failures into SourceError."""
    try:
        resp = await ctx.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise SourceError(f"{url} 응답 {exc.response.status_code}") from exc
    except Exception as exc:  # network, JSON decode, ...
        raise SourceError(f"{url} 요청 실패: {exc}") from exc
    finally:
        # Space out requests so a single run never looks like a scraper burst.
        if ctx.http.request_delay_seconds > 0:
            await asyncio.sleep(ctx.http.request_delay_seconds)


async def get_bytes(ctx: FetchContext, url: str) -> bytes:
    try:
        resp = await ctx.client.get(url)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPStatusError as exc:
        raise SourceError(f"{url} 응답 {exc.response.status_code}") from exc
    except Exception as exc:
        raise SourceError(f"{url} 요청 실패: {exc}") from exc
    finally:
        if ctx.http.request_delay_seconds > 0:
            await asyncio.sleep(ctx.http.request_delay_seconds)
