#!/bin/bash
set -e
cd "$(dirname "$0")"
export PYTHONUTF8=1
if [ ! -f .setup-complete ] || [ ! -x .venv/bin/python ]; then bash Setup.command; fi
exec .venv/bin/python -m streamlit run dashboard.py --server.address 127.0.0.1 "$@"
