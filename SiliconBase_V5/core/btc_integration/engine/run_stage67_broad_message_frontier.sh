#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "[1/2] stage64 relevance hybrid"
bash run_stage64_relevance_hybrid.sh

echo "[2/2] stage65 price-impact frontier"
bash run_stage65_price_impact_frontier.sh

echo "[OK] broad message frontier done"
echo "bundle: ~/Downloads/chatgpt_bundle_latest.zip"
echo "deepseek: ~/Downloads/deepseek_single_file_latest.txt"
echo "note: do NOT run bash run_send_files.sh after this round"
