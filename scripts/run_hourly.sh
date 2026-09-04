#!/usr/bin/env bash
# 서버 cron용 래퍼.
#
#   crontab -e
#   0 * * * * /path/to/repo/scripts/run_hourly.sh >> /var/log/comradar.log 2>&1
#
# 매시간 수집하고, comradar가 보고 주기를 판단해 4시간마다 보고서를 만든다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 필요한 환경변수는 여기서 읽는다. 파일 권한을 600으로 둘 것.
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

PYTHON="${COMRADAR_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi

exec "$PYTHON" -m comradar run --config "${COMRADAR_CONFIG:-config/communities.yaml}"
