#!/bin/bash
# Jednorázová instalace hlasu Bona na Macu (Apple Silicon M1/M2/M3/M4). Vše zdarma.
cd "$(dirname "$0")"
set -e
echo "== Vytvářím prostředí .venv =="
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
echo "== Instaluji Whisper (mlx), mikrofon, český hlas =="
.venv/bin/pip install mlx-whisper sounddevice numpy edge-tts
echo "== Stahuji model Whisper (~1,6 GB, jen poprvé) =="
.venv/bin/python -c "import mlx_whisper, numpy as np; mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo='mlx-community/whisper-large-v3-turbo'); print('Whisper OK')"
echo ""
echo "Hotovo! Bona spustíš příkazem:  bash start_mac.sh"
