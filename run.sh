#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# O Homebrew de Macs Apple Silicon nem sempre entra no PATH de shells antigos.
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
exec python -m streamlit run app/ui/dashboard.py --server.headless=false
