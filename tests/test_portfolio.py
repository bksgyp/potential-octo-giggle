"""Portfolio loading. The Notion path is exercised without touching Notion."""

import pytest

from comradar.config import PortfolioConfig
from comradar.models import PortfolioIdea
from comradar import portfolio as portfolio_mod
from comradar.portfolio import (
    PortfolioError,
    load_portfolio,
    load_snapshot,
    rows_to_ideas,
    save_snapshot,
)

TABLE = [
    ["아이디어", "한 줄 정의", "핵심 강점", "핵심 리스크", "아이디어 점수 (25)"],
    ["RunWith", "실시간 동시 러닝 앱", "타겟이 명확", "콜드스타트", "17"],
    ["BudgetFlow", "영수증 자동 정리", "세무사 채널", "홈택스 중복", "15"],
]


def test_rows_to_ideas_maps_columns():
    ideas = rows_to_ideas(TABLE)
    assert [i.name for i in ideas] == ["RunWith", "BudgetFlow"]
    assert ideas[0].one_liner == "실시간 동시 러닝 앱"
    # "아이디어 점수 (25)"가 이름 열을 덮어쓰지 않아야 한다.
    assert ideas[0].score == 17


def test_rows_to_ideas_ignores_table_without_name_column():
    assert rows_to_ideas([["점수", "비고"], ["17", "x"]]) == []


def test_rows_to_ideas_ignores_header_only_table():
    assert rows_to_ideas([TABLE[0]]) == []


def test_snapshot_roundtrip(tmp_path):
    path = tmp_path / "ideas.yaml"
    save_snapshot(path, rows_to_ideas(TABLE))
    assert [i.name for i in load_snapshot(path)] == ["RunWith", "BudgetFlow"]


def test_missing_snapshot_raises(tmp_path):
    with pytest.raises(PortfolioError, match="스냅샷"):
        load_snapshot(tmp_path / "nope.yaml")


async def test_disabled_portfolio_returns_empty():
    assert await load_portfolio(PortfolioConfig(enabled=False)) == []


async def test_notion_failure_falls_back_to_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "ideas.yaml"
    save_snapshot(path, [PortfolioIdea(name="스냅샷 아이디어", score=12)])

    async def boom(cfg, timeout=20.0):
        raise PortfolioError("토큰 없음")

    monkeypatch.setattr(portfolio_mod, "fetch_from_notion", boom)
    cfg = PortfolioConfig(enabled=True, source="notion", page_id="x", snapshot_path=path)
    ideas = await load_portfolio(cfg)
    assert [i.name for i in ideas] == ["스냅샷 아이디어"]


async def test_successful_notion_fetch_refreshes_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "ideas.yaml"
    save_snapshot(path, [PortfolioIdea(name="옛날 아이디어")])

    async def fresh(cfg, timeout=20.0):
        return [PortfolioIdea(name="새 아이디어", score=18)]

    monkeypatch.setattr(portfolio_mod, "fetch_from_notion", fresh)
    cfg = PortfolioConfig(enabled=True, source="notion", page_id="x", snapshot_path=path)
    ideas = await load_portfolio(cfg)
    assert [i.name for i in ideas] == ["새 아이디어"]
    # 다음 오프라인 실행이 최신 목록을 쓰도록 사본이 갱신된다.
    assert [i.name for i in load_snapshot(path)] == ["새 아이디어"]


async def test_both_paths_failing_degrades_to_empty(tmp_path, monkeypatch):
    async def boom(cfg, timeout=20.0):
        raise PortfolioError("토큰 없음")

    monkeypatch.setattr(portfolio_mod, "fetch_from_notion", boom)
    cfg = PortfolioConfig(
        enabled=True, source="notion", page_id="x", snapshot_path=tmp_path / "none.yaml"
    )
    # 대조를 못 해도 실행 전체가 죽지는 않는다.
    assert await load_portfolio(cfg) == []
