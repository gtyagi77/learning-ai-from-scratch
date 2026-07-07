#!/usr/bin/env bash
# Start the VoiceForge local server. Serves the web UI and the /api backend
# from one process at http://127.0.0.1:8080
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8080}"
VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "Creating virtualenv in $VENV …"
  python3 -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  echo "Installing dependencies (this downloads PyTorch; may take a few minutes)…"
  pip install --upgrade pip
  pip install -r server/requirements.txt
else
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

echo ""
echo "VoiceForge running at http://127.0.0.1:${PORT}"
echo "Set VOICEFORGE_FAKE_TTS=1 to run the UI without downloading the model."
echo ""
exec uvicorn server.main:app --host 127.0.0.1 --port "$PORT"
