"""Where the finished report goes."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List

from .config import DeliveryConfig
from .models import ReportDraft

logger = logging.getLogger(__name__)


def write_report(
    output_dir: Path,
    generated_at: datetime,
    markdown: str,
    html: str,
    cfg: DeliveryConfig,
) -> List[Path]:
    """Write the timestamped report plus a stable `latest.*` copy."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y-%m-%d-%H%M")
    written: List[Path] = []

    if cfg.write_markdown:
        path = output_dir / f"{stamp}.md"
        path.write_text(markdown, encoding="utf-8")
        (output_dir / "latest.md").write_text(markdown, encoding="utf-8")
        written.append(path)
    if cfg.write_html:
        path = output_dir / f"{stamp}.html"
        path.write_text(html, encoding="utf-8")
        (output_dir / "latest.html").write_text(html, encoding="utf-8")
        written.append(path)
    return written


def post_to_slack(draft: ReportDraft, cfg: DeliveryConfig) -> bool:
    """Best-effort Slack notification. Never fails the run."""
    if not cfg.slack_webhook_env:
        return False
    webhook = os.environ.get(cfg.slack_webhook_env, "").strip()
    if not webhook:
        logger.info("Slack 웹훅 환경변수 %s가 비어 있어 전송을 건너뜁니다.", cfg.slack_webhook_env)
        return False

    bullets = "\n".join(f"• {item}" for item in draft.tldr)
    themes = "\n".join(f"{t.rank}. {t.theme} — {t.so_what}" for t in draft.top_themes)
    payload = {"text": f"*{draft.headline}*\n{bullets}\n\n{themes}".strip()}
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:  # a failed notification must not fail the report
        logger.warning("Slack 전송 실패: %s", exc)
        return False
