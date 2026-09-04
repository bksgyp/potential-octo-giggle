"""Configuration loading and validation.

The whole framework is driven by one YAML file. Adding a community is a config
edit, never a code edit, unless the community needs a source adapter that does
not exist yet.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_MODEL = "claude-opus-5"
VALID_EFFORT = {"low", "medium", "high", "xhigh", "max"}


class ConfigError(ValueError):
    """Raised when the YAML file is structurally wrong."""


@dataclass(frozen=True)
class AgentModelConfig:
    """Model settings for one agent role."""

    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_tokens: int = 16000

    @classmethod
    def parse(cls, raw: Dict[str, Any] | None, role: str) -> "AgentModelConfig":
        raw = raw or {}
        effort = str(raw.get("effort", "high"))
        if effort not in VALID_EFFORT:
            raise ConfigError(
                f"models.{role}.effort는 {sorted(VALID_EFFORT)} 중 하나여야 합니다: {effort!r}"
            )
        max_tokens = int(raw.get("max_tokens", 16000))
        if not 1024 <= max_tokens <= 128000:
            raise ConfigError(f"models.{role}.max_tokens 범위를 벗어났습니다: {max_tokens}")
        return cls(str(raw.get("model", DEFAULT_MODEL)), effort, max_tokens)


@dataclass(frozen=True)
class CommunityConfig:
    """One community, and therefore one collector agent."""

    name: str
    source: str
    enabled: bool = True
    locale: str = "ko"
    options: Dict[str, Any] = field(default_factory=dict)
    # Per-community override; falls back to the global cap.
    max_posts: int | None = None

    @property
    def slug(self) -> str:
        """Filesystem- and SQLite-safe identifier derived from the name."""
        s = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", self.name).strip("-").lower()
        return s or "community"


@dataclass(frozen=True)
class HttpConfig:
    user_agent: str = "comradar/0.1 (community pain-point monitor)"
    timeout_seconds: float = 20.0
    request_delay_seconds: float = 1.0
    max_concurrent_fetches: int = 4


@dataclass(frozen=True)
class PortfolioConfig:
    """The existing idea list the ideation agent compares against."""

    enabled: bool = False
    source: str = "notion"  # notion | file
    token_env: str = "NOTION_TOKEN"
    page_id: str = ""
    table_index: int = 0
    snapshot_path: Path = Path("config/ideas.yaml")


@dataclass(frozen=True)
class RunConfig:
    # 수집은 매시간, 보고는 몇 시간에 한 번. window_hours는 한 보고서가 다루는
    # 관측 구간이므로 보고 주기와 맞추는 것이 기본이다.
    window_hours: int = 4
    report_interval_hours: int = 4
    max_posts_per_community: int = 40
    min_engagement: int = 0
    timezone: str = "Asia/Seoul"
    output_dir: Path = Path("reports")
    state_db: Path = Path(".comradar/state.db")
    max_pain_points_per_community: int = 12
    max_themes: int = 8
    max_new_ideas: int = 3


@dataclass(frozen=True)
class DeliveryConfig:
    write_markdown: bool = True
    write_html: bool = True
    slack_webhook_env: str = ""
    stdout: bool = True


@dataclass(frozen=True)
class AppConfig:
    run: RunConfig
    http: HttpConfig
    delivery: DeliveryConfig
    portfolio: PortfolioConfig
    collector: AgentModelConfig
    synthesizer: AgentModelConfig
    reporter: AgentModelConfig
    ideation: AgentModelConfig
    communities: List[CommunityConfig]

    @property
    def active_communities(self) -> List[CommunityConfig]:
        return [c for c in self.communities if c.enabled]


def _expand_env(value: Any) -> Any:
    """Allow ``${VAR}`` references anywhere in the YAML."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"설정 파일을 찾을 수 없습니다: {path}")
    raw = _expand_env(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if not isinstance(raw, dict):
        raise ConfigError("설정 파일 최상위는 매핑이어야 합니다.")

    run_raw = raw.get("run") or {}
    run = RunConfig(
        window_hours=int(run_raw.get("window_hours", 4)),
        report_interval_hours=int(run_raw.get("report_interval_hours", 4)),
        max_posts_per_community=int(run_raw.get("max_posts_per_community", 40)),
        min_engagement=int(run_raw.get("min_engagement", 0)),
        timezone=str(run_raw.get("timezone", "Asia/Seoul")),
        output_dir=Path(str(run_raw.get("output_dir", "reports"))),
        state_db=Path(str(run_raw.get("state_db", ".comradar/state.db"))),
        max_pain_points_per_community=int(run_raw.get("max_pain_points_per_community", 12)),
        max_themes=int(run_raw.get("max_themes", 8)),
        max_new_ideas=int(run_raw.get("max_new_ideas", 3)),
    )
    if run.window_hours < 1:
        raise ConfigError("run.window_hours는 1 이상이어야 합니다.")
    if run.report_interval_hours < 1:
        raise ConfigError("run.report_interval_hours는 1 이상이어야 합니다.")

    http_raw = raw.get("http") or {}
    http = HttpConfig(
        user_agent=str(http_raw.get("user_agent", HttpConfig.user_agent)),
        timeout_seconds=float(http_raw.get("timeout_seconds", 20.0)),
        request_delay_seconds=float(http_raw.get("request_delay_seconds", 1.0)),
        max_concurrent_fetches=int(http_raw.get("max_concurrent_fetches", 4)),
    )

    d_raw = raw.get("delivery") or {}
    delivery = DeliveryConfig(
        write_markdown=bool(d_raw.get("markdown", True)),
        write_html=bool(d_raw.get("html", True)),
        slack_webhook_env=str(d_raw.get("slack_webhook_env", "")),
        stdout=bool(d_raw.get("stdout", True)),
    )

    models_raw = raw.get("models") or {}
    collector = AgentModelConfig.parse(models_raw.get("collector"), "collector")
    synthesizer = AgentModelConfig.parse(models_raw.get("synthesizer"), "synthesizer")
    reporter = AgentModelConfig.parse(models_raw.get("reporter"), "reporter")
    ideation = AgentModelConfig.parse(models_raw.get("ideation"), "ideation")

    p_raw = raw.get("portfolio") or {}
    source = str(p_raw.get("source", "notion"))
    if source not in {"notion", "file"}:
        raise ConfigError(f"portfolio.source는 notion 또는 file이어야 합니다: {source!r}")
    portfolio = PortfolioConfig(
        enabled=bool(p_raw.get("enabled", False)),
        source=source,
        token_env=str(p_raw.get("token_env", "NOTION_TOKEN")),
        page_id=str(p_raw.get("page_id", "")).replace("-", ""),
        table_index=int(p_raw.get("table_index", 0)),
        snapshot_path=Path(str(p_raw.get("snapshot_path", "config/ideas.yaml"))),
    )
    if portfolio.enabled and portfolio.source == "notion" and not portfolio.page_id:
        raise ConfigError("portfolio.source가 notion이면 page_id가 필요합니다.")

    communities_raw = raw.get("communities") or []
    if not isinstance(communities_raw, list) or not communities_raw:
        raise ConfigError("communities에 최소 한 개의 커뮤니티가 필요합니다.")

    communities: List[CommunityConfig] = []
    seen: set[str] = set()
    for i, entry in enumerate(communities_raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"communities[{i}]는 매핑이어야 합니다.")
        name = str(entry.get("name", "")).strip()
        source = str(entry.get("source", "")).strip()
        if not name or not source:
            raise ConfigError(f"communities[{i}]에 name과 source가 모두 필요합니다.")
        if name in seen:
            raise ConfigError(f"커뮤니티 이름이 중복됩니다: {name}")
        seen.add(name)
        max_posts = entry.get("max_posts")
        communities.append(
            CommunityConfig(
                name=name,
                source=source,
                enabled=bool(entry.get("enabled", True)),
                locale=str(entry.get("locale", "ko")),
                options=dict(entry.get("options") or {}),
                max_posts=int(max_posts) if max_posts is not None else None,
            )
        )

    return AppConfig(
        run=run,
        http=http,
        delivery=delivery,
        portfolio=portfolio,
        collector=collector,
        synthesizer=synthesizer,
        reporter=reporter,
        ideation=ideation,
        communities=communities,
    )
