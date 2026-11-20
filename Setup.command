#!/bin/bash
set -e
cd "$(dirname "$0")"
export PYTHONUTF8=1
PYTHON=""
for candidate in /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 python3.11; do
 if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
if [ -z "$PYTHON" ]; then
 if command -v brew >/dev/null 2>&1; then
  brew install python@3.11 python-tk@3.11
  PYTHON="$(brew --prefix python@3.11)/bin/python3.11"
 else
  echo 'Install Python 3.11 including Tk from python.org (macOS universal2), then rerun Setup.command.'
  echo 'Alternatively install Homebrew and run: brew install python@3.11 python-tk@3.11'
  exit 1
 fi
fi
if ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
 echo 'Tk is missing. With Homebrew run: brew install python-tk@3.11'; exit 1
fi
if [ ! -x .venv/bin/python ]; then "$PYTHON" -m venv .venv; fi
.venv/bin/python setup.py "$@"
