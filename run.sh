#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PY=$(command -v python3 || command -v python)
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  NEW_VENV=1
fi
if [ -x .venv/Scripts/python.exe ]; then VPY=.venv/Scripts/python.exe; else VPY=.venv/bin/python; fi
[ -n "$NEW_VENV" ] && "$VPY" -m pip install -r requirements.txt

exec "$VPY" app.py
