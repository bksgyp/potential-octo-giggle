"""The existing idea portfolio, read from Notion.

The ideation agent needs to know what is already on the table, otherwise it
re-proposes ideas the user has already written down and scored. This module
loads that list from the Notion page and keeps a local snapshot so a run still
works when Notion is unreachable or no token is configured.

Only the first table on the page is read: on the "사업화 아이디어" page that is
the 종합 비교 table, which carries one row per idea with its one-liner,
strength, risk and score. Everything else on that page is prose the agent does
not need.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List

import httpx2 as httpx
import yaml

from .config import PortfolioConfig
from .models import PortfolioIdea

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Header text -> PortfolioIdea field. Matching is substring-based because the
# page's column titles are prose, not identifiers. A header matches a row if it
# contains ANY of that row's hints, and the rows are ordered most specific
# first: "아이디어 점수 (25)" must land on `score`, not on `name`.
COLUMN_HINTS = [
    (("점수",), "score"),
    (("한 줄", "정의"), "one_liner"),
    (("강점",), "strength"),
    (("리스크", "약점"), "risk"),
    (("아이디어", "이름", "항목"), "name"),
]


class PortfolioError(RuntimeError):
    """The idea portfolio could not be loaded. Never fatal to a run."""


def _plain_text(rich_text: list[dict]) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text or []).strip()


def _match_column(header: str) -> str | None:
    """Map a header cell to a field name, most specific hint first."""
    for hints, field in COLUMN_HINTS:
        if any(hint in header for hint in hints):
            return field
    return None


def rows_to_ideas(rows: List[List[str]]) -> List[PortfolioIdea]:
    """Turn a Notion table (first row = header) into portfolio ideas."""
    if len(rows) < 2:
        return []
    header, *body = rows
    mapping: dict[int, str] = {}
    for index, cell in enumerate(header):
        field = _match_column(cell)
        # The name column is the one whose header is exactly the idea column;
        # later columns that also mention 아이디어 (e.g. 아이디어 점수) must not
        # overwrite it, so a field is claimed once.
        if field and field not in mapping.values():
            mapping[index] = field
    if "name" not in mapping.values():
        return []

    ideas: List[PortfolioIdea] = []
    for row in body:
        values: dict[str, Any] = {}
        for index, field in mapping.items():
            if index >= len(row):
                continue
            cell = row[index]
            if field == "score":
                digits = "".join(ch for ch in cell if ch.isdigit())
                values[field] = int(digits) if digits else 0
            else:
                values[field] = cell
        if values.get("name"):
            ideas.append(PortfolioIdea(**values))
    return ideas


async def _fetch_children(client: httpx.AsyncClient, block_id: str) -> List[dict]:
    results: List[dict] = []
    cursor: str | None = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        response = await client.get(f"{NOTION_API}/blocks/{block_id}/children", params=params)
        if response.status_code != 200:
            raise PortfolioError(
                f"Notion 응답 {response.status_code}. 토큰이 이 페이지에 연결되어 있는지 확인하세요."
            )
        payload = response.json()
        results.extend(payload.get("results") or [])
        if not payload.get("has_more"):
            return results
        cursor = payload.get("next_cursor")


async def fetch_from_notion(cfg: PortfolioConfig, timeout: float = 20.0) -> List[PortfolioIdea]:
    """Read the page's Nth table and return one idea per row."""
    token = os.environ.get(cfg.token_env, "").strip()
    if not token:
        raise PortfolioError(
            f"환경변수 {cfg.token_env}가 비어 있습니다. Notion 내부 통합 토큰이 필요합니다."
        )
    if not cfg.page_id:
        raise PortfolioError("portfolio.page_id가 설정되지 않았습니다.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        blocks = await _fetch_children(client, cfg.page_id)
        tables = [b for b in blocks if b.get("type") == "table"]
        if not tables:
            raise PortfolioError("페이지 최상위에서 표를 찾지 못했습니다.")
        if cfg.table_index >= len(tables):
            raise PortfolioError(
                f"표 인덱스 {cfg.table_index}가 범위를 벗어났습니다 (표 {len(tables)}개)."
            )
        table_rows = await _fetch_children(client, tables[cfg.table_index]["id"])

    rows = [
        [_plain_text(cell) for cell in (block.get("table_row") or {}).get("cells") or []]
        for block in table_rows
        if block.get("type") == "table_row"
    ]
    ideas = rows_to_ideas(rows)
    if not ideas:
        raise PortfolioError("표에서 아이디어 행을 해석하지 못했습니다.")
    return ideas


def load_snapshot(path: Path) -> List[PortfolioIdea]:
    if not path.exists():
        raise PortfolioError(f"스냅샷 파일이 없습니다: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("ideas") or []
    ideas = [PortfolioIdea(**entry) for entry in entries if entry.get("name")]
    if not ideas:
        raise PortfolioError(f"스냅샷에 아이디어가 없습니다: {path}")
    return ideas


def save_snapshot(path: Path, ideas: List[PortfolioIdea]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ideas": [idea.model_dump() for idea in ideas]}
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


async def load_portfolio(cfg: PortfolioConfig, timeout: float = 20.0) -> List[PortfolioIdea]:
    """Load the portfolio, preferring Notion and falling back to the snapshot.

    A stale snapshot beats no comparison at all, so a Notion failure is logged
    and downgraded rather than raised. A successful fetch refreshes the
    snapshot, which is what keeps the offline path useful.
    """
    if not cfg.enabled:
        return []
    if cfg.source == "file":
        return load_snapshot(cfg.snapshot_path)

    try:
        ideas = await fetch_from_notion(cfg, timeout=timeout)
    except PortfolioError as exc:
        logger.warning("Notion에서 아이디어 목록을 읽지 못했습니다: %s", exc)
    except Exception as exc:
        logger.warning("Notion 요청 중 오류: %s", exc)
    else:
        try:
            save_snapshot(cfg.snapshot_path, ideas)
        except OSError as exc:
            logger.warning("스냅샷 저장 실패: %s", exc)
        return ideas

    logger.info("로컬 스냅샷으로 대체합니다: %s", cfg.snapshot_path)
    try:
        return load_snapshot(cfg.snapshot_path)
    except PortfolioError as exc:
        logger.warning("스냅샷도 사용할 수 없습니다: %s", exc)
        return []
