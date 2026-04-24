#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# BlastRadius — local dev startup script
# Usage: ./start.sh [--docker]
# ─────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

banner() {
  echo ""
  echo -e "${BOLD}${RED}  ▸ BlastRadius${RESET}${BOLD} — Pre-merge Impact Intelligence${RESET}"
  echo -e "  ${YELLOW}IBM Bob Hackathon 2026${RESET}"
  echo ""
}

check_env() {
  if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠  .env not found — copying from .env.example${RESET}"
    cp .env.example .env
    echo -e "${RED}   ✗ Add your API keys to .env before running analysis${RESET}"
    echo ""
  else
    echo -e "${GREEN}✓ .env found${RESET}"
  fi
}

run_docker() {
  banner
  check_env
  echo -e "${BLUE}▸ Starting with Docker Compose…${RESET}"
  docker-compose up --build
}

run_local() {
  banner
  check_env

  # ── Check Python ──────────────────────────────────────────────
  if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ python3 not found. Install Python 3.12+${RESET}"
    exit 1
  fi
  echo -e "${GREEN}✓ Python: $(python3 --version)${RESET}"

  # ── Backend venv ──────────────────────────────────────────────
  if [ ! -d "backend/.venv" ]; then
    echo -e "${BLUE}▸ Creating virtual environment…${RESET}"
    python3 -m venv backend/.venv
  fi

  source backend/.venv/bin/activate

  echo -e "${BLUE}▸ Installing backend dependencies…${RESET}"
  pip install -q -r backend/requirements.txt
  echo -e "${GREEN}✓ Dependencies installed${RESET}"

  # ── Run tests first ───────────────────────────────────────────
  echo ""
  echo -e "${BLUE}▸ Running smoke tests…${RESET}"
  cd backend
  if python -m pytest test_pipeline.py -v --tb=short -q 2>&1; then
    echo -e "${GREEN}✓ All tests passed${RESET}"
  else
    echo -e "${YELLOW}⚠  Some tests failed — check output above${RESET}"
    echo -e "   (The server will still start — tests don't block startup)"
  fi
  cd ..

  # ── Start backend in background ───────────────────────────────
  echo ""
  echo -e "${BLUE}▸ Starting FastAPI backend on :8000…${RESET}"
  cd backend
  uvicorn main:app --reload --port 8000 --log-level warning &
  BACKEND_PID=$!
  cd ..

  # Wait for backend to be ready
  echo -n "  Waiting for backend"
  for i in $(seq 1 20); do
    if curl -sf http://localhost:8000/api/health &>/dev/null; then
      echo -e " ${GREEN}✓${RESET}"
      break
    fi
    echo -n "."
    sleep 0.5
  done

  # ── Start frontend ────────────────────────────────────────────
  echo -e "${BLUE}▸ Starting frontend on :3000…${RESET}"

  if command -v npx &>/dev/null; then
    npx --yes serve frontend -l 3000 &>/dev/null &
    FRONTEND_PID=$!
    FRONTEND_CMD="npx serve"
  elif command -v python3 &>/dev/null; then
    cd frontend && python3 -m http.server 3000 &>/dev/null &
    FRONTEND_PID=$!
    cd ..
    FRONTEND_CMD="python3 -m http.server"
  else
    echo -e "${YELLOW}⚠  No static server found. Open frontend/index.html manually.${RESET}"
    FRONTEND_PID=""
    FRONTEND_CMD="none"
  fi

  # ── Ready ──────────────────────────────────────────────────────
  echo ""
  echo -e "${BOLD}${GREEN}  ✓ BlastRadius is running!${RESET}"
  echo ""
  echo -e "  ${BOLD}Frontend:${RESET}   ${BLUE}http://localhost:3000${RESET}"
  echo -e "  ${BOLD}API:${RESET}        ${BLUE}http://localhost:8000${RESET}"
  echo -e "  ${BOLD}API docs:${RESET}   ${BLUE}http://localhost:8000/docs${RESET}"
  echo -e "  ${BOLD}Demo:${RESET}       ${BLUE}http://localhost:8000/api/demo${RESET}"
  echo ""
  echo -e "  Press ${BOLD}Ctrl+C${RESET} to stop all servers."
  echo ""

  # ── Cleanup on exit ───────────────────────────────────────────
  cleanup() {
    echo ""
    echo -e "${BLUE}▸ Shutting down…${RESET}"
    kill $BACKEND_PID 2>/dev/null || true
    [ -n "$FRONTEND_PID" ] && kill $FRONTEND_PID 2>/dev/null || true
    echo -e "${GREEN}✓ Done${RESET}"
  }
  trap cleanup EXIT INT TERM

  # Keep script alive
  wait $BACKEND_PID
}

# ── Entry point ────────────────────────────────────────────────────
if [ "${1}" == "--docker" ]; then
  run_docker
else
  run_local
fi
