"""모델 호출 없이 보고서 레이아웃만 확인하는 스크립트.

    python scripts/demo_report.py

reports/sample.md 와 reports/sample.html 을 만든다. 내용은 고정된 예시이고,
목적은 실제 보고서가 어떤 모양으로 나오는지 보는 것이다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from comradar.models import (  # noqa: E402
    BusinessIdea,
    IdeaScore,
    IdeationResult,
    PortfolioVerdict,
    ReportDraft,
    ReportTheme,
    SynthesisResult,
    Theme,
)
from comradar.render import render_html, render_markdown  # noqa: E402

SYNTHESIS = SynthesisResult(
    themes=[
        Theme(
            theme="생활 행정 정보의 지역별 파편화",
            one_liner="같은 규칙이 지자체마다 달라 이사할 때마다 다시 배워야 한다.",
            domain="행정·제도",
            communities=["클리앙 모두의공원", "디시인사이드 실시간베스트"],
            mention_count=7,
            severity=3,
            momentum="상승",
            root_cause="규칙을 정하는 주체와 안내하는 주체가 분리되어 있고, 통합 창구가 없다.",
            solution_gap="지자체 홈페이지는 있지만 주소 기준으로 한 번에 확인할 방법이 없다",
            representative_quotes=["이사할 때마다 분리배출 규칙을 다시 검색합니다."],
            evidence_urls=["https://example.com/1", "https://example.com/2"],
        ),
        Theme(
            theme="전화로만 가능한 예약",
            one_liner="근무 시간에 전화를 걸 수 없는 사람은 예약 자체가 막힌다.",
            domain="건강·의료",
            communities=["클리앙 모두의공원", "r/mildlyinfuriating"],
            mention_count=5,
            severity=4,
            momentum="신규",
            root_cause="예약 시스템 도입 비용을 개별 사업장이 감당하지 못한다.",
            solution_gap="대형 병원만 앱 예약이 되고 동네 의원은 여전히 전화뿐이다",
            representative_quotes=["근무 중에 전화를 못 겁니다."],
            evidence_urls=["https://example.com/3"],
        ),
    ],
    cross_cutting_insight=(
        "두 테마 모두 정보가 없어서 생긴 문제가 아니라, 정보가 흩어져 있고 "
        "접근 채널이 하나뿐이어서 생긴 문제다. 사람들이 원하는 것은 새 정보가 아니라 창구다."
    ),
    contrarian_note="언급 수는 분리배출이 많지만, 실제 손실이 큰 쪽은 예약 문제다.",
    coverage_warning="해외 커뮤니티 2곳의 사례가 전체의 30%로, 국내 편향이 있다.",
)

IDEATION = IdeationResult(
    new_ideas=[
        BusinessIdea(
            name="동네 의원 예약 대행",
            source_theme="전화로만 가능한 예약",
            problem="근무 중 전화가 어려운 직장인이 동네 의원 예약을 포기한다.",
            solution="문자로 요청하면 대신 전화해 예약을 잡아 주는 서비스",
            target="주 5일 사무직, 반차 없이 진료가 필요한 사람",
            wedge="한 개 구의 이비인후과·정형외과 20곳만 대상으로 시작",
            revenue_model="건당 수수료. 이후 의원 측 예약 관리 구독으로 전환",
            demand_evidence="2개 커뮤니티에서 5건, 평균 심각도 4로 이번 구간 최고",
            score=IdeaScore(
                problem_urgency=4,
                market_size=3,
                differentiation=2,
                feasibility=4,
                profitability=2,
            ),
            first_test="구글폼과 사람이 직접 전화하는 방식으로 2주간 30건을 처리해 본다",
            kill_criteria="2주간 유료 요청 10건 미만이거나 재요청률 20% 미만이면 접는다",
        ),
        BusinessIdea(
            name="주소 기준 생활규칙 조회",
            source_theme="생활 행정 정보의 지역별 파편화",
            problem="이사한 1인가구가 분리배출·주차·소음 기준을 매번 다시 찾는다.",
            solution="주소를 넣으면 그 지역 규칙만 한 장으로 보여주는 페이지",
            target="최근 1년 내 이사한 수도권 1인가구",
            wedge="이사 수요가 많은 자치구 3곳의 분리배출 기준만 먼저 정리",
            revenue_model="이사·청소 업체 제휴 송출, 이후 지자체 안내 위탁",
            demand_evidence="2개 커뮤니티에서 7건, 전부 반복 불편으로 분류",
            score=IdeaScore(
                problem_urgency=3,
                market_size=3,
                differentiation=2,
                feasibility=4,
                profitability=2,
            ),
            first_test="자치구 3곳 페이지를 만들고 2주간 검색 유입과 저장률을 본다",
            kill_criteria="2주간 순방문 200명 미만이면 접는다",
        ),
    ],
    portfolio_verdicts=[
        PortfolioVerdict(
            existing_idea="카페 잔여석 지도·웨이팅",
            signal="신호 없음",
            observation="이번 구간 사례 12건 중 좌석·대기 관련 언급이 없었다.",
            action="이번 구간 근거로는 판단하지 않는다. 다음 구간까지 보류한다.",
        ),
        PortfolioVerdict(
            existing_idea="BudgetFlow 경비 정산·세무 준비",
            signal="약한 지지",
            observation="'서류를 대신 처리해 달라'는 요청이 행정 테마에서 3건 나왔다.",
            action="세무가 아니라 '대신 처리해 주는 서비스' 각도로 인터뷰 질문을 넓힌다.",
        ),
        PortfolioVerdict(
            existing_idea="지하철 역별 데이트코스 추천",
            signal="반대 신호",
            observation="장소 탐색 관련 언급은 전부 이미 지도 앱으로 해결하고 있었다.",
            action="단일 장소 추천이 아니라 '코스 생성'으로 좁히는 안을 먼저 검증한다.",
        ),
    ],
    ranking_note="신규 후보 두 건은 15점과 14점으로, 기존 포트폴리오의 중위권과 같은 구간이다.",
    portfolio_gap="기존 10건 중 생활 행정과 예약 대행을 다루는 아이디어가 없다.",
)

DRAFT = ReportDraft(
    headline="사람들이 원하는 것은 정보가 아니라 창구다",
    tldr=[
        "행정 규칙 파편화가 2개 커뮤니티 7건으로 이번 구간 최다.",
        "전화 예약 문제는 건수는 적지만 심각도 평균 4로 가장 높다.",
        "기존 포트폴리오 10건 중 이 두 영역을 다루는 것은 없다.",
    ],
    top_themes=[
        ReportTheme(
            rank=1,
            theme="생활 행정 정보의 지역별 파편화",
            so_what="이사 인구가 매번 같은 검색을 반복하며 시간을 쓴다.",
            evidence="2개 커뮤니티에서 7건, 전부 반복 불편",
            quote="이사할 때마다 분리배출 규칙을 다시 검색합니다.",
            momentum="상승",
        ),
        ReportTheme(
            rank=2,
            theme="전화로만 가능한 예약",
            so_what="근무 시간에 전화가 어려운 사람은 진료 자체를 미룬다.",
            evidence="2개 커뮤니티에서 5건, 평균 심각도 4",
            quote="근무 중에 전화를 못 겁니다.",
            momentum="신규",
        ),
    ],
    rising_signals=[
        "'대신 해 달라'는 표현이 서로 다른 영역에서 반복 등장",
        "해외 커뮤니티에서도 같은 예약 불편이 관측",
    ],
    decision_prompt="예약 대행을 2주 수동 실험으로 검증할 것인가, 다음 구간 데이터를 더 볼 것인가?",
    what_did_not_change="분리배출 테마는 지난 구간에 이어 두 번째로 상위에 올랐다.",
)

STATS = {
    "window_hours": 4,
    "report_interval_hours": 4,
    "communities_total": 5,
    "communities_ok": 4,
    "posts_new": 63,
    "points_window": 12,
    "portfolio_size": 10,
    "failed_communities": ["뽐뿌 자유게시판(응답 403)"],
    "usage": "7회 호출 / 입력 48,210 토큰 (캐시 적중 31,004) / 출력 6,880 토큰",
}


def main() -> None:
    generated_at = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Seoul"))
    out = ROOT / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample.md").write_text(
        render_markdown(DRAFT, SYNTHESIS, IDEATION, STATS, generated_at), encoding="utf-8"
    )
    (out / "sample.html").write_text(
        render_html(DRAFT, SYNTHESIS, IDEATION, STATS, generated_at), encoding="utf-8"
    )
    print(f"작성: {out / 'sample.md'}, {out / 'sample.html'}")


if __name__ == "__main__":
    main()
