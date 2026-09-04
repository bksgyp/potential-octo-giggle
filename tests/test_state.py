from datetime import datetime, timedelta, timezone

from comradar.models import RawPost, StoredPainPoint, Theme
from comradar.state import Store


def make_point(store_run="r1", hours_ago=0, community="A"):
    return StoredPainPoint(
        run_id=store_run,
        community=community,
        observed_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        title="t",
        summary="s",
        domain="기타",
        severity=3,
        who="w",
        workaround="",
        evidence_quote="q",
        is_recurring=False,
        source_url="https://example.com/1",
        source_title="title",
        engagement=5,
    )


def test_dedupe_across_runs(tmp_path):
    with Store(tmp_path / "s.db") as store:
        posts = [RawPost(post_id=f"p{i}", community="A", title=f"t{i}") for i in range(3)]
        assert len(store.filter_new_posts(posts)) == 3
        # 같은 목록을 다시 넣으면 새 글은 없다.
        assert store.filter_new_posts(posts) == []
        posts.append(RawPost(post_id="p9", community="A", title="new"))
        assert [p.post_id for p in store.filter_new_posts(posts)] == ["p9"]


def test_window_excludes_old_points(tmp_path):
    with Store(tmp_path / "s.db") as store:
        store.record_pain_points([make_point(hours_ago=1), make_point(hours_ago=50)])
        assert len(store.window_pain_points(24)) == 1
        assert len(store.window_pain_points(72)) == 2


def test_previous_themes_returns_latest_run_only(tmp_path):
    theme = Theme(
        theme="T",
        one_liner="o",
        domain="기타",
        communities=["A"],
        mention_count=2,
        severity=3,
        momentum="신규",
        root_cause="r",
        solution_gap="g",
        representative_quotes=["q"],
        evidence_urls=["https://example.com/1"],
    )
    with Store(tmp_path / "s.db") as store:
        store.record_themes("run1", [theme])
        store.record_themes("run2", [theme.model_copy(update={"theme": "T2"})])
        previous = store.previous_themes()
        assert [t["theme"] for t in previous] == ["T2"]


def test_prune_drops_old_rows(tmp_path):
    with Store(tmp_path / "s.db") as store:
        store.record_pain_points([make_point(hours_ago=24 * 40), make_point(hours_ago=1)])
        assert store.prune(keep_days=30) == 1
        assert len(store.window_pain_points(24 * 60)) == 1


def test_run_lifecycle(tmp_path):
    with Store(tmp_path / "s.db") as store:
        store.start_run("r1")
        store.finish_run("r1", "ok", {"posts_new": 4})
        run = store.recent_runs()[0]
        assert run["status"] == "ok" and run["finished_at"]
