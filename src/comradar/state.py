"""SQLite-backed run state.

Hourly monitoring only works if each run remembers what the previous ones
already saw. This module owns three jobs:

1. **Dedupe** — a post is analysed once, ever. An hourly run that re-reads the
   same front page must not re-bill you for it.
2. **The rolling window** — one hour of new posts is too thin to reason about,
   so pain points accumulate and the analyst agent reads a trailing window
   (24 hours by default) rather than a single run.
3. **Momentum** — themes from previous runs are kept so the analyst can say
   whether something is rising or fading instead of guessing.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

from .models import RawPost, StoredPainPoint, Theme

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_posts (
    post_id       TEXT PRIMARY KEY,
    community     TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_community ON seen_posts(community);

CREATE TABLE IF NOT EXISTS pain_points (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    community       TEXT NOT NULL,
    observed_at     TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    severity        INTEGER NOT NULL,
    who             TEXT NOT NULL DEFAULT '',
    workaround      TEXT NOT NULL DEFAULT '',
    evidence_quote  TEXT NOT NULL DEFAULT '',
    is_recurring    INTEGER NOT NULL DEFAULT 0,
    source_url      TEXT NOT NULL DEFAULT '',
    source_title    TEXT NOT NULL DEFAULT '',
    engagement      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pain_observed ON pain_points(observed_at);

CREATE TABLE IF NOT EXISTS themes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    theme         TEXT NOT NULL,
    domain        TEXT NOT NULL,
    mention_count INTEGER NOT NULL,
    severity      INTEGER NOT NULL,
    momentum      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_theme_observed ON themes(observed_at);

CREATE TABLE IF NOT EXISTS checkpoints (
    name TEXT PRIMARY KEY,
    at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '{}'
);
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class Store:
    """A small synchronous SQLite wrapper. One instance per run."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- dedupe ------------------------------------------------------------

    def filter_new_posts(self, posts: Sequence[RawPost]) -> List[RawPost]:
        """Return only posts never seen before, and record them as seen.

        Marking happens here rather than after analysis on purpose: a post that
        crashed the analyser should not be retried forever on every run.
        """
        if not posts:
            return []
        ids = [p.post_id for p in posts]
        placeholders = ",".join("?" * len(ids))
        with closing(self._conn.cursor()) as cur:
            cur.execute(f"SELECT post_id FROM seen_posts WHERE post_id IN ({placeholders})", ids)
            known = {row["post_id"] for row in cur.fetchall()}
        fresh = [p for p in posts if p.post_id not in known]
        now = _iso(datetime.now(timezone.utc))
        self._conn.executemany(
            "INSERT OR IGNORE INTO seen_posts(post_id, community, first_seen_at) VALUES (?,?,?)",
            [(p.post_id, p.community, now) for p in fresh],
        )
        self._conn.commit()
        return fresh

    # -- pain points -------------------------------------------------------

    def record_pain_points(self, points: Iterable[StoredPainPoint]) -> int:
        rows = [
            (
                p.run_id,
                p.community,
                _iso(p.observed_at),
                p.title,
                p.summary,
                p.domain,
                p.severity,
                p.who,
                p.workaround,
                p.evidence_quote,
                int(p.is_recurring),
                p.source_url,
                p.source_title,
                p.engagement,
            )
            for p in points
        ]
        if not rows:
            return 0
        self._conn.executemany(
            """INSERT INTO pain_points
               (run_id, community, observed_at, title, summary, domain, severity,
                who, workaround, evidence_quote, is_recurring, source_url,
                source_title, engagement)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def window_pain_points(self, hours: int) -> List[StoredPainPoint]:
        """Every pain point observed in the trailing `hours`, newest first."""
        cutoff = _iso(datetime.now(timezone.utc) - timedelta(hours=hours))
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                "SELECT * FROM pain_points WHERE observed_at >= ? ORDER BY observed_at DESC",
                (cutoff,),
            )
            rows = cur.fetchall()
        return [
            StoredPainPoint(
                run_id=r["run_id"],
                community=r["community"],
                observed_at=datetime.fromisoformat(r["observed_at"]),
                title=r["title"],
                summary=r["summary"],
                domain=r["domain"],
                severity=r["severity"],
                who=r["who"],
                workaround=r["workaround"],
                evidence_quote=r["evidence_quote"],
                is_recurring=bool(r["is_recurring"]),
                source_url=r["source_url"],
                source_title=r["source_title"],
                engagement=r["engagement"],
            )
            for r in rows
        ]

    # -- themes ------------------------------------------------------------

    def record_themes(self, run_id: str, themes: Sequence[Theme]) -> None:
        now = _iso(datetime.now(timezone.utc))
        self._conn.executemany(
            """INSERT INTO themes
               (run_id, observed_at, theme, domain, mention_count, severity, momentum)
               VALUES (?,?,?,?,?,?,?)""",
            [
                (run_id, now, t.theme, t.domain, t.mention_count, t.severity, t.momentum)
                for t in themes
            ],
        )
        self._conn.commit()

    def previous_themes(self, limit: int = 20) -> List[dict]:
        """The most recent completed run's themes, for momentum comparison."""
        with closing(self._conn.cursor()) as cur:
            cur.execute("SELECT run_id FROM themes ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row is None:
                return []
            cur.execute(
                """SELECT theme, domain, mention_count, severity, momentum, observed_at
                   FROM themes WHERE run_id = ? ORDER BY mention_count DESC LIMIT ?""",
                (row["run_id"], limit),
            )
            return [dict(r) for r in cur.fetchall()]

    # -- runs --------------------------------------------------------------

    def start_run(self, run_id: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs(run_id, started_at, status) VALUES (?,?,?)",
            (run_id, _iso(datetime.now(timezone.utc)), "running"),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, status: str, detail: dict | None = None) -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, detail = ? WHERE run_id = ?",
            (
                _iso(datetime.now(timezone.utc)),
                status,
                json.dumps(detail or {}, ensure_ascii=False),
                run_id,
            ),
        )
        self._conn.commit()

    def recent_runs(self, limit: int = 10) -> List[dict]:
        with closing(self._conn.cursor()) as cur:
            cur.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    # -- checkpoints -------------------------------------------------------

    def set_checkpoint(self, name: str, when: datetime | None = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoints(name, at) VALUES (?,?)",
            (name, _iso(when or datetime.now(timezone.utc))),
        )
        self._conn.commit()

    def get_checkpoint(self, name: str) -> datetime | None:
        with closing(self._conn.cursor()) as cur:
            cur.execute("SELECT at FROM checkpoints WHERE name = ?", (name,))
            row = cur.fetchone()
        return datetime.fromisoformat(row["at"]) if row else None

    def due(self, name: str, interval_hours: float) -> bool:
        """True when `interval_hours` have passed since the checkpoint.

        A missing checkpoint counts as due, so the first run after setup
        produces a report instead of waiting out a full interval.
        """
        last = self.get_checkpoint(name)
        if last is None:
            return True
        return datetime.now(timezone.utc) - last >= timedelta(hours=interval_hours)

    def prune(self, keep_days: int = 30) -> int:
        """Drop observations older than `keep_days`. Seen-post ids are kept."""
        cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=keep_days))
        cur = self._conn.execute("DELETE FROM pain_points WHERE observed_at < ?", (cutoff,))
        deleted = cur.rowcount or 0
        self._conn.execute("DELETE FROM themes WHERE observed_at < ?", (cutoff,))
        self._conn.commit()
        return deleted
