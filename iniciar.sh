#!/bin/bash
# Arranca el editor en http://localhost:8000
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Instalando dependencias (solo la primera vez)..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
command -v ffmpeg >/dev/null || { echo "Falta ffmpeg. Instalalo con: brew install ffmpeg"; exit 1; }
(sleep 1.5 && open http://localhost:8000) &
exec .venv/bin/uvicorn app.main:app --port 8000
