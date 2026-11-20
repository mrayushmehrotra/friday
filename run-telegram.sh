#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────────────────────────────────────
# Telegram institution-deal watcher launcher
#   bash run-telegram.sh               → install deps, then poll forever
#   bash run-telegram.sh --once        → run a single poll cycle and exit
#   bash run-telegram.sh --status      → show config/state summary and exit
#   bash run-telegram.sh --test        → send a test Telegram message and exit
#   bash run-telegram.sh --no-install  → skip the install step (fast start)
# Any other args are forwarded to institution_telegram_bot.py.
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
PY_VERSION="${JARVIS_PYTHON:-3.13}"
DO_INSTALL=1
FORWARD_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --no-install|--skip-install) DO_INSTALL=0 ;;
    -h|--help)                   SHOW_HELP=1 ;;
    *)                           FORWARD_ARGS+=("$arg") ;;
  esac
done

if [[ "${SHOW_HELP:-0}" -eq 1 ]]; then
  cat <<'EOF'
Usage: bash run-telegram.sh [options] [watcher args]

Options:
  (none)         Install dependencies (if needed), then poll forever
  --no-install   Skip the dependency install step (fast start)
  -h, --help     Show this help

Watcher args (forwarded to institution_telegram_bot.py):
  --once             Run one poll cycle, then exit
  --test             Send a test Telegram message, then exit
  --status           Print config/state summary, then exit
  --interval N       Poll every N minutes (default: 30 from config)
  --max-age-days N   Only alert deals newer than N days (default: 10)

Note: `bash run.sh` also starts this watcher automatically alongside Jarvis.
Use `bash run.sh --no-telegram` to disable it there.
EOF
  exit 0
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Telegram Deal Watcher"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. uv ──────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  warn "uv not found — installing it"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv &>/dev/null || { err "uv install failed"; exit 1; }
fi
info "uv $(uv --version | awk '{print $2}')"

# ── 2. Virtualenv ──────────────────────────────────────
if [[ ! -x "$VENV/bin/python" ]]; then
  step "Creating $VENV with Python $PY_VERSION"
  uv venv --python "$PY_VERSION" "$VENV"
  DO_INSTALL=1
fi
PY="$VENV/bin/python"
info "Python $("$PY" --version | awk '{print $2}') at $PY"

# ── 3. Dependencies ────────────────────────────────────
if [[ "$DO_INSTALL" -eq 1 ]]; then
  step "Installing requirements"
  if uv pip install --python "$PY" -r requirements.txt; then
    info "Dependencies installed"
  else
    err "Dependency install failed"
    exit 1
  fi
else
  info "Skipping install (--no-install)"
fi

echo ""
step "Starting Telegram watcher"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exec "$PY" institution_telegram_bot.py "${FORWARD_ARGS[@]}"
