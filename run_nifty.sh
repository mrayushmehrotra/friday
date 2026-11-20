#!/usr/bin/env bash
set -e

# Run NIFTY 50 Monte Carlo simulation with PineScript Strategy
# Defaults to 15m timeframe, ATR Trail, 5000 simulation paths

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

INTERVAL="${1:-15minute}"
SIMS="${2:-5000}"
TRAIL="${3:-ATR Trail}"

echo "[*] Running NIFTY 50 Monte Carlo Simulation..."
echo "    Timeframe:   $INTERVAL"
echo "    Simulations: $SIMS"
echo "    Trail Mode:  $TRAIL"

./.venv/bin/python monte_carlo_pinescript.py \
  --symbols "NIFTY" \
  --interval "$INTERVAL" \
  --simulations "$SIMS" \
  --trail-mode "$TRAIL" \
  --html "nifty_pinescript_monte_carlo_${INTERVAL}.html"

echo "[+] Done! Dashboard generated at: nifty_pinescript_monte_carlo_${INTERVAL}.html"
