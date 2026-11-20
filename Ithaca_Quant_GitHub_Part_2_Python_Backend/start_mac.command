#!/bin/bash
set -eu
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python3 -m pip install -r backend/requirements.txt
python3 backend/server.py
