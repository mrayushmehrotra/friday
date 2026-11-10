#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────────────────────────────────────
# INDmoney Intraday Equity Bot launcher
#   bash run-intraday-bot.sh                → start bot on port 9092
#   bash run-intraday-bot.sh --port 9093    → serve on custom port
#   bash run-intraday-bot.sh --paper        → run in forced paper simulation mode
#   bash run-intraday-bot.sh --scan         → run immediate scanner on startup
# ───────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
step() { echo -e "${CYAN}[>]${NC} $1"; }

cd "$(dirname "${BASH_SOURCE[0]}")"

VENV=".venv"
PORT=9092
FORWARD_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      [[ $# -ge 2 ]] || { err "--port needs a value"; exit 1; }
      PORT="$2"; shift ;;
    --port=*) PORT="${1#*=}" ;;
    -h|--help)
      echo "Usage: bash run-intraday-bot.sh [--port N] [--paper] [--scan] [--token TOKEN]"
      exit 0 ;;
    *) FORWARD_ARGS+=("$1") ;;
  esac
  shift
done

LOG="indmoney_bot.server.log"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  INDmoney Intraday Equity Bot Launcher"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -x "$VENV/bin/python" ]]; then
  PY="$VENV/bin/python"
else
  PY="python3"
fi
info "Using Python at $PY"

# Free the port if already in use
if curl -sf -m 2 "http://localhost:$PORT/api/status" >/dev/null 2>&1; then
  warn "Port $PORT already serving — restarting bot"
  command -v fuser &>/dev/null && fuser -k -n tcp "$PORT" >/dev/null 2>&1 || true
  pkill -f indmoney_intraday_bot.py >/dev/null 2>&1 || true
  sleep 0.5
fi

step "Starting INDmoney Intraday Bot on port $PORT (log: $LOG)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
"$PY" -u indmoney_intraday_bot.py --port "$PORT" "${FORWARD_ARGS[@]}" 2>&1 | tee -a "$LOG"
