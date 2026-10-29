#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m tracepatch v2-demo --out "${1:-runs/v2_demo_local}"
