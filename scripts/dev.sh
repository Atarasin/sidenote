#!/usr/bin/env bash
# sidenote 一键开发环境（计划 T0.1.4）：后端 FastAPI + 前端 Vite。
# 用法：scripts/dev.sh  （Git Bash / Linux / macOS）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 定位 Python 解释器：优先仓库 .venv（含 worktree 场景向上查找），回退系统 python
PY=""
if [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="$(command -v python || command -v python3)"
fi
echo "[dev] python: $PY"

BACK_PID=""
FRONT_PID=""

cleanup() {
  echo "[dev] shutting down..."
  [[ -n "$BACK_PID" ]] && kill "$BACK_PID" 2>/dev/null || true
  [[ -n "$FRONT_PID" ]] && kill "$FRONT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 后端：uvicorn（端口 8787）
(cd "$ROOT/apps/server" && "$PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8787) &
BACK_PID=$!

# 前端：vite dev server（端口 5173，/api 代理到 8787）
if [[ ! -d "$ROOT/apps/web/node_modules" ]]; then
  echo "[dev] 前端依赖未安装，执行 npm install..."
  (cd "$ROOT/apps/web" && npm install)
fi
(cd "$ROOT/apps/web" && npm run dev) &
FRONT_PID=$!

echo "[dev] 前端: http://localhost:5173  后端: http://127.0.0.1:8787/api/health"
wait
