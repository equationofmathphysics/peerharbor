#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  echo '缺少 .venv，请先按 README 安装 Python 依赖。' >&2
  exit 1
fi
exec .venv/bin/python local_launcher.py "$@"
