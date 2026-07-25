#!/usr/bin/env bash
set -euo pipefail

if [ "$PWD" = "/" ] || [ -z "${PWD:-}" ]; then
  echo "Error: no working directory set; run this from /app." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "${SCRIPT_DIR}/fit_tree.py" /app/fit_tree.py
chmod +x /app/fit_tree.py

python3 /app/fit_tree.py --data-dir /app/data --output-dir /app/output
