"""Analyst agent: reads every collector's output and finds the shape of it.

This is the only agent that sees more than one community. It works on the
trailing window from the store, not just the current hour, because an hour of
new posts is too thin to tell a trend from a coincidence.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Dict, List, Sequence

from ..config import AgentModelConfig
from ..llm import StructuredCaller
from ..models import StoredPainPoint, SynthesisResult

SYSTEM_PROMPT = """\
당신은 여러 커뮤니티 관찰자들이 올린 불편 사례를 받아 하나의 그림으로 묶는 분석가다.

할 일
1. 표현이 달라도 같은 원인을 가리키는 사례를 하나의 테마로 묶는다.
   묶는 기준은 단어의 유사성이 아니라 **원인의 동일성**이다.
   '배달비가 비싸다'와 '최소주문금액이 올랐다'는 같은 테마일 수 있고,
   '앱이 느리다'와 '앱 디자인이 바뀌었다'는 다른 테마일 수 있다.
2. 각 테마마다 표면 증상이 아니라 구조적 원인을 한 문장으로 판단한다.
3. 이전 구간 테마 목록이 주어지면 momentum을 그것과 비교해서 정한다.
   목록에 없던 테마만 '신규'다. 비교 대상이 없으면 전부 '신규'로 둔다.
4. 테마를 영향도 순으로 정렬한다. 영향도는 언급 수만이 아니라
   심각도, 몇 개 커뮤니티에 걸쳐 있는지, 우회책이 있는지를 함께 본다.

지켜야 할 선
- communities에는 실제로 그 테마의 사례가 나온 커뮤니티 이름만 넣는다.
- representative_quotes와 evidence_urls는 입력에 있는 것만 쓴다. 만들어내지 않는다.
- mention_count는 실제로 묶인 사례 수와 일치해야 한다.
- 한 커뮤니티에서만, 한 번만 나온 사례를 '전국적 흐름'처럼 쓰지 않는다.
- cross_cutting_insight는 테마 요약의 재탕이 아니라, 테마들을 겹쳐 놓았을 때만
  보이는 것이어야 한다. 그런 것이 없으면 없다고 쓴다.
- 입력이 얇거나 한쪽 커뮤니티에 쏠려 있으면 coverage_warning에 그대로 적는다.
- 모든 출력은 한국어로 쓴다."""


def _format_points(points: Sequence[StoredPainPoint], limit: int) -> str:
    """Render the window for the prompt, densest signal first.

    Sorting by severity then engagement means that when the window has to be
    truncated, what falls off the end is the weakest evidence rather than the
    oldest.
    """
    ordered = sorted(points, key=lambda p: (p.severity, p.engagement), reverse=True)[:limit]
    by_community: Dict[str, List[StoredPainPoint]] = {}
    for point in ordered:
        by_community.setdefault(point.community, []).append(point)

    blocks: List[str] = []
    for community, items in by_community.items():
        lines = [f"## {community} ({len(items)}건)"]
        for point in items:
            lines.append(
                f"- [{point.domain} / 심각도 {point.severity}"
                f"{' / 반복' if point.is_recurring else ''} / 반응 {point.engagement}] "
                f"{point.title}: {point.summary}"
            )
            lines.append(f"  대상: {point.who or '불명'} / 우회책: {point.workaround or '없음'}")
            if point.evidence_quote:
                lines.append(f'  인용: "{point.evidence_quote}"')
            if point.source_url:
                lines.append(f"  출처: {point.source_url}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


class SynthesisAgent:
    """Clusters a window of pain points into ranked themes."""

    label = "synthesizer"

    def __init__(
        self,
        llm: StructuredCaller,
        cfg: AgentModelConfig,
        max_themes: int = 8,
        max_points_in_prompt: int = 200,
    ) -> None:
        self.llm = llm
        self.cfg = cfg
        self.max_themes = max_themes
        self.max_points_in_prompt = max_points_in_prompt

    def build_prompt(
        self,
        points: Sequence[StoredPainPoint],
        previous_themes: Sequence[dict],
        window_hours: int,
    ) -> str:
        domains = Counter(p.domain for p in points)
        communities = Counter(p.community for p in points)
        header = [
            f"관측 구간: 최근 {window_hours}시간",
            f"총 사례 수: {len(points)}건",
            f"커뮤니티별: {', '.join(f'{k} {v}건' for k, v in communities.most_common())}",
            f"영역별: {', '.join(f'{k} {v}건' for k, v in domains.most_common())}",
            f"테마는 최대 {self.max_themes}개까지.",
        ]
        previous = (
            json.dumps(list(previous_themes), ensure_ascii=False, indent=2)
            if previous_themes
            else "(이전 구간 기록 없음 — 모든 테마를 '신규'로 둔다)"
        )
        return (
            "\n".join(header)
            + "\n\n### 이전 구간 테마\n"
            + previous
            + "\n\n### 이번 구간 사례\n"
            + _format_points(points, self.max_points_in_prompt)
        )

    async def run(
        self,
        points: Sequence[StoredPainPoint],
        previous_themes: Sequence[dict],
        window_hours: int,
    ) -> SynthesisResult:
        if not points:
            return SynthesisResult(
                themes=[],
                cross_cutting_insight="",
                contrarian_note="",
                coverage_warning="관측 구간에 수집된 사례가 없습니다.",
            )
        result = await self.llm.structured(
            cfg=self.cfg,
            system=SYSTEM_PROMPT,
            user=self.build_prompt(points, previous_themes, window_hours),
            schema=SynthesisResult,
            label=self.label,
        )
        result.themes = result.themes[: self.max_themes]
        return result
