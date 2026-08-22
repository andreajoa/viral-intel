#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [ -x "/opt/homebrew/bin/brew" ]; then
  export PATH="/opt/homebrew/bin:$PATH"
elif [ -x "/usr/local/bin/brew" ]; then
  export PATH="/usr/local/bin:$PATH"
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "O ambiente ainda não foi instalado. Execute primeiro: ./setup.sh"
  exit 1
fi

VENV_VERSION="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "$VENV_VERSION" != "3.11" ] && [ "$VENV_VERSION" != "3.12" ]; then
  echo "O ambiente usa Python $VENV_VERSION, que não é compatível com o processamento de vídeo."
  echo "Execute novamente: ./setup.sh"
  exit 1
fi

source .venv/bin/activate
UPLOAD_LIMIT_MB="$(python -c 'from app.config import get_settings; print(get_settings().max_upload_mb)')"

# O mesmo bootstrap é usado localmente e na nuvem, mas o marcador abaixo impede que
# defaults efêmeros do Community Cloud sobrescrevam a configuração local do .env.
export VIRAL_INTEL_EXECUTION=local
exec python -m streamlit run cloud/streamlit_app.py \
  --server.headless=false \
  --server.address=127.0.0.1 \
  --server.maxUploadSize="$UPLOAD_LIMIT_MB" \
  --server.showEmailPrompt=false \
  --browser.gatherUsageStats=false
