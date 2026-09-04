"""Rendering the one-pager.

Layout is code, not prompt. The agent supplies bounded fields; this module
lays them out so the result is a single page every time, in Markdown for the
repository and in print-ready HTML for humans.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Sequence

from .models import IdeationResult, ReportDraft, SynthesisResult

SIGNAL_MARK = {
    "강한 지지": "++",
    "약한 지지": "+",
    "신호 없음": "·",
    "반대 신호": "-",
}

MOMENTUM_MARK = {
    "신규": "NEW",
    "급상승": "▲▲",
    "상승": "▲",
    "유지": "=",
    "하락": "▼",
}


def _cell(text: str) -> str:
    """Make a string safe to drop into a Markdown table cell."""
    return text.replace("|", "／").replace("\n", " ").strip()


def render_markdown(
    draft: ReportDraft,
    synthesis: SynthesisResult,
    ideation: IdeationResult,
    stats: dict,
    generated_at: datetime,
) -> str:
    lines: list[str] = []
    lines.append(f"# {draft.headline}")
    lines.append("")
    lines.append(
        f"*{generated_at.strftime('%Y-%m-%d %H:%M %Z')} 기준 · "
        f"최근 {stats.get('window_hours')}시간 · "
        f"커뮤니티 {stats.get('communities_ok')}/{stats.get('communities_total')}곳 · "
        f"신규 게시물 {stats.get('posts_new')}건 · 불편 사례 {stats.get('points_window')}건*"
    )
    lines.append("")

    lines.append("## 세 줄 요약")
    for item in draft.tldr:
        lines.append(f"- {item}")
    lines.append("")

    if draft.top_themes:
        lines.append("## 핵심 불편 테마")
        lines.append("")
        lines.append("| # | 테마 | 추세 | 왜 중요한가 | 관측 근거 |")
        lines.append("|---|------|------|-------------|-----------|")
        for theme in draft.top_themes:
            lines.append(
                f"| {theme.rank} | **{_cell(theme.theme)}** "
                f"| {MOMENTUM_MARK.get(theme.momentum, theme.momentum)} "
                f"| {_cell(theme.so_what)} | {_cell(theme.evidence)} |"
            )
        lines.append("")
        for theme in draft.top_themes:
            if theme.quote:
                lines.append(f"> **{theme.theme}** — “{theme.quote.strip()}”")
        lines.append("")

    if draft.rising_signals:
        lines.append("## 떠오르는 신호")
        for signal in draft.rising_signals:
            lines.append(f"- {signal}")
        lines.append("")

    if ideation.new_ideas:
        lines.append("## 사업화 후보")
        lines.append("")
        lines.append("| 아이디어 | 진입점 | 수요 근거 | 점수 |")
        lines.append("|----------|--------|-----------|------|")
        for idea in ideation.new_ideas:
            lines.append(
                f"| **{_cell(idea.name)}**<br>{_cell(idea.solution)} "
                f"| {_cell(idea.wedge)} | {_cell(idea.demand_evidence)} "
                f"| {idea.score.total}/25 |"
            )
        lines.append("")
        for idea in ideation.new_ideas:
            lines.append(f"**{idea.name}** ({idea.source_theme} 테마)")
            lines.append(f"- 문제: {idea.problem}")
            lines.append(f"- 첫 고객: {idea.target} · 수익: {idea.revenue_model}")
            lines.append(f"- 2주 안에 할 검증: {idea.first_test}")
            lines.append(f"- 접는 기준: {idea.kill_criteria}")
            lines.append(
                "- 점수: 절실함 {0} / 시장 {1} / 차별성 {2} / 실행 {3} / 수익 {4}".format(
                    idea.score.problem_urgency,
                    idea.score.market_size,
                    idea.score.differentiation,
                    idea.score.feasibility,
                    idea.score.profitability,
                )
            )
            lines.append("")

    if ideation.portfolio_verdicts:
        lines.append("## 기존 아이디어 대조")
        lines.append("")
        lines.append("| 기존 아이디어 | 신호 | 이번 구간 관측 | 할 일 |")
        lines.append("|---------------|------|----------------|-------|")
        for verdict in ideation.portfolio_verdicts[:6]:
            lines.append(
                f"| {_cell(verdict.existing_idea)} "
                f"| {SIGNAL_MARK.get(verdict.signal, '')} {verdict.signal} "
                f"| {_cell(verdict.observation)} | {_cell(verdict.action)} |"
            )
        lines.append("")
    if ideation.ranking_note:
        lines.append(f"- 위치: {ideation.ranking_note}")
    if ideation.portfolio_gap:
        lines.append(f"- 포트폴리오 공백: {ideation.portfolio_gap}")
    if ideation.ranking_note or ideation.portfolio_gap:
        lines.append("")

    if synthesis.cross_cutting_insight:
        lines.append("## 관통하는 한 가지")
        lines.append(synthesis.cross_cutting_insight)
        lines.append("")

    if draft.decision_prompt:
        lines.append("## 지금 결정할 것")
        lines.append(f"**{draft.decision_prompt}**")
        lines.append("")

    footnotes: list[str] = []
    if draft.what_did_not_change:
        footnotes.append(f"**변하지 않은 것** — {draft.what_did_not_change}")
    if synthesis.contrarian_note:
        footnotes.append(f"**반론** — {synthesis.contrarian_note}")
    if synthesis.coverage_warning:
        footnotes.append(f"**데이터 한계** — {synthesis.coverage_warning}")
    failures: Sequence[str] = stats.get("failed_communities") or []
    if failures:
        footnotes.append(f"**수집 실패** — {', '.join(failures)}")
    if stats.get("usage"):
        footnotes.append(f"**비용** — {stats['usage']}")

    if footnotes:
        lines.append("---")
        for note in footnotes:
            lines.append(f"- {note}")
        lines.append("")

    if draft.top_themes:
        lines.append("<details><summary>근거 링크</summary>")
        lines.append("")
        for theme in synthesis.themes[:5]:
            urls = " · ".join(f"[{i + 1}]({u})" for i, u in enumerate(theme.evidence_urls[:3]) if u)
            if urls:
                lines.append(f"- {theme.theme}: {urls}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


HTML_STYLE = """
:root { color-scheme: light dark; --fg:#16181d; --muted:#606874; --line:#d9dee6;
        --bg:#ffffff; --accent:#1f4fd8; --chip:#eef2fb; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8eaee; --muted:#9aa3b2; --line:#333a45; --bg:#14161a;
          --accent:#8fb0ff; --chip:#1e2530; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font: 13px/1.55 -apple-system, "Pretendard", "Apple SD Gothic Neo",
             "Noto Sans KR", system-ui, sans-serif; }
.page { max-width: 820px; margin: 0 auto; padding: 28px 32px 40px; }
h1 { font-size: 22px; line-height:1.3; margin:0 0 6px; letter-spacing:-0.01em; }
.meta { color:var(--muted); font-size:11.5px; margin:0 0 18px;
        padding-bottom:12px; border-bottom:1px solid var(--line); }
h2 { font-size:12px; text-transform:uppercase; letter-spacing:.08em;
     color:var(--muted); margin:20px 0 8px; }
ul, ol { margin:0 0 4px; padding-left:18px; }
li { margin-bottom:3px; }
table { width:100%; border-collapse:collapse; font-size:12px; margin-bottom:10px; }
th { text-align:left; font-weight:600; color:var(--muted); font-size:11px;
     text-transform:uppercase; letter-spacing:.04em;
     border-bottom:1px solid var(--line); padding:6px 8px 6px 0; }
td { padding:7px 8px 7px 0; border-bottom:1px solid var(--line);
     vertical-align:top; }
td.rank { width:22px; color:var(--muted); }
td.mom { width:52px; }
.chip { display:inline-block; padding:1px 7px; border-radius:10px;
        background:var(--chip); color:var(--accent); font-size:10.5px;
        font-weight:600; white-space:nowrap; }
blockquote { margin:6px 0; padding:6px 0 6px 12px; border-left:2px solid var(--line);
             color:var(--muted); font-size:11.5px; }
.insight { padding:10px 12px; background:var(--chip); border-radius:6px; font-size:12.5px; }
.decision { padding:10px 12px; border:1px solid var(--accent); border-radius:6px;
            font-size:12.5px; font-weight:600; }
.idea { border:1px solid var(--line); border-radius:6px; padding:9px 11px; margin-bottom:8px; }
.idea-head { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.idea-head .score { color:var(--accent); font-weight:700; font-size:11.5px; }
.idea-line { margin:2px 0 6px; color:var(--muted); font-size:11.5px; }
.idea ul { font-size:11.5px; }
.notes { margin-top:18px; padding-top:12px; border-top:1px solid var(--line);
         color:var(--muted); font-size:11px; }
a { color:var(--accent); }
@media print {
  body { background:#fff; color:#000; }
  .page { max-width:none; padding:0; }
  @page { size: A4; margin: 14mm; }
}
"""


def render_html(
    draft: ReportDraft,
    synthesis: SynthesisResult,
    ideation: IdeationResult,
    stats: dict,
    generated_at: datetime,
) -> str:
    e = html.escape
    out: list[str] = [
        "<!doctype html>",
        '<html lang="ko"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(draft.headline)}</title>",
        f"<style>{HTML_STYLE}</style></head><body><div class='page'>",
        f"<h1>{e(draft.headline)}</h1>",
        f"<p class='meta'>{e(generated_at.strftime('%Y-%m-%d %H:%M %Z'))} 기준 · "
        f"최근 {e(str(stats.get('window_hours')))}시간 · "
        f"커뮤니티 {e(str(stats.get('communities_ok')))}/{e(str(stats.get('communities_total')))}곳 · "
        f"신규 게시물 {e(str(stats.get('posts_new')))}건 · "
        f"불편 사례 {e(str(stats.get('points_window')))}건</p>",
        "<h2>세 줄 요약</h2><ul>",
        *[f"<li>{e(item)}</li>" for item in draft.tldr],
        "</ul>",
    ]

    if draft.top_themes:
        out.append("<h2>핵심 불편 테마</h2><table><thead><tr>")
        out.append("<th></th><th>테마</th><th>추세</th><th>왜 중요한가</th><th>관측 근거</th>")
        out.append("</tr></thead><tbody>")
        for theme in draft.top_themes:
            out.append(
                f"<tr><td class='rank'>{theme.rank}</td>"
                f"<td><strong>{e(theme.theme)}</strong></td>"
                f"<td class='mom'><span class='chip'>{e(theme.momentum)}</span></td>"
                f"<td>{e(theme.so_what)}</td><td>{e(theme.evidence)}</td></tr>"
            )
        out.append("</tbody></table>")
        for theme in draft.top_themes:
            if theme.quote:
                out.append(
                    f"<blockquote><strong>{e(theme.theme)}</strong> — “{e(theme.quote.strip())}”"
                    "</blockquote>"
                )

    if draft.rising_signals:
        out.append("<h2>떠오르는 신호</h2><ul>")
        out += [f"<li>{e(s)}</li>" for s in draft.rising_signals]
        out.append("</ul>")

    if ideation.new_ideas:
        out.append("<h2>사업화 후보</h2>")
        for idea in ideation.new_ideas:
            out.append("<div class='idea'>")
            out.append(
                f"<div class='idea-head'><strong>{e(idea.name)}</strong>"
                f"<span class='score'>{idea.score.total}/25</span></div>"
            )
            out.append(f"<p class='idea-line'>{e(idea.solution)}</p>")
            out.append("<ul>")
            out.append(f"<li>문제 — {e(idea.problem)}</li>")
            out.append(f"<li>진입점 — {e(idea.wedge)}</li>")
            out.append(f"<li>첫 고객 — {e(idea.target)} · 수익 — {e(idea.revenue_model)}</li>")
            out.append(f"<li>수요 근거 — {e(idea.demand_evidence)}</li>")
            out.append(f"<li>2주 검증 — {e(idea.first_test)}</li>")
            out.append(f"<li>접는 기준 — {e(idea.kill_criteria)}</li>")
            out.append(
                "<li>절실함 {0} · 시장 {1} · 차별성 {2} · 실행 {3} · 수익 {4}</li>".format(
                    idea.score.problem_urgency,
                    idea.score.market_size,
                    idea.score.differentiation,
                    idea.score.feasibility,
                    idea.score.profitability,
                )
            )
            out.append("</ul></div>")

    if ideation.portfolio_verdicts:
        out.append("<h2>기존 아이디어 대조</h2><table><thead><tr>")
        out.append("<th>기존 아이디어</th><th>신호</th><th>이번 구간 관측</th><th>할 일</th>")
        out.append("</tr></thead><tbody>")
        for verdict in ideation.portfolio_verdicts[:6]:
            out.append(
                f"<tr><td>{e(verdict.existing_idea)}</td>"
                f"<td class='mom'><span class='chip'>{e(verdict.signal)}</span></td>"
                f"<td>{e(verdict.observation)}</td><td>{e(verdict.action)}</td></tr>"
            )
        out.append("</tbody></table>")
    if ideation.ranking_note or ideation.portfolio_gap:
        out.append("<ul>")
        if ideation.ranking_note:
            out.append(f"<li>위치 — {e(ideation.ranking_note)}</li>")
        if ideation.portfolio_gap:
            out.append(f"<li>포트폴리오 공백 — {e(ideation.portfolio_gap)}</li>")
        out.append("</ul>")

    if synthesis.cross_cutting_insight:
        out.append("<h2>관통하는 한 가지</h2>")
        out.append(f"<p class='insight'>{e(synthesis.cross_cutting_insight)}</p>")

    if draft.decision_prompt:
        out.append("<h2>지금 결정할 것</h2>")
        out.append(f"<p class='decision'>{e(draft.decision_prompt)}</p>")

    notes: list[str] = []
    if draft.what_did_not_change:
        notes.append(f"<strong>변하지 않은 것</strong> — {e(draft.what_did_not_change)}")
    if synthesis.contrarian_note:
        notes.append(f"<strong>반론</strong> — {e(synthesis.contrarian_note)}")
    if synthesis.coverage_warning:
        notes.append(f"<strong>데이터 한계</strong> — {e(synthesis.coverage_warning)}")
    if stats.get("failed_communities"):
        notes.append(f"<strong>수집 실패</strong> — {e(', '.join(stats['failed_communities']))}")
    if stats.get("usage"):
        notes.append(f"<strong>비용</strong> — {e(str(stats['usage']))}")
    if notes:
        out.append("<div class='notes'><ul>")
        out += [f"<li>{n}</li>" for n in notes]
        out.append("</ul></div>")

    out.append("</div></body></html>")
    return "\n".join(out)
