import pytest

from comradar.config import ConfigError, load_config


def write(tmp_path, text):
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf-8")
    return path


BASE = """
communities:
  - name: A
    source: rss
    options: {url: https://example.com/feed}
"""


def test_defaults_apply(tmp_path):
    cfg = load_config(write(tmp_path, BASE))
    assert cfg.run.window_hours == 4
    assert cfg.run.report_interval_hours == 4
    assert cfg.collector.model == "claude-opus-5"
    assert cfg.ideation.model == "claude-opus-5"
    assert cfg.active_communities[0].slug == "a"
    assert cfg.portfolio.enabled is False


def test_notion_portfolio_requires_page_id(tmp_path):
    with pytest.raises(ConfigError, match="page_id"):
        load_config(
            write(tmp_path, "portfolio:\n  enabled: true\n  source: notion\n" + BASE)
        )


def test_portfolio_page_id_dashes_stripped(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            "portfolio:\n  enabled: true\n  page_id: 2ae959f5-14e4-806b-8acc-f715136b5e04\n"
            + BASE,
        )
    )
    assert cfg.portfolio.page_id == "2ae959f514e4806b8accf715136b5e04"


def test_unknown_portfolio_source_rejected(tmp_path):
    with pytest.raises(ConfigError, match="portfolio.source"):
        load_config(write(tmp_path, "portfolio:\n  source: airtable\n" + BASE))


def test_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("FEED_HOST", "feeds.example.org")
    cfg = load_config(
        write(
            tmp_path,
            "communities:\n  - name: A\n    source: rss\n"
            "    options: {url: 'https://${FEED_HOST}/rss'}\n",
        )
    )
    assert cfg.communities[0].options["url"] == "https://feeds.example.org/rss"


def test_duplicate_names_rejected(tmp_path):
    text = BASE + "  - name: A\n    source: rss\n    options: {url: https://x/y}\n"
    with pytest.raises(ConfigError, match="중복"):
        load_config(write(tmp_path, text))


def test_invalid_effort_rejected(tmp_path):
    with pytest.raises(ConfigError, match="effort"):
        load_config(write(tmp_path, "models:\n  collector:\n    effort: turbo\n" + BASE))


def test_missing_source_rejected(tmp_path):
    with pytest.raises(ConfigError, match="name과 source"):
        load_config(write(tmp_path, "communities:\n  - name: A\n"))


def test_disabled_community_excluded(tmp_path):
    text = BASE + "  - name: B\n    source: rss\n    enabled: false\n    options: {url: https://x/y}\n"
    cfg = load_config(write(tmp_path, text))
    assert [c.name for c in cfg.active_communities] == ["A"]
