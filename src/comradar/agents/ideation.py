"""Ideation agent: turns observed friction into business hypotheses.

This agent has two jobs, and the second is the one that keeps it honest.

1. Propose new ideas that follow from what the communities actually said.
2. Hold those ideas, and the ideas already in the user's portfolio, against
   the same 25-point rubric the portfolio was scored with — so a new proposal
   can be compared to an existing one instead of merely sounding exciting.

The comparison is explicitly hypothetical. Community chatter is evidence that
a problem is felt, never evidence that a product will sell.
"""

from __future__ import annotations

from typing import Sequence

from ..config import AgentModelConfig
from ..llm import StructuredCaller
from ..models import IdeationResult, PortfolioIdea, SynthesisResult

SYSTEM_PROMPT = """\
당신은 관측된 생활 불편을 사업 가설로 바꾸는 사람이다. 동시에, 이미 존재하는
아이디어 목록을 이번 관측에 비추어 다시 판단한다.

평가 기준 (기존 포트폴리오와 동일한 척도를 쓴다. 비교 가능해야 하기 때문이다)
- 문제 절실함 1~5: 없으면 불편한가, 아니면 있으면 좋은가.
- 시장 크기 1~5: 같은 불편을 겪는 사람이 얼마나 되는가.
- 차별성 1~5: 무료 대체재(검색, 지도, 오픈채팅, 엑셀)를 이길 이유가 있는가.
- 실행 가능성 1~5: 규제·데이터 확보·양면 시장 문제를 넘을 수 있는가.
- 수익성 1~5: 누가 지불하는가. 고통 주체와 지불 주체가 같은가.
합계 25점. 후하게 주지 않는다. 대부분의 아이디어는 12~17점 사이다.

신규 아이디어 작성 규칙
- 반드시 분석 결과에 있는 테마에서 출발한다. source_theme은 그 테마 이름 그대로.
- demand_evidence에는 이번 관측의 숫자를 넣는다. 근거 없는 시장 수치를 만들지 않는다.
- wedge는 "가장 좁은 시작점" 하나여야 한다. 여러 사업을 동시에 시작하는 안은 감점 대상이다.
- 고통을 겪는 사람과 돈을 내는 사람이 다르면 그 사실을 problem이나 kill_criteria에 명시한다.
- first_test는 제품 없이 2주 안에 할 수 있어야 한다. "MVP를 만든다"는 검증이 아니다.
- kill_criteria는 숫자여야 한다. "반응이 없으면"이 아니라 "20명 중 3명 미만이면".
- 아이디어가 억지스러우면 개수를 줄인다. 빈 배열도 정답이 될 수 있다.

기존 포트폴리오 판정 규칙
- existing_idea는 주어진 목록에 있는 이름만 쓴다. 목록에 없는 것을 지어내지 않는다.
- 이번 관측과 관련이 없는 아이디어는 아예 다루지 않는다. 억지로 연결하지 않는다.
- '강한 지지'는 같은 불편이 여러 커뮤니티에서 반복 관측되었을 때만 쓴다.
- '반대 신호'는 관측이 그 아이디어의 전제를 부정할 때 쓴다. 사용자가 이미 다른
  방법으로 문제를 해결하고 있다는 관측이 대표적이다.
- observation에는 이번 관측 내용을 인용한다. 일반론을 쓰지 않는다.

지켜야 할 선
- 커뮤니티 언급은 문제가 존재한다는 증거이지, 제품이 팔린다는 증거가 아니다.
  이 구분을 흐리지 않는다.
- 한 구간의 관측으로 기존 아이디어를 폐기하라고 말하지 않는다. 판정은 신호이지 결론이 아니다.
- 모든 출력은 한국어로 쓴다."""


class IdeationAgent:
    """Proposes new bets and re-reads the existing ones against this window."""

    label = "ideation"

    def __init__(
        self,
        llm: StructuredCaller,
        cfg: AgentModelConfig,
        max_new_ideas: int = 3,
    ) -> None:
        self.llm = llm
        self.cfg = cfg
        self.max_new_ideas = max_new_ideas

    def build_prompt(
        self, synthesis: SynthesisResult, portfolio: Sequence[PortfolioIdea]
    ) -> str:
        if portfolio:
            scored = [idea for idea in portfolio if idea.score]
            span = (
                f"기존 점수 분포: {min(i.score for i in scored)}~{max(i.score for i in scored)}점"
                if scored
                else "기존 점수 정보 없음"
            )
            existing = "\n".join(idea.render() for idea in portfolio)
            portfolio_block = f"{span}\n{existing}"
        else:
            portfolio_block = "(기존 아이디어 목록을 불러오지 못했다. portfolio_verdicts는 빈 배열로 둔다.)"

        return (
            "### 이번 구간 분석 결과\n"
            + synthesis.model_dump_json(indent=2)
            + "\n\n### 기존 사업화 아이디어 포트폴리오\n"
            + portfolio_block
            + f"\n\n신규 아이디어는 최대 {self.max_new_ideas}개까지, 점수 높은 순으로 쓴다. "
            "기존 아이디어 판정은 이번 관측과 실제로 관련 있는 것만 고른다."
        )

    async def run(
        self, synthesis: SynthesisResult, portfolio: Sequence[PortfolioIdea]
    ) -> IdeationResult:
        if not synthesis.themes:
            return IdeationResult(
                new_ideas=[],
                portfolio_verdicts=[],
                ranking_note="",
                portfolio_gap="",
            )
        result = await self.llm.structured(
            cfg=self.cfg,
            system=SYSTEM_PROMPT,
            user=self.build_prompt(synthesis, portfolio),
            schema=IdeationResult,
            label=self.label,
        )
        result.new_ideas = sorted(result.new_ideas, key=lambda i: i.score.total, reverse=True)[
            : self.max_new_ideas
        ]
        # 목록에 없는 아이디어에 대한 판정은 버린다. 없는 것을 평가할 수는 없다.
        known = {idea.name for idea in portfolio}
        if known:
            result.portfolio_verdicts = [
                v for v in result.portfolio_verdicts if v.existing_idea in known
            ]
        return result
