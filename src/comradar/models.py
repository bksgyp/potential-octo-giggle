"""Data models for the community monitoring pipeline.

Two families live here:

* Plain records (`RawPost`, `StoredPainPoint`) that move between the fetch
  layer, the SQLite store and the agents. These never touch the model.
* LLM-facing schemas (`CommunityScan`, `SynthesisResult`, `ReportDraft`) that
  are handed to the Messages API as structured-output schemas. Keep every
  field required and avoid `Optional` here: the structured-output encoder is
  strict, and a nullable branch is one more thing for the model to get wrong.
  "Nothing to report" is expressed with an empty string or an empty list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal

from pydantic import BaseModel, Field

# Domains of everyday-life friction. Kept short and mutually recognisable so
# that themes from different communities land in the same bucket.
Domain = Literal[
    "주거·부동산",
    "이동·교통",
    "돈·금융",
    "일·직장",
    "건강·의료",
    "육아·돌봄",
    "쇼핑·소비",
    "행정·제도",
    "디지털·기기",
    "음식·식생활",
    "관계·커뮤니케이션",
    "학습·교육",
    "여가·취미",
    "기타",
]

Momentum = Literal["신규", "급상승", "상승", "유지", "하락"]


# --------------------------------------------------------------------------
# Plain records
# --------------------------------------------------------------------------


class RawPost(BaseModel):
    """One post or thread fetched from a community, before any analysis."""

    post_id: str
    community: str
    title: str
    body: str = ""
    url: str = ""
    author: str = ""
    score: int = 0
    num_comments: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def engagement(self) -> int:
        """Cheap proxy for how much a post resonated."""
        return self.score + 2 * self.num_comments

    def render(self, index: int, body_chars: int = 1200) -> str:
        """Render the post for the collector prompt.

        `index` is the handle the model uses to point back at this post, so the
        pipeline can attach a real URL to every extracted pain point instead of
        trusting the model to copy one.
        """
        body = self.body.strip().replace("\r", "")
        if len(body) > body_chars:
            body = body[:body_chars] + "…(생략)"
        parts = [
            f"[{index}] 제목: {self.title.strip()}",
            f"    반응: 추천 {self.score} / 댓글 {self.num_comments}",
        ]
        if body:
            parts.append(f"    본문: {body}")
        return "\n".join(parts)


class StoredPainPoint(BaseModel):
    """A pain point after it has been anchored back to its source post."""

    run_id: str
    community: str
    observed_at: datetime
    title: str
    summary: str
    domain: str
    severity: int
    who: str
    workaround: str
    evidence_quote: str
    is_recurring: bool
    source_url: str
    source_title: str
    engagement: int


# --------------------------------------------------------------------------
# Collector agent (one instance per community)
# --------------------------------------------------------------------------


class PainPoint(BaseModel):
    """A single piece of everyday-life friction extracted from one post."""

    post_index: int = Field(
        description="근거가 된 게시물의 대괄호 번호. 반드시 입력에 존재하는 번호여야 한다."
    )
    title: str = Field(description="불편의 핵심을 담은 20자 이내 한 줄")
    summary: str = Field(description="무엇이 왜 불편한지 1~2문장")
    domain: Domain
    who: str = Field(description="누가 겪는 문제인지. 예: '자취 2년차 1인가구'")
    severity: int = Field(
        ge=1, le=5, description="1=사소한 짜증, 3=반복적 시간·비용 손실, 5=생계·건강 위협"
    )
    workaround: str = Field(description="현재 사람들이 쓰는 우회책. 없으면 빈 문자열")
    evidence_quote: str = Field(description="원문에서 그대로 인용한 한 문장")
    is_recurring: bool = Field(description="일회성 사건이 아니라 반복되는 불편이면 true")


class CommunityScan(BaseModel):
    """The collector agent's report for one community, for one run."""

    community_mood: str = Field(description="이번 배치에서 읽히는 커뮤니티 분위기 한 줄")
    pain_points: List[PainPoint]
    notes: str = Field(description="분석을 방해한 요소가 있으면 기록. 없으면 빈 문자열")


# --------------------------------------------------------------------------
# Synthesis agent (single instance, consumes every collector's output)
# --------------------------------------------------------------------------


class Theme(BaseModel):
    """A cluster of pain points that describe the same underlying friction."""

    theme: str = Field(description="테마 이름. 25자 이내")
    one_liner: str = Field(description="이 테마가 무엇인지 한 문장")
    domain: Domain
    communities: List[str] = Field(description="이 테마가 관측된 커뮤니티 이름 목록")
    mention_count: int = Field(ge=1, description="이 테마로 묶인 불편 사례 수")
    severity: int = Field(ge=1, le=5, description="묶인 사례들의 대표 심각도")
    momentum: Momentum = Field(description="이전 관측 구간 대비 추세")
    root_cause: str = Field(description="표면 증상이 아닌 구조적 원인에 대한 판단")
    solution_gap: str = Field(description="이미 있는 해법이 왜 부족한지. 없으면 '기존 해법 없음'")
    representative_quotes: List[str] = Field(description="서로 다른 사례에서 뽑은 인용 1~3개")
    evidence_urls: List[str] = Field(description="근거 게시물 URL 1~3개")


class SynthesisResult(BaseModel):
    """The analyst agent's cross-community picture."""

    themes: List[Theme] = Field(description="영향도 순으로 정렬된 테마")
    cross_cutting_insight: str = Field(
        description="여러 테마를 관통하는 한 가지 통찰. 테마 요약의 반복이 아니어야 한다."
    )
    contrarian_note: str = Field(
        description="숫자는 크지만 실제로는 덜 중요하거나, 작지만 중요한 신호. 없으면 빈 문자열"
    )
    coverage_warning: str = Field(
        description="데이터가 얇거나 한쪽으로 치우쳤으면 그 사실. 문제 없으면 빈 문자열"
    )


# --------------------------------------------------------------------------
# Report agent (single instance, writes the one-pager)
# --------------------------------------------------------------------------


class ReportTheme(BaseModel):
    rank: int = Field(ge=1)
    theme: str
    so_what: str = Field(description="독자가 왜 신경 써야 하는지 한 문장")
    evidence: str = Field(description="관측 근거를 숫자와 함께 한 문장으로")
    quote: str = Field(description="가장 잘 드러내는 인용 한 줄")
    momentum: Momentum


class ReportDraft(BaseModel):
    """Content for the one-page report. Layout is done in code, not here."""

    headline: str = Field(description="이번 구간을 한 문장으로 요약한 제목. 40자 이내")
    tldr: List[str] = Field(description="정확히 3개의 요약 불릿. 각 40자 이내")
    top_themes: List[ReportTheme] = Field(description="상위 5개 이내")
    rising_signals: List[str] = Field(description="아직 작지만 커지는 신호 2~3개")
    decision_prompt: str = Field(
        description="이 보고서를 읽고 지금 내려야 할 결정 하나를 질문 형태로. 한 문장."
    )
    what_did_not_change: str = Field(
        description="지난 구간과 비교해 달라지지 않은 것. 비교 대상이 없으면 빈 문자열"
    )


# --------------------------------------------------------------------------
# Ideation agent (single instance, turns friction into business hypotheses)
# --------------------------------------------------------------------------


class PortfolioIdea(BaseModel):
    """One idea from the existing portfolio (Notion page or local snapshot)."""

    name: str
    one_liner: str = ""
    strength: str = ""
    risk: str = ""
    score: int = 0  # 25점 만점. 0이면 미평가.

    def render(self) -> str:
        parts = [f"- {self.name}"]
        if self.one_liner:
            parts.append(f"정의: {self.one_liner}")
        if self.strength:
            parts.append(f"강점: {self.strength}")
        if self.risk:
            parts.append(f"리스크: {self.risk}")
        if self.score:
            parts.append(f"기존 점수: {self.score}/25")
        return " / ".join(parts)


class IdeaScore(BaseModel):
    """The existing portfolio's rubric, reused so scores are comparable."""

    problem_urgency: int = Field(ge=1, le=5, description="문제 절실함")
    market_size: int = Field(ge=1, le=5, description="시장 크기")
    differentiation: int = Field(ge=1, le=5, description="차별성")
    feasibility: int = Field(ge=1, le=5, description="실행 가능성")
    profitability: int = Field(ge=1, le=5, description="수익성")

    @property
    def total(self) -> int:
        return (
            self.problem_urgency
            + self.market_size
            + self.differentiation
            + self.feasibility
            + self.profitability
        )


class BusinessIdea(BaseModel):
    """A business hypothesis derived from an observed theme."""

    name: str = Field(description="아이디어 이름. 20자 이내")
    source_theme: str = Field(description="근거가 된 테마 이름. 분석 결과에 있는 것만.")
    problem: str = Field(description="누구의 어떤 불편인지 한 문장")
    solution: str = Field(description="무엇을 만들 것인지 한 문장")
    target: str = Field(description="첫 고객 세그먼트. '모두'는 답이 아니다.")
    wedge: str = Field(description="가장 좁게 시작할 진입점 하나")
    revenue_model: str = Field(description="누가 무엇에 얼마를 내는가")
    demand_evidence: str = Field(description="이번 관측에서 나온 수요 근거. 숫자를 포함한다.")
    score: IdeaScore
    first_test: str = Field(description="제품 없이 2주 안에 할 수 있는 검증 한 가지")
    kill_criteria: str = Field(description="이 결과가 나오면 접는다는 기준. 숫자로.")


class PortfolioVerdict(BaseModel):
    """This window's evidence, applied to one idea already in the portfolio."""

    existing_idea: str = Field(description="기존 포트폴리오 아이디어 이름. 목록에 있는 것만.")
    signal: Literal["강한 지지", "약한 지지", "신호 없음", "반대 신호"]
    observation: str = Field(description="그렇게 판단한 근거를 이번 관측에서 인용")
    action: str = Field(description="이 아이디어에 대해 지금 할 일 한 가지")


class IdeationResult(BaseModel):
    """The ideation agent's output: new bets, and a read on the existing ones."""

    new_ideas: List[BusinessIdea] = Field(description="점수 높은 순으로 최대 3개")
    portfolio_verdicts: List[PortfolioVerdict] = Field(
        description="기존 아이디어에 대한 판정. 관측과 관련 있는 것만 고른다."
    )
    ranking_note: str = Field(
        description="신규 아이디어가 기존 포트폴리오 점수대의 어디에 놓이는지 한두 문장"
    )
    portfolio_gap: str = Field(
        description="이번 관측이 보여준, 기존 포트폴리오가 다루지 않는 영역. 없으면 빈 문자열"
    )
