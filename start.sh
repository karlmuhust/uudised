#!/bin/sh
# Start Uudised on this computer: http://localhost:8765
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] && set -a && . ./.env && set +a
exec python -m pipeline.serve "$@"
