#!/usr/bin/env bash
set -euo pipefail

# ───────────────────────────────────────────────────────
# Ollama + Jarvis performance tuner
# Run once:  bash optimize.sh
# Reboot or restart ollama after.
# ───────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Ollama & Jarvis Optimizer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Detect CPU cores ────────────────────────────────
CORES=$(nproc 2>/dev/null || echo 2)
THREADS=$(( CORES > 2 ? CORES / 2 : CORES ))
info "Detected $CORES logical CPUs — will use $THREADS threads"

# ── 2. Create persistent systemd drop-in ───────────────
OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
OVERRIDE_FILE="$OVERRIDE_DIR/override.conf"

info "Creating persistent Ollama config at $OVERRIDE_FILE"
sudo mkdir -p "$OVERRIDE_DIR"

cat <<EOF | sudo tee "$OVERRIDE_FILE" > /dev/null
[Service]
# Keep model loaded in RAM (no cold start delay)
Environment="OLLAMA_KEEP_ALIVE=-1"
# Flash attention — faster attention, less memory bandwidth
Environment="OLLAMA_FLASH_ATTENTION=1"
# Single request at a time (2-core CPU can't benefit from parallel)
Environment="OLLAMA_NUM_PARALLEL=1"
# Cap CPU to ~40% of total (comment out if you want full speed)
CPUQuota=80%
EOF

info "Reloading systemd and restarting Ollama"
sudo systemctl daemon-reload
sudo systemctl restart ollama
info "Ollama restarted with optimized settings"

# ── 3. Verify the model exists locally ─────────────────
MODEL="qwen3:1.7b"
info "Checking model $MODEL"
if ollama list 2>/dev/null | grep -q "$MODEL"; then
    info "Model $MODEL is already pulled"
else
    warn "Model $MODEL not found locally"
    echo -n "Pull it now? [y/N] "
    read -r ans
    if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
        ollama pull "$MODEL"
    fi
fi

# ── 4. Optional: cpulimit guard (extra safety) ─────────
if command -v cpulimit &>/dev/null; then
    warn "cpulimit is installed — you can run:"
    echo "  sudo cpulimit -e ollama -l 40 -b"
    echo "to hard-cap Ollama at 40% CPU at all times."
else
    echo ""
    warn "cpulimit not installed (optional)."
    echo "  Install:  sudo apt install cpulimit"
    echo "  Then:     sudo cpulimit -e ollama -l 40 -b"
fi

# ── 5. CPU governor hint ───────────────────────────────
GOV=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo "unknown")
if [[ "$GOV" != "performance" ]]; then
    echo ""
    warn "CPU governor is '$GOV' (not 'performance')"
    echo "  For lower latency:  sudo cpupower frequency-set -g performance"
    echo "  (reverts on reboot, or set via /etc/default/cpufrequtils)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Done. Changes are persistent."
echo "  Reboot or run:"
echo "    sudo systemctl restart ollama"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
