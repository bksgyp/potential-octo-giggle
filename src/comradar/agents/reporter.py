"""Report agent: writes the one-pager the human actually reads.

The agent writes content, not layout. Page structure lives in `render.py`, so
"한 장" is enforced by the renderer and the field limits rather than by asking
the model nicely to be brief.
"""

from __future__ import annotations

import json
from typing import Sequence

from ..config import AgentModelConfig
from ..llm import StructuredCaller
from ..models import IdeationResult, ReportDraft, SynthesisResult

SYSTEM_PROMPT = """\
당신은 분석 결과를 받아 의사결정자가 읽을 A4 한 장짜리 보고서를 쓰는 사람이다.
읽는 사람은 커뮤니티를 직접 보지 않는다. 이 한 장이 그들이 보는 전부다.

원칙
- 결론을 먼저 쓴다. headline은 이번 구간에서 가장 중요한 사실 하나여야 하고,
  '여러 불편이 관측되었다' 같은 무내용한 문장이면 안 된다.
- 모든 주장에 숫자를 붙인다. evidence는 '몇 개 커뮤니티에서 몇 건'처럼 센 값을 쓴다.
- 인용은 분석 결과에 있는 것만 쓴다. 다듬거나 새로 짓지 않는다.
- 사업 아이디어 자체는 쓰지 않는다. 그 부분은 사업화 에이전트가 이미 작성했고
  보고서에 그대로 실린다. 당신은 그 내용을 headline과 decision_prompt에
  반영하기만 한다.
- decision_prompt는 읽는 사람이 오늘 답해야 할 질문 하나여야 한다.
  '검토가 필요하다' 같은 미루는 문장은 실패다.
- 데이터가 얇으면 얇다고 쓴다. 얇은 데이터 위에 센 결론을 얹지 않는다.
- 길이 제한을 지킨다. 한 장을 넘기면 아무도 읽지 않는다.
- 모든 출력은 한국어로 쓴다."""


class ReportAgent:
    """Produces the content of the one-page report."""

    label = "reporter"

    def __init__(self, llm: StructuredCaller, cfg: AgentModelConfig) -> None:
        self.llm = llm
        self.cfg = cfg

    def build_prompt(
        self, synthesis: SynthesisResult, ideation: IdeationResult, stats: dict
    ) -> str:
        return (
            "### 이번 실행 통계\n"
            + json.dumps(stats, ensure_ascii=False, indent=2)
            + "\n\n### 분석가 결과\n"
            + synthesis.model_dump_json(indent=2)
            + "\n\n### 사업화 에이전트 결과 (참고용, 보고서에 그대로 실린다)\n"
            + ideation.model_dump_json(indent=2)
            + "\n\n위 결과만 근거로 한 장짜리 보고서 내용을 작성하라. "
            "top_themes는 5개를 넘기지 말고, 분석가가 정한 순위를 뒤집지 마라."
        )

    async def run(
        self, synthesis: SynthesisResult, ideation: IdeationResult, stats: dict
    ) -> ReportDraft:
        if not synthesis.themes:
            return ReportDraft(
                headline="이번 구간에 보고할 만한 불편 신호가 없습니다",
                tldr=[
                    "수집된 신규 사례가 없거나 분석 대상에 미달했습니다.",
                    f"점검 대상 커뮤니티 {stats.get('communities_total', 0)}곳.",
                    "소스 설정과 수집 오류를 먼저 확인하세요.",
                ],
                top_themes=[],
                rising_signals=[],
                decision_prompt="수집 파이프라인을 고칠 것인가, 대상 커뮤니티를 바꿀 것인가?",
                what_did_not_change=synthesis.coverage_warning,
            )
        draft = await self.llm.structured(
            cfg=self.cfg,
            system=SYSTEM_PROMPT,
            user=self.build_prompt(synthesis, ideation, stats),
            schema=ReportDraft,
            label=self.label,
        )
        draft.top_themes = draft.top_themes[:5]
        draft.tldr = draft.tldr[:3]
        return draft
