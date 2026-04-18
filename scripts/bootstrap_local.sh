#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "python3.12 is required" >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3.12 -m venv .venv
fi

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"

mkdir -p data certs

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

if ! command -v mkcert >/dev/null 2>&1; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
    brew install mkcert
  else
    echo "mkcert is required and was not found on PATH" >&2
    exit 1
  fi
fi

mkcert -install
mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem 127.0.0.1 localhost

DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./data/darth_schwader.db}" \
  .venv/bin/alembic upgrade head

echo "Bootstrap complete."
