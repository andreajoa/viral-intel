#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

BREW_BIN=""
if command -v brew >/dev/null 2>&1; then
  BREW_BIN="$(command -v brew)"
elif [ -x "/opt/homebrew/bin/brew" ]; then
  BREW_BIN="/opt/homebrew/bin/brew"
elif [ -x "/usr/local/bin/brew" ]; then
  BREW_BIN="/usr/local/bin/brew"
fi

if [ -n "$BREW_BIN" ]; then
  export PATH="$(dirname "$BREW_BIN"):$PATH"
fi

SUPPORTED_PYTHON=""
for candidate in python3.12 python3.11; do
  if command -v "$candidate" >/dev/null 2>&1; then
    SUPPORTED_PYTHON="$(command -v "$candidate")"
    break
  fi
done

if [ -z "$SUPPORTED_PYTHON" ] && [ -n "$BREW_BIN" ]; then
  echo "Python 3.11/3.12 não foi encontrado. Instalando Python 3.12 com Homebrew..."
  "$BREW_BIN" install python@3.12
  SUPPORTED_PYTHON="$("$BREW_BIN" --prefix python@3.12)/bin/python3.12"
fi

if [ -z "$SUPPORTED_PYTHON" ] || [ ! -x "$SUPPORTED_PYTHON" ]; then
  echo "Este projeto precisa do Python 3.11 ou 3.12. Python 3.14 não é compatível com onnxruntime/faster-whisper."
  echo "No Mac, instale com: brew install python@3.12"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  if [ -n "$BREW_BIN" ]; then
    echo "FFmpeg não foi encontrado. Instalando com Homebrew..."
    "$BREW_BIN" install ffmpeg
  else
    echo "FFmpeg não foi encontrado. No Mac, instale com: brew install ffmpeg"
    exit 1
  fi
fi

if [ -x ".venv/bin/python" ]; then
  VENV_VERSION="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  if [ "$VENV_VERSION" != "3.11" ] && [ "$VENV_VERSION" != "3.12" ]; then
    BACKUP_DIR=".venv-incompativel-$(date +%Y%m%d-%H%M%S)"
    echo "O ambiente atual usa Python ${VENV_VERSION:-desconhecido}. Movendo para $BACKUP_DIR..."
    mv .venv "$BACKUP_DIR"
  fi
fi

if [ ! -d ".venv" ]; then
  "$SUPPORTED_PYTHON" -m venv .venv
fi

source .venv/bin/activate
echo "Usando $(python --version) em $PROJECT_DIR/.venv"
python -m pip install --upgrade pip wheel
python -m pip install --only-binary=pyarrow,numpy,pandas -c constraints.txt -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Foi criado o arquivo .env. Abra-o e adicione pelo menos uma chave de IA."
fi

python -m unittest discover -s tests -v

echo ""
echo "Instalação concluída. Para abrir o Viral Intel:"
echo "  cd \"$PROJECT_DIR\""
echo "  ./run.sh"
