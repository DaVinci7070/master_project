#!/usr/bin/env bash
set -euo pipefail

ROLE="${ROLE:-agent_orchestrator}"
PORT="${PORT:-8000}"

# Projektroot im Container – passt zu COPY . /app/a2a-multi-agent
APP_ROOT="${APP_ROOT:-/app/a2a-multi-agent}"

echo "Using APP_ROOT=${APP_ROOT}"
cd "${APP_ROOT}"

case "$ROLE" in
  agent_orchestrator|orchestrator)
    echo "Starting Orchestrator on port ${PORT}..."
    exec uvicorn agents.orchestrator_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_rag|rag)
    echo "Starting RAG agent on port ${PORT}..."
    exec uvicorn agents.rag_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_summarizer|summarizer)
    echo "Starting Summarizer agent on port ${PORT}..."
    exec uvicorn agents.summarizer_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_guard|guard)
    echo "Starting Guard agent on port ${PORT}..."
    exec uvicorn agents.guard_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_template|template)
    echo "Starting Template agent on port ${PORT}..."
    exec uvicorn agents.template_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_question|question)
    echo "Starting Question agent on port ${PORT}..."
    exec uvicorn agents.question_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_defect|defect)
    echo "Starting Defect agent on port ${PORT}..."
    exec uvicorn agents.defect_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_safety|safety)
    echo "Starting Safety agent on port ${PORT}..."
    exec uvicorn agents.safety_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_claim|claim)
    echo "Starting Claim agent on port ${PORT}..."
    exec uvicorn agents.claim_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  agent_quality|quality)
    echo "Starting Quality agent on port ${PORT}..."
    exec uvicorn agents.quality_agent.app:create_app \
      --host 0.0.0.0 --port "${PORT}" --factory
    ;;
  *)
    echo "Unknown ROLE: ${ROLE}" >&2
    exit 1
    ;;
esac
