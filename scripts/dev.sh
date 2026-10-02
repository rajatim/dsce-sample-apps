#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOAN_DIR="${REPO_DIR}/archived-apps/loan-preprocessing-agents"
LOAN_ENV_FILE="${LOAN_ENV_FILE:-${LOAN_DIR}/.env}"
[[ -f "${LOAN_ENV_FILE}" ]] || { echo 'Create the protected Loan .env before starting.' >&2; exit 1; }
set -a
source "${LOAN_ENV_FILE}"
set +a
for name in SERVER_PORT VITE_PORT; do
  value="${!name:-}"
  [[ "$value" =~ ^[0-9]+$ ]] && ((10#$value >= 1024 && 10#$value <= 65535)) || { echo "Invalid ${name}." >&2; exit 1; }
  case "$value" in 3000|4200|5173|5174|8000|8080) echo "Default port is not allowed for ${name}." >&2; exit 1;; esac
  if lsof -nP -iTCP:"$value" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port ${value} is occupied; no process was stopped." >&2; exit 1
  fi
done
[[ "$SERVER_PORT" != "$VITE_PORT" ]] || { echo 'API and UI ports must differ.' >&2; exit 1; }
[[ -n "${DATABASE_URL:-}" ]] || { echo 'Set an isolated DATABASE_URL in the Loan .env.' >&2; exit 1; }
if [[ "${1:-}" == '--check' ]]; then
  echo "Loan configuration checked: API ${SERVER_PORT}, UI ${VITE_PORT}. No service started."
  exit 0
fi
LOAN_PYTHON="${LOAN_PYTHON:-${LOAN_DIR}/backend/.venv/bin/python}"
[[ -x "$LOAN_PYTHON" ]] || { echo 'Install the locked backend dependencies before starting.' >&2; exit 1; }
[[ -x "${LOAN_DIR}/frontend/node_modules/.bin/vite" ]] || { echo 'Install frontend dependencies before starting.' >&2; exit 1; }
module='main:app'
if [[ "${LOAN_STATUS_FIXTURES:-false}" == true ]]; then
  module='tests.status_browser_app:app'
  echo 'Controlled status fixtures enabled. No real provider checks or loan processing are available.'
fi
api_pid=''
ui_pid=''
cleanup() {
  [[ -z "$api_pid" ]] || kill "$api_pid" 2>/dev/null || true
  [[ -z "$ui_pid" ]] || kill "$ui_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
(cd "${LOAN_DIR}/backend"; exec "$LOAN_PYTHON" -m uvicorn "$module" --host 127.0.0.1 --port "$SERVER_PORT") &
api_pid=$!
(cd "${LOAN_DIR}/frontend"; exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$VITE_PORT" --strictPort) &
ui_pid=$!
echo "Loan status: http://127.0.0.1:${VITE_PORT}/status"
# macOS ships Bash 3: monitor both children without relying on wait -n.
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$ui_pid" 2>/dev/null; do sleep 1; done
exit 1
