#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created vllm/.env from template. Edit if needed (HF cache path, HF token)."
fi

docker compose up -d
echo
echo "vLLM is starting. First boot downloads ~17 GB if Qwen3-32B-AWQ isn't cached."
echo "Tail logs:    docker compose logs -f"
echo "Health:       curl -s http://localhost:8000/health"
echo "Models:       curl -s http://localhost:8000/v1/models | jq"
