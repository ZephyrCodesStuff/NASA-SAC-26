#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/deploy.sh <ssh-host>
#   or:  DEPLOY_HOST=my-vps ./scripts/deploy.sh

HOST="${1:-${DEPLOY_HOST:-}}"
REMOTE_DIR="${REMOTE_DIR:-/root/NASA-SAC-26}"

if [[ -z "$HOST" ]]; then
  echo "Usage: $0 <ssh-host>"
  echo "  e.g. $0 root@1.2.3.4"
  echo "  or:  DEPLOY_HOST=prod-vps $0"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Syncing ${REPO_ROOT}/ -> ${HOST}:${REMOTE_DIR}/"
ssh "$HOST" "mkdir -p '${REMOTE_DIR}'"

rsync -avz --delete \
  --include='.env.example' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='node_modules/' \
  --exclude='.next/' \
  --exclude='out/' \
  --exclude='build/' \
  --exclude='dist/' \
  --exclude='.turbo/' \
  --exclude='coverage/' \
  --exclude='*.tsbuildinfo' \
  --exclude='__pycache__/' \
  --exclude='*.py[cod]' \
  --exclude='*.egg-info/' \
  --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.DS_Store' \
  --exclude='.cache/' \
  --exclude='.nicegui/' \
  --exclude='pocketbase/pb_data/' \
  --exclude='data/' \
  "${REPO_ROOT}/" "${HOST}:${REMOTE_DIR}/"

echo "==> Running docker compose up -d --build on ${HOST}"
ssh "$HOST" "cd '${REMOTE_DIR}' && docker compose up -d --build"

echo "==> Deploy complete."
