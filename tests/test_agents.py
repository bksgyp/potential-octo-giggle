from comradar.agents import CollectorAgent, IdeationAgent, ReportAgent, SynthesisAgent
from comradar.config import CommunityConfig
from comradar.models import CommunityScan, IdeationResult, ReportDraft, SynthesisResult
from tests.conftest import FakeCaller

COMMUNITY = CommunityConfig(name="테스트 커뮤니티", source="rss", options={"url": "x"})


async def test_collector_anchors_to_real_posts(model_cfg, posts, scan):
    agent = CollectorAgent(COMMUNITY, FakeCaller({CommunityScan: scan}), model_cfg)
    result, anchored = await agent.run(posts, run_id="r1")

    # 존재하지 않는 post_index를 가리킨 항목은 버려진다.
    assert len(anchored) == 1
    point = anchored[0]
    # URL과 반응 수는 모델이 아니라 실제 게시물에서 온다.
    assert point.source_url == "https://example.com/p1"
    assert point.engagement == posts[0].engagement()
    assert point.community == "테스트 커뮤니티"
    assert result.community_mood


async def test_collector_respects_max_points(model_cfg, posts, scan):
    agent = CollectorAgent(COMMUNITY, FakeCaller({CommunityScan: scan}), model_cfg, max_points=0)
    _, anchored = await agent.run(posts, run_id="r1")
    assert anchored == []


async def test_collector_skips_llm_when_no_posts(model_cfg):
    caller = FakeCaller()
    agent = CollectorAgent(COMMUNITY, caller, model_cfg)
    result, anchored = await agent.run([], run_id="r1")
    assert caller.calls == []  # 빈 배치에 토큰을 쓰지 않는다
    assert anchored == [] and result.notes


async def test_collector_prompt_indexes_every_post(model_cfg, posts, scan):
    agent = CollectorAgent(COMMUNITY, FakeCaller({CommunityScan: scan}), model_cfg)
    prompt = agent.build_prompt(posts)
    assert "[0] 제목:" in prompt and "[1] 제목:" in prompt
    assert "테스트 커뮤니티" in prompt


async def test_synthesizer_short_circuits_on_empty_window(model_cfg):
    caller = FakeCaller()
    result = await SynthesisAgent(caller, model_cfg).run([], [], 24)
    assert caller.calls == []
    assert result.themes == [] and result.coverage_warning


async def test_synthesizer_prompt_carries_previous_themes(model_cfg, posts, scan, synthesis):
    collector = CollectorAgent(COMMUNITY, FakeCaller({CommunityScan: scan}), model_cfg)
    _, anchored = await collector.run(posts, run_id="r1")

    caller = FakeCaller({SynthesisResult: synthesis})
    agent = SynthesisAgent(caller, model_cfg)
    await agent.run(anchored, [{"theme": "이전 테마", "mention_count": 4}], 24)

    prompt = caller.calls[0]["user"]
    assert "이전 테마" in prompt
    assert "최근 24시간" in prompt
    assert "테스트 커뮤니티" in prompt


async def test_synthesizer_caps_theme_count(model_cfg, posts, scan, synthesis):
    many = synthesis.model_copy(update={"themes": synthesis.themes * 5})
    collector = CollectorAgent(COMMUNITY, FakeCaller({CommunityScan: scan}), model_cfg)
    _, anchored = await collector.run(posts, run_id="r1")
    result = await SynthesisAgent(
        FakeCaller({SynthesisResult: many}), model_cfg, max_themes=2
    ).run(anchored, [], 24)
    assert len(result.themes) == 2


async def test_reporter_short_circuits_without_themes(model_cfg, synthesis, ideation):
    empty = synthesis.model_copy(update={"themes": [], "coverage_warning": "데이터 없음"})
    caller = FakeCaller()
    draft = await ReportAgent(caller, model_cfg).run(empty, ideation, {"communities_total": 3})
    assert caller.calls == []
    assert len(draft.tldr) == 3 and draft.top_themes == []


async def test_reporter_trims_to_one_page(model_cfg, synthesis, ideation, draft):
    oversized = draft.model_copy(
        update={"top_themes": draft.top_themes * 9, "tldr": draft.tldr * 3}
    )
    result = await ReportAgent(FakeCaller({ReportDraft: oversized}), model_cfg).run(
        synthesis, ideation, {"communities_total": 1}
    )
    assert len(result.top_themes) == 5 and len(result.tldr) == 3


async def test_reporter_sees_ideation_output(model_cfg, synthesis, ideation, draft):
    caller = FakeCaller({ReportDraft: draft})
    await ReportAgent(caller, model_cfg).run(synthesis, ideation, {"communities_total": 1})
    assert "분리배출 규칙 통합 조회" in caller.calls[0]["user"]


async def test_ideation_drops_verdicts_on_unknown_ideas(
    model_cfg, synthesis, ideation, portfolio
):
    caller = FakeCaller({IdeationResult: ideation.model_copy(deep=True)})
    result = await IdeationAgent(caller, model_cfg).run(synthesis, portfolio)
    names = [v.existing_idea for v in result.portfolio_verdicts]
    assert names == ["카페 잔여석 지도·웨이팅"]  # 존재하지 않는 아이디어 판정은 버려진다


async def test_ideation_prompt_lists_existing_ideas(model_cfg, synthesis, ideation, portfolio):
    caller = FakeCaller({IdeationResult: ideation.model_copy(deep=True)})
    await IdeationAgent(caller, model_cfg).run(synthesis, portfolio)
    prompt = caller.calls[0]["user"]
    assert "카페 잔여석 지도·웨이팅" in prompt
    assert "기존 점수 분포: 13~15점" in prompt


async def test_ideation_handles_missing_portfolio(model_cfg, synthesis, ideation):
    caller = FakeCaller({IdeationResult: ideation.model_copy(deep=True)})
    result = await IdeationAgent(caller, model_cfg).run(synthesis, [])
    assert "불러오지 못했다" in caller.calls[0]["user"]
    # 대조할 목록이 없으면 판정을 걸러낼 근거도 없으므로 그대로 둔다.
    assert len(result.portfolio_verdicts) == 2


async def test_ideation_short_circuits_without_themes(model_cfg, synthesis, portfolio):
    empty = synthesis.model_copy(update={"themes": []})
    caller = FakeCaller()
    result = await IdeationAgent(caller, model_cfg).run(empty, portfolio)
    assert caller.calls == []
    assert result.new_ideas == []


async def test_ideation_caps_and_sorts_new_ideas(model_cfg, synthesis, ideation, portfolio):
    weak = ideation.new_ideas[0].model_copy(
        update={
            "name": "약한 후보",
            "score": ideation.new_ideas[0].score.model_copy(update={"market_size": 1}),
        }
    )
    many = ideation.model_copy(update={"new_ideas": [weak, *ideation.new_ideas]})
    result = await IdeationAgent(FakeCaller({IdeationResult: many}), model_cfg, max_new_ideas=1).run(
        synthesis, portfolio
    )
    assert [i.name for i in result.new_ideas] == ["분리배출 규칙 통합 조회"]
