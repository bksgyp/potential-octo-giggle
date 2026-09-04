"""Collector agent: one dedicated instance per community.

Each collector reads only its own community and knows nothing about the others.
That isolation is the point. A collector that could see every community would
start writing cross-community conclusions, which is the analyst's job, and its
prompt would stop fitting in a cache-friendly stable prefix.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Sequence, Tuple

from ..config import AgentModelConfig, CommunityConfig
from ..llm import StructuredCaller
from ..models import CommunityScan, RawPost, StoredPainPoint

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 하나의 온라인 커뮤니티만 전담해서 읽는 관찰자다. 목표는 단 하나,
사람들이 **실생활에서 실제로 겪는 불편**을 원문에서 찾아내는 것이다.

무엇이 '실생활 불편'인가
- 반복되는 시간·비용·감정 손실. 예: 재활용 분리배출 규칙이 지자체마다 달라 매번 검색한다.
- 제도나 서비스가 사용자의 실제 생활 패턴과 어긋나는 지점.
- 대안이 없어서 사람들이 이상한 우회책을 쓰고 있는 상황.

무엇이 아닌가
- 정치·연예·스포츠 논평, 시사 뉴스에 대한 감상.
- 특정 제품의 단순 호불호나 취향 논쟁.
- 홍보글, 판매글, 구인글, 자동 생성된 공지.
- 게시물에 근거가 없는 당신의 추측. 원문에 없는 내용은 쓰지 않는다.

작성 규칙
- 각 항목의 post_index는 반드시 입력에 실제로 존재하는 대괄호 번호여야 한다.
- evidence_quote는 해당 게시물 원문에서 **그대로** 따온 한 문장이어야 한다.
  원문을 다듬거나 요약해서 인용문에 넣지 않는다.
- 같은 게시물에서 같은 불편을 두 번 뽑지 않는다. 서로 다른 게시물이 같은 불편을
  말하면 더 구체적인 쪽 하나만 남긴다.
- severity는 인상이 아니라 근거로 매긴다. 원문에 손실의 크기가 드러나지 않으면 3을 넘기지 않는다.
- 건질 것이 없으면 pain_points를 빈 배열로 두고 notes에 이유를 한 줄로 적는다.
  억지로 채우는 것이 아무것도 못 찾는 것보다 나쁘다.
- 모든 서술은 한국어로 쓴다. 원문이 다른 언어여도 요약은 한국어로 하고,
  evidence_quote만 원문 그대로 둔다."""


class CollectorAgent:
    """Turns one community's new posts into anchored pain points."""

    def __init__(
        self,
        community: CommunityConfig,
        llm: StructuredCaller,
        cfg: AgentModelConfig,
        max_points: int = 12,
    ) -> None:
        self.community = community
        self.llm = llm
        self.cfg = cfg
        self.max_points = max_points

    @property
    def label(self) -> str:
        return f"collector:{self.community.slug}"

    def build_prompt(self, posts: Sequence[RawPost]) -> str:
        rendered = "\n\n".join(post.render(i) for i, post in enumerate(posts))
        return (
            f"커뮤니티: {self.community.name}\n"
            f"주 사용 언어: {self.community.locale}\n"
            f"수집 시각: {datetime.now(timezone.utc).astimezone().isoformat(timespec='minutes')}\n"
            f"신규 게시물 {len(posts)}건. 최대 {self.max_points}개의 불편을 뽑아라.\n\n"
            f"--- 게시물 시작 ---\n{rendered}\n--- 게시물 끝 ---"
        )

    async def run(
        self, posts: Sequence[RawPost], run_id: str
    ) -> Tuple[CommunityScan, List[StoredPainPoint]]:
        """Analyse `posts` and return the raw scan plus source-anchored points."""
        if not posts:
            empty = CommunityScan(
                community_mood="",
                pain_points=[],
                notes="이번 구간에 신규 게시물이 없었습니다.",
            )
            return empty, []

        scan = await self.llm.structured(
            cfg=self.cfg,
            system=SYSTEM_PROMPT,
            user=self.build_prompt(posts),
            schema=CommunityScan,
            label=self.label,
        )
        return scan, self._anchor(scan, posts, run_id)

    def _anchor(
        self, scan: CommunityScan, posts: Sequence[RawPost], run_id: str
    ) -> List[StoredPainPoint]:
        """Attach each pain point to its real source post.

        The URL and engagement numbers come from the fetched post, never from
        the model. A pain point that points at a post index outside the batch is
        dropped rather than guessed at: an unanchored claim is worse than a
        missing one, because the report cites its evidence.
        """
        observed_at = datetime.now(timezone.utc)
        anchored: List[StoredPainPoint] = []
        for point in scan.pain_points[: self.max_points]:
            if not 0 <= point.post_index < len(posts):
                logger.warning(
                    "[%s] 존재하지 않는 post_index %s를 가리키는 항목을 버렸습니다: %s",
                    self.label,
                    point.post_index,
                    point.title,
                )
                continue
            source = posts[point.post_index]
            anchored.append(
                StoredPainPoint(
                    run_id=run_id,
                    community=self.community.name,
                    observed_at=observed_at,
                    title=point.title,
                    summary=point.summary,
                    domain=point.domain,
                    severity=point.severity,
                    who=point.who,
                    workaround=point.workaround,
                    evidence_quote=point.evidence_quote,
                    is_recurring=point.is_recurring,
                    source_url=source.url,
                    source_title=source.title,
                    engagement=source.engagement(),
                )
            )
        return anchored
