#!/usr/bin/env bash
# Start Machaa on this computer. Leave the window open while you use it.
set -euo pipefail
cd "$(dirname "$0")"

echo "Machaa will be at http://127.0.0.1:8787"
echo "Leave this window open. Press Ctrl+C to stop."
echo

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed."
  echo "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and run this script again."
  exit 1
fi

exec docker compose up --build
