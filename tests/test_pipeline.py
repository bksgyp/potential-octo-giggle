"""End-to-end run with a fake source and a fake model. No network, no tokens."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest

from comradar.config import CommunityConfig, load_config
from comradar.models import (
    CommunityScan,
    IdeationResult,
    RawPost,
    ReportDraft,
    SynthesisResult,
)
from comradar.pipeline import REPORT_CHECKPOINT, Pipeline
from comradar.sources import register
from comradar.state import Store
from tests.conftest import FakeCaller

COUNTER = {"n": 0}


@register("fake")
async def fetch_fake(community: CommunityConfig, ctx) -> List[RawPost]:
    """Returns a fresh post every call so dedupe has something to do."""
    COUNTER["n"] += 1
    return [
        RawPost(
            post_id=f"{community.slug}-{COUNTER['n']}",
            community=community.name,
            title="분리배출 규칙이 동네마다 다름",
            body="이사할 때마다 다시 검색합니다.",
            url=f"https://example.com/{COUNTER['n']}",
            score=10,
            num_comments=5,
            created_at=datetime.now(timezone.utc),
        )
    ]


@register("broken")
async def fetch_broken(community: CommunityConfig, ctx) -> List[RawPost]:
    raise RuntimeError("업스트림이 죽었습니다")


CONFIG = """
run:
  window_hours: 4
  report_interval_hours: 4
  output_dir: {out}
  state_db: {db}
portfolio:
  enabled: true
  source: file
  snapshot_path: {ideas}
delivery:
  stdout: false
http:
  request_delay_seconds: 0
communities:
  - name: 테스트 커뮤니티
    source: fake
  - name: 고장난 커뮤니티
    source: broken
"""

IDEAS = """
ideas:
  - name: 카페 잔여석 지도·웨이팅
    score: 13
  - name: BudgetFlow 경비 정산·세무 준비
    score: 15
"""


@pytest.fixture
def config(tmp_path):
    ideas = tmp_path / "ideas.yaml"
    ideas.write_text(IDEAS, encoding="utf-8")
    path = tmp_path / "c.yaml"
    path.write_text(
        CONFIG.format(out=tmp_path / "reports", db=tmp_path / "state.db", ideas=ideas),
        encoding="utf-8",
    )
    return load_config(path)


@pytest.fixture
def caller(scan, synthesis, ideation, draft) -> FakeCaller:
    return FakeCaller(
        {
            CommunityScan: scan,
            SynthesisResult: synthesis,
            IdeationResult: ideation,
            ReportDraft: draft,
        }
    )


async def test_full_run_writes_a_report(config, caller, draft):
    with Store(config.run.state_db) as store:
        result = await Pipeline(config, store, llm=caller).run()

    assert result.reported
    assert result.stats["posts_new"] == 1
    # 고장난 커뮤니티는 자기 자리만 잃고 실행 전체를 죽이지 않는다.
    assert result.stats["communities_ok"] == 1
    assert "고장난 커뮤니티" in result.stats["failed_communities"][0]

    assert [p.name for p in result.written] == [
        f"{result.generated_at.strftime('%Y-%m-%d-%H%M')}.md",
        f"{result.generated_at.strftime('%Y-%m-%d-%H%M')}.html",
    ]
    latest = config.run.output_dir / "latest.md"
    assert latest.exists()
    body = latest.read_text(encoding="utf-8")
    assert draft.headline in body
    assert "분리배출 규칙 통합 조회" in body      # 사업화 에이전트 결과
    assert "카페 잔여석 지도·웨이팅" in body      # 노션 포트폴리오 대조


async def test_all_four_agents_are_called(config, caller):
    with Store(config.run.state_db) as store:
        await Pipeline(config, store, llm=caller).run()
    labels = [call["label"] for call in caller.calls]
    assert labels == [
        "collector:테스트-커뮤니티",
        "synthesizer",
        "ideation",
        "reporter",
    ]


async def test_second_run_collects_but_does_not_report(config, caller):
    with Store(config.run.state_db) as store:
        pipeline = Pipeline(config, store, llm=caller)
        await pipeline.run()
        caller.calls.clear()
        second = await Pipeline(config, store, llm=caller).run()

    assert not second.reported
    assert second.stats["posts_new"] == 1  # 수집은 계속된다
    # 보고 주기 전에는 분석·사업화·보고 에이전트를 부르지 않는다.
    assert [c["label"] for c in caller.calls] == ["collector:테스트-커뮤니티"]


async def test_force_report_overrides_the_interval(config, caller):
    with Store(config.run.state_db) as store:
        await Pipeline(config, store, llm=caller).run()
        forced = await Pipeline(config, store, llm=caller).run(report_mode="force")
    assert forced.reported


async def test_report_checkpoint_is_recorded(config, caller):
    with Store(config.run.state_db) as store:
        await Pipeline(config, store, llm=caller).run()
        assert store.get_checkpoint(REPORT_CHECKPOINT) is not None
        assert store.due(REPORT_CHECKPOINT, 4) is False


async def test_fetch_only_spends_no_tokens(config, caller):
    with Store(config.run.state_db) as store:
        result = await Pipeline(config, store, llm=caller).run(analyse=False)
    assert caller.calls == []
    assert result.stats["posts_new"] == 1
    assert not result.reported


async def test_report_only_skips_collection(config, caller):
    with Store(config.run.state_db) as store:
        await Pipeline(config, store, llm=caller).run()
        caller.calls.clear()
        again = await Pipeline(config, store, llm=caller).report_only()
    assert again.reported
    assert again.stats["posts_new"] == 0
    assert [c["label"] for c in caller.calls] == ["synthesizer", "ideation", "reporter"]


async def test_portfolio_reaches_the_result(config, caller):
    with Store(config.run.state_db) as store:
        result = await Pipeline(config, store, llm=caller).run()
    assert [i.name for i in result.portfolio] == [
        "카페 잔여석 지도·웨이팅",
        "BudgetFlow 경비 정산·세무 준비",
    ]
    assert result.stats["portfolio_size"] == 2
