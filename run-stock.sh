#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────────────────────────────────────
# Stock dashboard launcher
#   bash run-stock.sh                → install deps, then start stock_dashboard.py
#   bash run-stock.sh --no-install   → skip the install step (fast restart)
#   bash run-stock.sh --check        → install deps and verify imports only
#   bash run-stock.sh --port 9091    → serve on a different port
# Any other args are forwarded to stock_dashboard.py.
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
PORT=9090
DO_INSTALL=1
DO_RUN=1
FORWARD_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-install|--skip-install) DO_INSTALL=0 ;;
    --check)                    DO_RUN=0 ;;
    --port)
      [[ $# -ge 2 ]] || { err "--port needs a value"; exit 1; }
      PORT="$2"; shift ;;
    --port=*)                   PORT="${1#*=}" ;;
    -h|--help)                  DO_RUN=0; DO_INSTALL=0; SHOW_HELP=1 ;;
    *)                          FORWARD_ARGS+=("$1") ;;
  esac
  shift
done

if [[ "${SHOW_HELP:-0}" -eq 1 ]]; then
  cat <<'EOF'
Usage: bash run-stock.sh [options] [-- stock_dashboard args]

Options:
  (none)         Install dependencies (if needed) and start the stock dashboard
  --no-install   Skip the dependency install step (fast restart)
  --check        Install dependencies and verify imports, then exit
  --port N       Serve on port N (default: 9090)
  -h, --help     Show this help

Environment:
  JARVIS_PYTHON   Python version for .venv (default: 3.13)
  STOCK_PORT      Default port when neither --port nor args specify one (default: 9090)
EOF
  exit 0
fi

PORT="${STOCK_PORT:-$PORT}"
LOG="stock_dashboard.server.log"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Stock Dashboard Launcher"
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

# ── 4. Free the port (warn only) ───────────────────────
if curl -sf -m 2 "http://localhost:$PORT" >/dev/null 2>&1; then
  warn "Port $PORT already serving — killing stale process"
  command -v fuser &>/dev/null && fuser -k -n tcp "$PORT" >/dev/null 2>&1 || true
  pkill -f stock_dashboard.py >/dev/null 2>&1 || true
  for _ in $(seq 30); do
    curl -sf -m 1 "http://localhost:$PORT" >/dev/null 2>&1 || break
    sleep 0.1
  done
fi

# ── 5. Verify / run ────────────────────────────────────
if [[ "$DO_RUN" -eq 0 ]]; then
  step "Verifying imports"
  "$PY" - <<'PYEOF'
required = ["numpy", "pandas", "yfinance", "requests"]
bad = []
for m in required:
    try:
        __import__(m)
    except Exception as e:
        bad.append(f"{m}: {type(e).__name__}: {e}")
if bad:
    print("\n".join("  x " + b for b in bad))
    raise SystemExit(1)
print(f"  all {len(required)} required imports OK")
PYEOF
  info "Check passed"
  exit 0
fi

echo ""
step "Starting stock dashboard on port $PORT (log: $LOG)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
"$PY" -u stock_dashboard.py --port "$PORT" "${FORWARD_ARGS[@]}" 2>&1 | tee -a "$LOG"