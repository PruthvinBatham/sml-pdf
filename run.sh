#!/usr/bin/env bash
# Thin wrapper -- all the logic lives in run.py so macOS/Windows/Linux behave identically.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 run.py "$@"
