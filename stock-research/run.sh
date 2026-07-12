#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Ensure npm global bin is in PATH (for @brightdata/mcp)
export PATH="$HOME/.npm-global/bin:$PATH"

# Activate Python venv
source ../.venv/bin/activate

exec streamlit run app.py "$@"
