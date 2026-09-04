"""Thin wrapper around the Messages API for structured agent calls.

Every agent in this framework does the same thing: send a stable system prompt
plus a volatile payload, and get back one validated Pydantic object. That is
the only shape this module supports, and it is deliberately the only one.

Three API features matter here and are on by default:

* **Structured outputs** (`output_format=<PydanticModel>`) so a malformed reply
  is impossible rather than merely unlikely.
* **Server-side refusal fallbacks** so a policy decline is retried on a
  fallback model inside the same call instead of dropping a community's slot.
* **Prompt caching on the system block**, which is the only part of the request
  that repeats across the hourly runs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Protocol, Type, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .config import AgentModelConfig

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# The scalar `fallbacks="default"` form; its beta flag differs from the array form.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AgentError(RuntimeError):
    """The model could not produce a usable answer for this agent call."""


@dataclass
class Usage:
    """Token accounting, aggregated across every call in a run."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    per_agent: dict[str, int] = field(default_factory=dict)

    def add(self, label: str, usage) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.per_agent[label] = self.per_agent.get(label, 0) + 1

    def summary(self) -> str:
        return (
            f"{self.calls}회 호출 / 입력 {self.input_tokens:,} 토큰 "
            f"(캐시 적중 {self.cache_read_tokens:,}) / 출력 {self.output_tokens:,} 토큰"
        )


class StructuredCaller(Protocol):
    """What the agents depend on. Tests substitute their own implementation."""

    async def structured(
        self,
        *,
        cfg: AgentModelConfig,
        system: str,
        user: str,
        schema: Type[T],
        label: str,
    ) -> T: ...


class LLMClient:
    """`StructuredCaller` backed by the Anthropic API."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        *,
        max_concurrent: int = 4,
        enable_fallbacks: bool = True,
        usage: Usage | None = None,
    ) -> None:
        # A bare constructor resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN,
        # or an `ant auth login` profile, in that order.
        self._client = client or anthropic.AsyncAnthropic()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._enable_fallbacks = enable_fallbacks
        self.usage = usage or Usage()

    async def structured(
        self,
        *,
        cfg: AgentModelConfig,
        system: str,
        user: str,
        schema: Type[T],
        label: str,
    ) -> T:
        async with self._semaphore:
            return await self._call(cfg=cfg, system=system, user=user, schema=schema, label=label)

    async def _call(
        self,
        *,
        cfg: AgentModelConfig,
        system: str,
        user: str,
        schema: Type[T],
        label: str,
        _retry: bool = True,
    ) -> T:
        kwargs = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            # The system block is the stable prefix across hourly runs, so the
            # cache breakpoint goes here and nowhere else.
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": cfg.effort},
            "output_format": schema,
        }
        if self._enable_fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        try:
            response = await self._client.beta.messages.parse(**kwargs)
        except anthropic.NotFoundError as exc:
            raise AgentError(f"[{label}] 모델 '{cfg.model}'을 찾을 수 없습니다: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise AgentError(f"[{label}] 레이트 리밋에 걸렸습니다: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise AgentError(f"[{label}] API 오류 {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise AgentError(f"[{label}] API 연결 실패: {exc}") from exc

        self.usage.add(label, response.usage)

        # A refusal is an HTTP 200. Check it before touching the content.
        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            category = getattr(detail, "category", None) if detail else None
            raise AgentError(f"[{label}] 모델이 응답을 거부했습니다 (분류: {category}).")
        if response.stop_reason == "max_tokens":
            raise AgentError(
                f"[{label}] max_tokens({cfg.max_tokens})에서 잘렸습니다. 입력을 줄이거나 한도를 올리세요."
            )

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            if _retry:
                logger.warning("[%s] 구조화 출력 파싱 실패. 1회 재시도합니다.", label)
                return await self._call(
                    cfg=cfg,
                    system=system,
                    user=user + "\n\n(주의: 직전 응답이 스키마를 만족하지 않았습니다. 스키마를 정확히 지키세요.)",
                    schema=schema,
                    label=label,
                    _retry=False,
                )
            raise AgentError(f"[{label}] 스키마에 맞는 응답을 얻지 못했습니다.")
        try:
            return schema.model_validate(parsed.model_dump())
        except ValidationError as exc:
            raise AgentError(f"[{label}] 응답 검증 실패: {exc}") from exc
