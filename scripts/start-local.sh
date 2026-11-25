#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

web_port="${DRIVEWELL_WEB_PORT:-3000}"
api_port="${DRIVEWELL_API_PORT:-8016}"
export API_URL="http://127.0.0.1:$api_port"
export APP_ENV="${APP_ENV:-development}"
local_origins="http://localhost:$web_port,http://127.0.0.1:$web_port"
if [[ "$APP_ENV" == development ]]; then
  export WEB_ORIGIN="${WEB_ORIGIN:+$WEB_ORIGIN,}$local_origins"
else
  export WEB_ORIGIN="${WEB_ORIGIN:-$local_origins}"
fi
export PAYMENT_MODE="${PAYMENT_MODE:-demo}"

if [[ ! -x .venv/bin/alembic || ! -d apps/web/node_modules ]]; then
  echo "Install the project dependencies using the README setup steps first." >&2
  exit 1
fi

docker compose up -d --wait postgres
(
  cd services/api
  ../../.venv/bin/alembic upgrade head
)
(
  cd services/api
  exec ../../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$api_port"
) &
api_pid=$!
web_pid=""
cleanup() {
  kill "$api_pid" ${web_pid:+"$web_pid"} 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
curl -fsS --retry 12 --retry-connrefused --retry-delay 1 "$API_URL/health" >/dev/null
(
  cd apps/web
  if [[ "${DRIVEWELL_DEV:-0}" == 1 ]]; then
    exec node node_modules/next/dist/bin/next dev --hostname 0.0.0.0 --port "$web_port"
  fi
  npm run build
  exec node node_modules/next/dist/bin/next start --hostname 0.0.0.0 --port "$web_port"
) &
web_pid=$!
wait -n "$api_pid" "$web_pid"
