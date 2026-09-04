"""Command line entry point.

    comradar run                 # 매시간 호출용. 수집하고, 보고 주기가 되면 보고서까지.
    comradar run --force-report  # 주기와 무관하게 이번에 보고서를 만든다
    comradar run --fetch-only    # 모델 호출 없이 수집 경로만 점검
    comradar collect             # 수집만. 보고서는 만들지 않는다
    comradar report              # 저장된 관측만으로 보고서를 다시 만든다
    comradar loop --interval 1h  # 프로세스 안에서 매시간 run을 반복
    comradar discover <게시판주소>  # 그 사이트의 실제 RSS 주소를 찾아 준다
    comradar doctor              # 설정, 소스 연결, 아이디어 포트폴리오 점검
    comradar sources             # 사용 가능한 소스 어댑터
    comradar history             # 최근 실행 기록
    comradar prune --keep-days 30

수집 주기와 보고 주기는 다르다. run을 매시간 돌려도 보고서는
run.report_interval_hours(기본 4시간)마다 한 번만 나온다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import AppConfig, ConfigError, load_config
from .discover import config_snippet, discover
from .pipeline import Pipeline, RunResult
from .portfolio import load_portfolio
from .sources import available_sources
from .state import Store

DEFAULT_CONFIG = "config/communities.yaml"
logger = logging.getLogger("comradar")

_DURATION = re.compile(r"^(\d+)\s*([smhd]?)$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 1}


def parse_duration(text: str) -> int:
    """`3600`, `90m`, `1h`, `1d` -> seconds."""
    match = _DURATION.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"기간 형식이 잘못되었습니다: {text!r} (예: 1h, 30m, 3600)")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _print_run_summary(result: RunResult) -> None:
    print()
    print(f"실행 {result.run_id}")
    for item in result.communities:
        status = "실패" if not item.ok else f"신규 {item.new_posts}건 → 불편 {item.pain_points}건"
        detail = f" ({item.error})" if item.error else ""
        print(f"  - {item.community}: 수집 {item.fetched}건 / {status}{detail}")
    stats = result.stats
    print(
        f"  합계: 신규 게시물 {stats['posts_new']}건, "
        f"이번 구간 사례 {stats['points_new']}건"
        + (f", 분석 윈도우 {stats['points_window']}건" if "points_window" in stats else "")
    )
    if not result.reported:
        print(f"  보고서 생략: 보고 주기 {stats.get('report_interval_hours')}시간이 아직 안 됨")
    if result.written:
        print("  보고서: " + ", ".join(str(p) for p in result.written))
    if result.portfolio:
        print(f"  기존 아이디어 {len(result.portfolio)}건과 대조")
    if result.draft:
        print()
        print(f"  ▸ {result.draft.headline}")
        for line in result.draft.tldr:
            print(f"    · {line}")
    if result.ideation and result.ideation.new_ideas:
        print()
        print("  사업화 후보:")
        for idea in result.ideation.new_ideas:
            print(f"    · {idea.name} ({idea.score.total}/25) — {idea.wedge}")


async def _execute(
    config: AppConfig, analyse: bool, echo: bool, report_mode: str = "auto"
) -> RunResult:
    with Store(config.run.state_db) as store:
        result = await Pipeline(config, store).run(analyse=analyse, report_mode=report_mode)
    if echo:
        _print_run_summary(result)
    return result


def _report_mode(args: argparse.Namespace) -> str:
    if getattr(args, "no_report", False):
        return "never"
    return "force" if getattr(args, "force_report", False) else "auto"


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.window_hours:
        config = _with_window(config, args.window_hours)
    result = asyncio.run(
        _execute(
            config,
            analyse=not args.fetch_only,
            echo=True,
            report_mode=_report_mode(args),
        )
    )
    if config.delivery.stdout and result.markdown:
        print("\n" + "=" * 72 + "\n")
        print(result.markdown)
    failed = len(result.stats.get("failed_communities") or [])
    if failed and failed == result.stats["communities_total"]:
        logger.error("모든 커뮤니티 수집에 실패했습니다.")
        return 1
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    asyncio.run(_execute(config, analyse=True, echo=True, report_mode="never"))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.window_hours:
        config = _with_window(config, args.window_hours)

    async def build() -> RunResult:
        with Store(config.run.state_db) as store:
            return await Pipeline(config, store).report_only()

    result = asyncio.run(build())
    _print_run_summary(result)
    if config.delivery.stdout and result.markdown:
        print("\n" + "=" * 72 + "\n")
        print(result.markdown)
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    interval = parse_duration(args.interval)

    async def loop() -> None:
        while True:
            started = datetime.now(timezone.utc)
            try:
                await _execute(config, analyse=True, echo=True)
            except Exception:  # a bad run must not end the schedule
                logger.exception("실행 중 오류가 발생했습니다. 다음 주기에 다시 시도합니다.")
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            delay = max(interval - elapsed, 30.0)
            next_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            logger.info("다음 실행: %s (%.0f초 후)", next_at.astimezone().strftime("%H:%M"), delay)
            await asyncio.sleep(delay)

    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        print("\n중단했습니다.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(f"설정 파일: {args.config}")
    print(f"활성 커뮤니티 {len(config.active_communities)}곳 / 전체 {len(config.communities)}곳")
    print(f"모델: 수집 {config.collector.model}({config.collector.effort}) · "
          f"분석 {config.synthesizer.model}({config.synthesizer.effort}) · "
          f"사업화 {config.ideation.model}({config.ideation.effort}) · "
          f"보고 {config.reporter.model}({config.reporter.effort})")
    print(f"주기: 수집은 호출될 때마다, 보고는 {config.run.report_interval_hours}시간마다 "
          f"(관측 구간 {config.run.window_hours}시간)")
    print(f"상태 DB: {config.run.state_db}")

    print("\n아이디어 포트폴리오")
    if not config.portfolio.enabled:
        print("  꺼져 있음 (portfolio.enabled: false). 사업화 대조는 생략됩니다.")
    else:
        ideas = asyncio.run(load_portfolio(config.portfolio, config.http.timeout_seconds))
        if ideas:
            # 어느 경로로 읽혔는지는 위의 경고 로그가 말해 준다. Notion이
            # 실패하고 스냅샷으로 대체된 경우 설정값을 그대로 찍으면 거짓이 된다.
            print(f"  OK   {len(ideas)}건 로드")
            for idea in ideas[:3]:
                print(f"       · {idea.name}" + (f" ({idea.score}/25)" if idea.score else ""))
        else:
            print("  FAIL 아이디어를 불러오지 못했습니다. 토큰과 page_id, 스냅샷 경로를 확인하세요.")
    print("\n소스 연결 점검 (모델 호출 없음)")
    result = asyncio.run(_execute(config, analyse=False, echo=False, report_mode="never"))
    failures = 0
    for item in result.communities:
        if item.ok:
            print(f"  OK   {item.community}: {item.fetched}건 수집 (신규 {item.new_posts}건)")
        else:
            failures += 1
            print(f"  FAIL {item.community}: {item.error}")
    return 1 if failures else 0


def cmd_discover(args: argparse.Namespace) -> int:
    """피드 주소는 추측하지 말고 사이트에 직접 물어본다."""
    config = load_config(args.config)
    candidates = asyncio.run(
        discover(
            args.url,
            user_agent=config.http.user_agent,
            timeout=config.http.timeout_seconds,
            try_common_paths=not args.declared_only,
        )
    )
    if not candidates:
        print("후보를 찾지 못했습니다.")
        return 1

    print(f"{args.url} 에서 찾은 피드 후보\n")
    for candidate in candidates:
        if candidate.ok:
            print(f"  OK   [{candidate.source}] {candidate.url}")
            print(f"       항목 {candidate.entries}건 · {candidate.title or '(제목 없음)'}")
            if candidate.sample:
                print(f"       최근 글: {candidate.sample}")
        else:
            print(f"  FAIL [{candidate.source}] {candidate.url} — {candidate.error}")

    snippet = config_snippet(args.name or "이름을 정하세요", candidates)
    if not snippet:
        print("\n동작하는 피드가 없습니다. 이 사이트는 RSS를 제공하지 않을 수 있습니다.")
        print("`comradar sources`의 다른 어댑터(naver, json)를 검토하세요.")
        return 1
    print("\nconfig/communities.yaml 의 communities: 아래에 붙여넣으세요.\n")
    print(snippet)
    return 0


def cmd_sources(_: argparse.Namespace) -> int:
    print("사용 가능한 소스 어댑터:")
    for name in available_sources():
        print(f"  - {name}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    with Store(config.run.state_db) as store:
        runs = store.recent_runs(args.limit)
    if not runs:
        print("실행 기록이 없습니다.")
        return 0
    for run in runs:
        print(f"{run['run_id']}  {run['status']:<10} {run['finished_at'] or '(진행 중)'}")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    with Store(config.run.state_db) as store:
        deleted = store.prune(args.keep_days)
    print(f"{args.keep_days}일 이전 사례 {deleted}건을 삭제했습니다.")
    return 0


def _with_window(config: AppConfig, hours: int) -> AppConfig:
    from dataclasses import replace

    return replace(config, run=replace(config.run, window_hours=hours))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comradar",
        description="커뮤니티를 주기적으로 읽고 실생활 불편을 한 장으로 정리한다.",
    )
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="설정 YAML 경로")
    parser.add_argument("-v", "--verbose", action="store_true", help="디버그 로그")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="수집하고, 보고 주기가 되었으면 보고서까지 만든다")
    run.add_argument("--fetch-only", action="store_true", help="모델 호출 없이 수집만 한다")
    run.add_argument("--force-report", action="store_true", help="주기와 무관하게 보고서를 만든다")
    run.add_argument("--no-report", action="store_true", help="이번에는 보고서를 만들지 않는다")
    run.add_argument("--window-hours", type=int, default=None, help="분석 윈도우 시간 override")
    run.set_defaults(func=cmd_run)

    collect = sub.add_parser("collect", help="수집만 한다 (매시간용)")
    collect.set_defaults(func=cmd_collect)

    report = sub.add_parser("report", help="저장된 관측만으로 보고서를 만든다")
    report.add_argument("--window-hours", type=int, default=None, help="분석 윈도우 시간 override")
    report.set_defaults(func=cmd_report)

    loop = sub.add_parser("loop", help="주기적으로 반복 실행한다")
    loop.add_argument("--interval", default="1h", help="run 반복 간격 (기본 1h)")
    loop.set_defaults(func=cmd_loop)

    doctor = sub.add_parser("doctor", help="설정과 소스 연결을 점검한다")
    doctor.set_defaults(func=cmd_doctor)

    disc = sub.add_parser("discover", help="사이트의 실제 RSS 주소를 찾는다")
    disc.add_argument("url", help="게시판 페이지 주소. 피드 주소를 직접 넣어도 된다.")
    disc.add_argument("--name", default="", help="스니펫에 넣을 커뮤니티 이름")
    disc.add_argument(
        "--declared-only", action="store_true", help="관용 경로는 시도하지 않는다"
    )
    disc.set_defaults(func=cmd_discover)

    sources = sub.add_parser("sources", help="소스 어댑터 목록")
    sources.set_defaults(func=cmd_sources)

    history = sub.add_parser("history", help="최근 실행 기록")
    history.add_argument("--limit", type=int, default=10)
    history.set_defaults(func=cmd_history)

    prune = sub.add_parser("prune", help="오래된 관측 기록을 지운다")
    prune.add_argument("--keep-days", type=int, default=30)
    prune.set_defaults(func=cmd_prune)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
