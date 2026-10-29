#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m tracepatch demo --out "${1:-runs/demo_local}" --provider offline
