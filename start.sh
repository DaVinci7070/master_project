#!/bin/bash

# Lumari Start Script
# Starts Docker services, installs dependencies, and runs backend + frontend

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "========================================"
echo " Lumari - Starting Development Environment"
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
echo -e "\n${YELLOW}Checking prerequisites...${NC}"

if ! command_exists python3; then
    echo -e "${RED}Error: python3 not found${NC}"
    exit 1
fi

if ! command_exists node; then
    echo -e "${RED}Error: node not found. Install Node.js first.${NC}"
    exit 1
fi

if ! command_exists npm; then
    echo -e "${RED}Error: npm not found${NC}"
    exit 1
fi

if ! command_exists docker; then
    echo -e "${RED}Error: docker not found. Install Docker Desktop first.${NC}"
    exit 1
fi

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker Desktop.${NC}"
    exit 1
fi

echo -e "${GREEN}Prerequisites OK${NC}"

# ============================================
# Start Docker Services (PostgreSQL + Qdrant)
# ============================================
echo -e "\n${YELLOW}Starting Docker services...${NC}"

# Start postgres and qdrant
docker-compose up -d postgres qdrant

# Benchmark-DB (eigenes Compose-File, shared Network)
docker network inspect lumari-network >/dev/null 2>&1 || docker network create lumari-network
docker-compose -f docker-compose.benchmark.yml up -d benchmark-db

# Wait for Benchmark-DB to be healthy
echo "Waiting for Benchmark-DB..."
for i in {1..20}; do
    if docker exec lumari-benchmark-db pg_isready -U benchmark -d lumari_benchmark_db >/dev/null 2>&1; then
        echo -e "${GREEN}Benchmark-DB is ready${NC}"
        break
    fi
    if [ $i -eq 20 ]; then
        echo -e "${YELLOW}Benchmark-DB may still be initializing...${NC}"
    fi
    sleep 1
done

# Wait for PostgreSQL to be healthy
echo "Waiting for PostgreSQL..."
for i in {1..30}; do
    if docker-compose exec -T postgres pg_isready -U lumari -d lumari >/dev/null 2>&1; then
        echo -e "${GREEN}PostgreSQL is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}PostgreSQL failed to start${NC}"
        exit 1
    fi
    sleep 1
done

# Wait for Qdrant to be healthy
echo "Waiting for Qdrant..."
for i in {1..30}; do
    if curl -s http://localhost:6333/readyz >/dev/null 2>&1; then
        echo -e "${GREEN}Qdrant is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}Qdrant failed to start${NC}"
        exit 1
    fi
    sleep 1
done

echo -e "${GREEN}Docker services running${NC}"

# ============================================
# Backend Setup
# ============================================
echo -e "\n${YELLOW}Setting up Backend...${NC}"

# Create venv if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Install/upgrade pip
pip install --upgrade pip --quiet

# Install backend requirements
echo "Installing backend dependencies..."
pip install -r backend/requirements.txt --quiet

echo -e "${GREEN}Backend dependencies installed${NC}"

# ============================================
# Frontend Setup
# ============================================
echo -e "\n${YELLOW}Setting up Frontend...${NC}"
cd "$PROJECT_DIR/frontend"

# Install npm dependencies
echo "Installing frontend dependencies..."
npm install --silent 2>/dev/null || npm install

echo -e "${GREEN}Frontend dependencies installed${NC}"

# ============================================
# Start Application Services
# ============================================
echo -e "\n${YELLOW}Starting application...${NC}"

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    echo -e "${YELLOW}Stopping Docker services...${NC}"
    cd "$PROJECT_DIR"
    docker-compose stop postgres qdrant
    docker-compose -f docker-compose.benchmark.yml stop benchmark-db
    echo -e "${GREEN}Done${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start backend
echo "Starting backend on http://localhost:8000..."
cd "$PROJECT_DIR/backend"
source "$PROJECT_DIR/.venv/bin/activate"
mkdir -p logs
BACKEND_LOG="logs/backend_$(date +%Y%m%d_%H%M%S).log"
echo "Backend log: $BACKEND_LOG"
# Process Substitution: $! ist die uvicorn-PID (nicht die tee-PID)
python -m uvicorn app.main:app --reload --port 8000 > >(tee "$BACKEND_LOG") 2>&1 &
BACKEND_PID=$!

# Wait for backend to start
echo "Waiting for backend..."
for i in {1..30}; do
    if curl -s http://localhost:8000/health >/dev/null 2>&1; then
        echo -e "${GREEN}Backend is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}Backend may still be starting...${NC}"
    fi
    sleep 1
done

# ============================================
# Database Setup (Migrations + Seed Agents)
# ============================================
echo -e "\n${YELLOW}Running database migrations...${NC}"
cd "$PROJECT_DIR/backend"
python -m alembic upgrade head 2>/dev/null || echo -e "${YELLOW}Migrations may have already run${NC}"

echo -e "${YELLOW}Checking for agents in database...${NC}"
AGENT_COUNT=$(python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.core.config import settings

async def count_agents():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(text('SELECT COUNT(*) FROM agents'))
        count = result.scalar()
        print(count)

asyncio.run(count_agents())
" 2>/dev/null || echo "0")

if [ "$AGENT_COUNT" -lt "5" ]; then
    echo -e "${YELLOW}Only $AGENT_COUNT agents found. Seeding full agent topology...${NC}"
    python scripts/seed_agents.py
    echo -e "${GREEN}Agent topology seeded (Main Team + Developer Team)${NC}"
else
    echo -e "${GREEN}Found $AGENT_COUNT agents in database${NC}"
fi

# ETL-Testdaten generieren (für L5-Benchmark)
ETL_DIR="$PROJECT_DIR/backend/scripts/evaluation/data/etl_csvs"
if [ ! -d "$ETL_DIR" ] || [ -z "$(ls -A "$ETL_DIR" 2>/dev/null)" ]; then
    echo -e "${YELLOW}Generating ETL test data...${NC}"
    python scripts/evaluation/generate_etl_data.py
    echo -e "${GREEN}ETL test data generated${NC}"
fi

# Start frontend
echo "Starting frontend on http://localhost:3000..."
cd "$PROJECT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

# Wait for frontend
sleep 3

echo -e "\n${GREEN}========================================"
echo " Lumari is running!"
echo "========================================"
echo -e "${NC}"
echo "  Frontend:     http://localhost:3000"
echo "  Backend:      http://localhost:8000"
echo "  Health:       http://localhost:8000/health"
echo "  PostgreSQL:   localhost:5432"
echo "  Benchmark-DB: localhost:5433"
echo "  Qdrant:       http://localhost:6333"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Wait for processes
wait
