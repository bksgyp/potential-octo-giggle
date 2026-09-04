"""The orchestrator: fan out to collectors, then synthesise, ideate, report.

    community 1 ─┐
    community 2 ─┼─▶ 수집 에이전트 (커뮤니티당 하나, 병렬, 서로 격리) ─▶ SQLite
    community N ─┘                                                        │
                                                                          ▼
                                                                   분석 에이전트
                                                                          │
                                                    노션 포트폴리오 ─▶ 사업화 에이전트
                                                                          │
                                                                          ▼
                                                                   보고 에이전트 ─▶ 한 장

The two phases run on different clocks. Collection is hourly, because the
point of hourly polling is to catch posts before they scroll off the front
page. Reporting is every four hours, because a report needs enough new
material to say something a person did not already know.

Every stage failure is contained. A community that 403s loses its slot in this
run and is named in the report footnote; it does not take the run down.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx2 as httpx

from .agents import CollectorAgent, IdeationAgent, ReportAgent, SynthesisAgent
from .config import AppConfig, CommunityConfig
from .delivery import post_to_slack, write_report
from .llm import AgentError, LLMClient, StructuredCaller, Usage
from .models import (
    IdeationResult,
    PortfolioIdea,
    RawPost,
    ReportDraft,
    StoredPainPoint,
    SynthesisResult,
)
from .portfolio import load_portfolio
from .render import render_html, render_markdown
from .sources import FetchContext, SourceError, get_adapter
from .state import Store

logger = logging.getLogger(__name__)

REPORT_CHECKPOINT = "last_report"


@dataclass
class CommunityResult:
    """What one collector agent achieved this run."""

    community: str
    fetched: int = 0
    new_posts: int = 0
    pain_points: int = 0
    mood: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class RunResult:
    run_id: str
    generated_at: datetime
    stats: dict
    communities: List[CommunityResult] = field(default_factory=list)
    reported: bool = False
    synthesis: Optional[SynthesisResult] = None
    ideation: Optional[IdeationResult] = None
    draft: Optional[ReportDraft] = None
    portfolio: List[PortfolioIdea] = field(default_factory=list)
    markdown: str = ""
    html: str = ""
    written: List[Path] = field(default_factory=list)


def _local_now(tz_name: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("알 수 없는 시간대 %r. UTC를 사용합니다.", tz_name)
        return datetime.now(timezone.utc)


class Pipeline:
    """One instance per run. Not reused across runs."""

    def __init__(
        self,
        config: AppConfig,
        store: Store,
        llm: StructuredCaller | None = None,
        usage: Usage | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.usage = usage or Usage()
        self.llm = llm

    def _ensure_llm(self) -> StructuredCaller:
        if self.llm is None:
            self.llm = LLMClient(
                max_concurrent=self.config.http.max_concurrent_fetches,
                usage=self.usage,
            )
        return self.llm

    # -- phase 1: collect --------------------------------------------------

    async def fetch_community(
        self, community: CommunityConfig, ctx: FetchContext
    ) -> Sequence[RawPost]:
        adapter = get_adapter(community.source)
        posts = await adapter(community, ctx)
        floor = self.config.run.min_engagement
        if floor > 0:
            posts = [p for p in posts if p.engagement() >= floor]
        return posts

    async def _run_one_community(
        self,
        community: CommunityConfig,
        ctx: FetchContext,
        run_id: str,
        analyse: bool,
    ) -> tuple[CommunityResult, List[StoredPainPoint]]:
        result = CommunityResult(community=community.name)
        try:
            posts = await self.fetch_community(community, ctx)
        except SourceError as exc:
            result.error = str(exc)
            logger.warning("[%s] 수집 실패: %s", community.name, exc)
            return result, []
        except Exception as exc:  # an adapter bug must not kill the run
            result.error = f"예상치 못한 수집 오류: {exc}"
            logger.exception("[%s] 수집 중 예외", community.name)
            return result, []

        result.fetched = len(posts)
        # 매시간 같은 목록을 다시 읽어도, 이전에 본 글은 여기서 걸러진다.
        # 모델에 들어가는 것은 언제나 신규 글뿐이다.
        fresh = self.store.filter_new_posts(posts)
        result.new_posts = len(fresh)
        if not analyse or not fresh:
            return result, []

        agent = CollectorAgent(
            community=community,
            llm=self._ensure_llm(),
            cfg=self.config.collector,
            max_points=self.config.run.max_pain_points_per_community,
        )
        try:
            scan, anchored = await agent.run(fresh, run_id)
        except AgentError as exc:
            result.error = str(exc)
            logger.warning("[%s] 분석 실패: %s", community.name, exc)
            return result, []

        result.mood = scan.community_mood
        result.pain_points = len(anchored)
        return result, anchored

    async def collect(self, run_id: str, analyse: bool = True) -> tuple[List[CommunityResult], int]:
        """Fetch every active community in parallel and store what is new."""
        cfg = self.config
        communities = cfg.active_communities
        headers = {"User-Agent": cfg.http.user_agent, "Accept-Language": "ko,en;q=0.8"}
        semaphore = asyncio.Semaphore(max(1, cfg.http.max_concurrent_fetches))

        async def guarded(community: CommunityConfig, ctx: FetchContext):
            async with semaphore:
                return await self._run_one_community(community, ctx, run_id, analyse)

        results: List[CommunityResult] = []
        all_points: List[StoredPainPoint] = []
        async with httpx.AsyncClient(
            headers=headers, timeout=cfg.http.timeout_seconds, follow_redirects=True
        ) as client:
            tasks = [
                guarded(
                    community,
                    FetchContext(
                        client=client,
                        http=cfg.http,
                        limit=community.max_posts or cfg.run.max_posts_per_community,
                    ),
                )
                for community in communities
            ]
            for result, points in await asyncio.gather(*tasks):
                results.append(result)
                all_points.extend(points)

        stored = self.store.record_pain_points(all_points)
        logger.info("신규 불편 사례 %d건을 기록했습니다.", stored)
        return results, stored

    # -- phase 2: report ---------------------------------------------------

    async def report(self, run_result: RunResult) -> RunResult:
        """Synthesise the window, derive business bets, write the one-pager."""
        cfg = self.config
        window = self.store.window_pain_points(cfg.run.window_hours)
        stats = run_result.stats
        stats["points_window"] = len(window)

        synthesis = await SynthesisAgent(
            llm=self._ensure_llm(), cfg=cfg.synthesizer, max_themes=cfg.run.max_themes
        ).run(window, self.store.previous_themes(), cfg.run.window_hours)
        run_result.synthesis = synthesis
        if synthesis.themes:
            self.store.record_themes(run_result.run_id, synthesis.themes)

        # 사업화 에이전트는 기존 아이디어 목록을 알아야 한다. 모르면 이미
        # 적어 둔 아이디어를 새 아이디어라고 다시 제안한다.
        portfolio = await load_portfolio(cfg.portfolio, timeout=cfg.http.timeout_seconds)
        run_result.portfolio = list(portfolio)
        stats["portfolio_size"] = len(portfolio)

        ideation = await IdeationAgent(
            llm=self._ensure_llm(), cfg=cfg.ideation, max_new_ideas=cfg.run.max_new_ideas
        ).run(synthesis, portfolio)
        run_result.ideation = ideation

        draft = await ReportAgent(llm=self._ensure_llm(), cfg=cfg.reporter).run(
            synthesis, ideation, stats
        )
        run_result.draft = draft

        stats["usage"] = self.usage.summary()
        generated_at = run_result.generated_at
        run_result.markdown = render_markdown(draft, synthesis, ideation, stats, generated_at)
        run_result.html = render_html(draft, synthesis, ideation, stats, generated_at)
        run_result.written = write_report(
            cfg.run.output_dir, generated_at, run_result.markdown, run_result.html, cfg.delivery
        )
        post_to_slack(draft, cfg.delivery)

        self.store.set_checkpoint(REPORT_CHECKPOINT)
        run_result.reported = True
        return run_result

    # -- main entry point --------------------------------------------------

    async def run(self, analyse: bool = True, report_mode: str = "auto") -> RunResult:
        """Collect, then report according to `report_mode`.

        `report_mode` is "auto" (report when the interval has elapsed),
        "force" (report regardless) or "never" (collect only). `analyse=False`
        is the fetch-only smoke test: it exercises every source adapter and the
        dedupe store without spending a token.
        """
        cfg = self.config
        generated_at = _local_now(cfg.run.timezone)
        run_id = generated_at.strftime("%Y%m%dT%H%M%S")
        self.store.start_run(run_id)

        results, stored = await self.collect(run_id, analyse=analyse)
        stats = {
            "run_id": run_id,
            "window_hours": cfg.run.window_hours,
            "report_interval_hours": cfg.run.report_interval_hours,
            "communities_total": len(cfg.active_communities),
            "communities_ok": sum(1 for r in results if r.ok),
            "posts_fetched": sum(r.fetched for r in results),
            "posts_new": sum(r.new_posts for r in results),
            "points_new": stored,
            "failed_communities": [f"{r.community}({r.error})" for r in results if not r.ok],
        }
        run_result = RunResult(
            run_id=run_id, generated_at=generated_at, stats=stats, communities=results
        )

        if not analyse:
            self.store.finish_run(run_id, "fetch-only", stats)
            return run_result

        due = report_mode == "force" or (
            report_mode == "auto"
            and self.store.due(REPORT_CHECKPOINT, cfg.run.report_interval_hours)
        )
        if not due:
            logger.info(
                "보고 주기(%d시간)가 아직 지나지 않았습니다. 수집만 하고 끝냅니다.",
                cfg.run.report_interval_hours,
            )
            self.store.finish_run(run_id, "collected", stats)
            return run_result

        await self.report(run_result)
        self.store.finish_run(run_id, "reported", stats)
        return run_result

    async def report_only(self) -> RunResult:
        """Rebuild the report from what is already stored, without collecting."""
        generated_at = _local_now(self.config.run.timezone)
        run_id = generated_at.strftime("%Y%m%dT%H%M%S")
        self.store.start_run(run_id)
        stats = {
            "run_id": run_id,
            "window_hours": self.config.run.window_hours,
            "report_interval_hours": self.config.run.report_interval_hours,
            "communities_total": len(self.config.active_communities),
            "communities_ok": len(self.config.active_communities),
            "posts_fetched": 0,
            "posts_new": 0,
            "points_new": 0,
            "failed_communities": [],
        }
        run_result = RunResult(run_id=run_id, generated_at=generated_at, stats=stats)
        await self.report(run_result)
        self.store.finish_run(run_id, "reported", stats)
        return run_result
