from datetime import datetime, timezone

from comradar.render import render_html, render_markdown

STATS = {
    "window_hours": 4,
    "communities_ok": 5,
    "communities_total": 5,
    "posts_new": 42,
    "points_window": 11,
    "failed_communities": ["뽐뿌 자유게시판(응답 403)"],
    "usage": "7회 호출",
}
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def test_markdown_has_every_section(draft, synthesis, ideation):
    md = render_markdown(draft, synthesis, ideation, STATS, NOW)
    for heading in ["세 줄 요약", "핵심 불편 테마", "사업화 후보", "기존 아이디어 대조", "지금 결정할 것"]:
        assert f"## {heading}" in md
    assert draft.headline in md
    assert "분리배출 규칙 통합 조회" in md
    assert "14/25" in md  # 신규 아이디어 점수가 기존 점수와 같은 척도로 표시된다
    assert "카페 잔여석 지도·웨이팅" in md
    assert "뽐뿌 자유게시판(응답 403)" in md  # 수집 실패가 각주로 드러난다


def test_markdown_escapes_table_breaking_pipes(draft, synthesis, ideation):
    hostile = draft.model_copy(
        update={
            "top_themes": [
                draft.top_themes[0].model_copy(update={"so_what": "a | b | c", "quote": "q"})
            ]
        }
    )
    md = render_markdown(hostile, synthesis, ideation, STATS, NOW)
    row = next(line for line in md.splitlines() if "a ／ b ／ c" in line)
    assert row.count("|") == 6  # 5칸짜리 행이 파이프 때문에 깨지지 않는다


def test_markdown_omits_empty_sections(draft, synthesis, ideation):
    bare = ideation.model_copy(
        update={"new_ideas": [], "portfolio_verdicts": [], "ranking_note": "", "portfolio_gap": ""}
    )
    md = render_markdown(draft, synthesis, bare, STATS, NOW)
    assert "## 사업화 후보" not in md
    assert "## 기존 아이디어 대조" not in md


def test_html_escapes_user_content(draft, synthesis, ideation):
    hostile = draft.model_copy(update={"headline": "<script>alert(1)</script>"})
    html = render_html(hostile, synthesis, ideation, STATS, NOW)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_is_theme_aware_and_printable(draft, synthesis, ideation):
    html = render_html(draft, synthesis, ideation, STATS, NOW)
    assert "prefers-color-scheme: dark" in html
    assert "@page { size: A4" in html
    assert "분리배출 규칙 통합 조회" in html
