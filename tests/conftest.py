"""Shared fixtures. Nothing in the test suite touches the network or the API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Type

import pytest

from comradar.config import AgentModelConfig
from comradar.models import (
    BusinessIdea,
    CommunityScan,
    IdeaScore,
    IdeationResult,
    PainPoint,
    PortfolioIdea,
    PortfolioVerdict,
    RawPost,
    ReportDraft,
    ReportTheme,
    SynthesisResult,
    Theme,
)


class FakeCaller:
    """A `StructuredCaller` that returns canned objects and records prompts."""

    def __init__(self, responses: Dict[Any, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: List[dict] = []

    async def structured(self, *, cfg, system, user, schema: Type, label: str):
        self.calls.append({"schema": schema, "system": system, "user": user, "label": label})
        if schema in self.responses:
            return self.responses[schema]
        raise AssertionError(f"준비되지 않은 스키마 요청: {schema.__name__}")


@pytest.fixture
def model_cfg() -> AgentModelConfig:
    return AgentModelConfig(model="claude-opus-5", effort="low", max_tokens=4096)


@pytest.fixture
def posts() -> List[RawPost]:
    return [
        RawPost(
            post_id="p1",
            community="테스트 커뮤니티",
            title="분리배출 규칙이 동네마다 다름",
            body="이사할 때마다 다시 검색합니다.",
            url="https://example.com/p1",
            score=10,
            num_comments=5,
            created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        ),
        RawPost(
            post_id="p2",
            community="테스트 커뮤니티",
            title="병원 예약 전화만 됨",
            body="근무 중에 전화를 못 겁니다.",
            url="https://example.com/p2",
            score=4,
            num_comments=20,
            created_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        ),
    ]


@pytest.fixture
def scan() -> CommunityScan:
    return CommunityScan(
        community_mood="생활 행정 불만이 잦음",
        notes="",
        pain_points=[
            PainPoint(
                post_index=0,
                title="분리배출 규칙 파편화",
                summary="지자체마다 기준이 달라 이사 때마다 다시 배운다.",
                domain="행정·제도",
                who="이사 잦은 1인가구",
                severity=3,
                workaround="구청 홈페이지 검색",
                evidence_quote="이사할 때마다 다시 검색합니다.",
                is_recurring=True,
            ),
            PainPoint(
                post_index=99,  # 존재하지 않는 인덱스 — 버려져야 한다
                title="유령 항목",
                summary="근거 없는 항목",
                domain="기타",
                who="아무도",
                severity=5,
                workaround="",
                evidence_quote="없음",
                is_recurring=False,
            ),
        ],
    )


@pytest.fixture
def synthesis() -> SynthesisResult:
    return SynthesisResult(
        themes=[
            Theme(
                theme="생활 행정의 지역별 파편화",
                one_liner="같은 규칙이 지자체마다 달라 매번 다시 배워야 한다.",
                domain="행정·제도",
                communities=["테스트 커뮤니티"],
                mention_count=3,
                severity=3,
                momentum="신규",
                root_cause="기준을 정하는 주체와 안내하는 주체가 분리되어 있다.",
                solution_gap="통합 안내 서비스가 없다",
                representative_quotes=["이사할 때마다 다시 검색합니다."],
                evidence_urls=["https://example.com/p1"],
            )
        ],
        cross_cutting_insight="불편의 원인이 정보 부재가 아니라 정보의 분산에 있다.",
        contrarian_note="",
        coverage_warning="",
    )


@pytest.fixture
def draft() -> ReportDraft:
    return ReportDraft(
        headline="생활 행정 정보가 흩어져 매번 다시 찾는다",
        tldr=["규칙이 지역마다 다르다", "사람들은 검색으로 때운다", "통합 안내가 없다"],
        top_themes=[
            ReportTheme(
                rank=1,
                theme="생활 행정의 지역별 파편화",
                so_what="반복 검색 비용이 계속 발생한다.",
                evidence="1개 커뮤니티에서 3건 관측",
                quote="이사할 때마다 다시 검색합니다.",
                momentum="신규",
            )
        ],
        rising_signals=["병원 예약 채널 부재"],
        decision_prompt="지자체 규칙 통합 조회를 2주 실험으로 검증할 것인가?",
        what_did_not_change="",
    )


@pytest.fixture
def portfolio() -> List[PortfolioIdea]:
    return [
        PortfolioIdea(
            name="카페 잔여석 지도·웨이팅",
            one_liner="실시간 잔여 좌석 표시와 원격 대기 플랫폼",
            strength="보편적 페인포인트",
            risk="POS로는 좌석 점유를 알 수 없음",
            score=13,
        ),
        PortfolioIdea(name="BudgetFlow 경비 정산·세무 준비", score=15),
    ]


@pytest.fixture
def ideation() -> IdeationResult:
    return IdeationResult(
        new_ideas=[
            BusinessIdea(
                name="분리배출 규칙 통합 조회",
                source_theme="생활 행정의 지역별 파편화",
                problem="이사가 잦은 1인가구가 매번 지자체 기준을 다시 찾는다.",
                solution="주소를 넣으면 그 지역 기준만 보여주는 조회 서비스",
                target="최근 1년 내 이사한 수도권 1인가구",
                wedge="지자체 3곳의 배출 기준만 정리한 단일 페이지",
                revenue_model="지자체 대상 안내 위탁, 이사 서비스 제휴",
                demand_evidence="1개 커뮤니티에서 3건, 모두 반복 불편으로 분류",
                score=IdeaScore(
                    problem_urgency=3,
                    market_size=3,
                    differentiation=2,
                    feasibility=4,
                    profitability=2,
                ),
                first_test="지자체 3곳 페이지를 만들어 검색 유입과 저장률을 2주간 측정",
                kill_criteria="2주간 순방문 200명 미만이거나 재방문 5% 미만이면 접는다",
            )
        ],
        portfolio_verdicts=[
            PortfolioVerdict(
                existing_idea="카페 잔여석 지도·웨이팅",
                signal="신호 없음",
                observation="이번 구간 사례 중 좌석 관련 언급이 없었다.",
                action="이번 구간 근거로는 판단하지 않는다. 다음 구간까지 보류.",
            ),
            PortfolioVerdict(
                existing_idea="목록에 없는 아이디어",
                signal="강한 지지",
                observation="지어낸 항목이므로 필터링되어야 한다.",
                action="버려져야 한다",
            ),
        ],
        ranking_note="신규 아이디어는 14점으로 기존 중위권과 같은 구간이다.",
        portfolio_gap="생활 행정 영역을 다루는 기존 아이디어가 없다.",
    )
