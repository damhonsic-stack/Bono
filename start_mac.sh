#!/bin/bash
# Spustí Bona na Macu s hlasem (mikrofon + Whisper + český hlas). Mac nebude usínat.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Nejdřív jednou spusť:  bash setup_mac.sh"; exit 1
fi
exec caffeinate -di .venv/bin/python server.py --voice "$@"
