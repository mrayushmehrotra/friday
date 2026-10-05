#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────────────────────────────────────
# Jarvis launcher
#   bash run.sh              → install deps, then start Jarvis
#   bash run.sh --no-install → skip the install step (fast restart)
#   bash run.sh --check      → install deps and verify imports only
# Any other args are forwarded to jarvis.py.
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
DO_RUN=1
FORWARD_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --no-install|--skip-install) DO_INSTALL=0 ;;
    --check)                    DO_RUN=0 ;;
    --audio-check)              DO_RUN=0; DO_INSTALL=0; AUDIO_CHECK=1 ;;
    -h|--help)                  DO_RUN=0; DO_INSTALL=0; SHOW_HELP=1 ;;
    *)                          FORWARD_ARGS+=("$arg") ;;
  esac
done

if [[ "${SHOW_HELP:-0}" -eq 1 ]]; then
  cat <<'EOF'
Usage: bash run.sh [options] [-- jarvis args]

Options:
  (none)         Install dependencies (if needed) and start Jarvis
  --no-install   Skip the dependency install step (fast restart)
  --check        Install dependencies and verify imports, then exit
  --audio-check  Diagnose the voice chain (TTS, microphone, STT) and exit
  -h, --help     Show this help

Environment:
  JARVIS_PYTHON            Python version for .venv (default: 3.13)
  JARVIS_LLM_ENDPOINT      Ollama base URL (default: http://localhost:11434)
  JARVIS_LLM_MODEL         Ollama model (default: qwen2.5:0.5b)
  GROQ_API_KEY, HF_TOKEN   Loaded from .env
EOF
  exit 0
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Jarvis Launcher"
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

# ── 4. Optional system deps (warn only) ────────────────
command -v ffplay &>/dev/null || warn "ffplay missing — background music disabled (apt install ffmpeg)"
command -v paplay &>/dev/null || command -v pw-play &>/dev/null ||
  warn "no paplay/pw-play — speech output disabled (pacman -S pulseaudio-utils pipewire)"
command -v wpctl  &>/dev/null || warn "wpctl missing — mic mute/unmute disabled (pacman -S wireplumber)"
if ! curl -sf -m 2 http://localhost:11434 >/dev/null 2>&1; then
  warn "Ollama not reachable on :11434 — start it, or set JARVIS_LLM_ENDPOINT"
fi

# ── 5. Verify / run ────────────────────────────────────
if [[ "${AUDIO_CHECK:-0}" -eq 1 ]]; then
  step "Checking audio chain"
  exec "$PY" -c "
import sys, helpers
sys.exit(0 if helpers.audio_diagnostics() else 1)
"
fi

if [[ "$DO_RUN" -eq 0 ]]; then
  step "Verifying imports"
  "$PY" - <<'PYEOF'
required = [
    "langchain_ollama", "langgraph", "chromadb", "dotenv", "groq", "lxml",
    "piper", "pyttsx3", "speech_recognition", "pyperclip",
    "mcp", "numpy", "pandas", "requests", "yfinance",
]
optional = ["pyautogui", "pyaudio", "mediapipe", "cv2"]

bad, soft = [], []
for m in required:
    try:
        __import__(m)
    except Exception as e:
        bad.append(f"{m}: {type(e).__name__}: {e}")
for m in optional:
    try:
        __import__(m)
    except Exception as e:
        soft.append(f"{m}: {type(e).__name__}: {e}")

for s in soft:
    print(f"  ~ {s} (non-fatal)")
if bad:
    print("\n".join("  x " + b for b in bad))
    raise SystemExit(1)
print(f"  all {len(required)} required imports OK")
PYEOF
  info "Check passed"
  exit 0
fi

echo ""
step "Starting Jarvis"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exec "$PY" jarvis.py "${FORWARD_ARGS[@]}"