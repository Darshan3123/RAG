#!/usr/bin/env bash
# =========================================================================
# start_workers.sh
# GeMBridge Multi-Worker Distributed Process Launcher for Linux / WSL
# Launches 3 dedicated queue workers (Scraper, Document, ATC/RAG)
# =========================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Detect Python & Celery binaries
if [ -n "$VIRTUAL_ENV" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
    CELERY_BIN="$VIRTUAL_ENV/bin/celery"
    UVICORN_BIN="$VIRTUAL_ENV/bin/uvicorn"
elif [ -d "$PROJECT_ROOT/.venv_linux" ]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv_linux/bin/python"
    CELERY_BIN="$PROJECT_ROOT/.venv_linux/bin/celery"
    UVICORN_BIN="$PROJECT_ROOT/.venv_linux/bin/uvicorn"
else
    PYTHON_BIN="$(command -v python3 || command -v python)"
    CELERY_BIN="$(command -v celery)"
    UVICORN_BIN="$(command -v uvicorn)"
fi

PID_FILE="$PROJECT_ROOT/logs/workers.pid"
mkdir -p "$PROJECT_ROOT/logs"

# Flags
STOP=false
WITH_BEAT=false
WITH_FLOWER=false
WITH_GATEWAY=false
NO_SCRAPER=false
CONCURRENCY=6

# Parse arguments (supports both PowerShell -WithStyle and Linux --style)
while [[ $# -gt 0 ]]; do
    case "$1" in
        -Stop|--stop|-stop)
            STOP=true
            shift
            ;;
        -WithBeat|--with-beat|--beat)
            WITH_BEAT=true
            shift
            ;;
        -WithFlower|--with-flower|--flower)
            WITH_FLOWER=true
            shift
            ;;
        -WithGateway|--with-gateway|--gateway)
            WITH_GATEWAY=true
            shift
            ;;
        -NoScraper|--no-scraper)
            NO_SCRAPER=true
            shift
            ;;
        -c|--concurrency|-Concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        -c=*|--concurrency=*|-Concurrency=*)
            CONCURRENCY="${1#*=}"
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: ./start_workers.sh [-c <workers>] [-WithGateway] [-WithBeat] [-WithFlower] [-NoScraper] [-Stop]"
            exit 1
            ;;
    esac
done

# If stop requested
if [ "$STOP" = true ]; then
    echo -e "\033[1;33m[*] Stopping all running GeMBridge Celery, Beat, Flower, and Gateway processes...\033[0m"
    if [ -f "$PID_FILE" ]; then
        while read -r pid; do
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi
    # Also catch any lingering processes by name
    pkill -f "tasks.celery_app" 2>/dev/null || true
    pkill -f "gateway.main:app" 2>/dev/null || true
    pkill -f "flower" 2>/dev/null || true
    echo -e "\033[1;32m[OK] All workers and gateway stopped.\033[0m"
    exit 0
fi

echo -e "\033[1;36m=======================================================================\033[0m"
echo -e "\033[1;36m GeMBridge Multi-Worker Pipeline Launcher - Linux / WSL\033[0m"
echo -e "\033[1;36m Mode: Queue Isolation (3 Dedicated Independent OS Processes)\033[0m"
echo -e "\033[1;36m=======================================================================\033[0m"

# 1. Check Redis
echo -n "[1/3] Checking Redis Broker on localhost:6379... "
if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null; then
    echo -e "\033[1;32m[ONLINE (local)]\033[0m"
elif command -v docker &>/dev/null && docker exec redis-server-gem redis-cli ping 2>/dev/null | grep -q "PONG"; then
    echo -e "\033[1;32m[ONLINE (Docker: redis-server-gem)]\033[0m"
else
    # Try Python socket test
    if "$PYTHON_BIN" -c "import socket; s = socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', 6379)); s.close(); print('OK')" 2>/dev/null | grep -q "OK"; then
        echo -e "\033[1;32m[ONLINE]\033[0m"
    else
        echo -e "\033[1;31m[OFFLINE]\033[0m"
        echo -e "\033[0;31m[-] Redis is not reachable on localhost:6379. Please start Redis container or service.\033[0m"
        exit 1
    fi
fi

# Clean up old PID file
> "$PID_FILE"

# 2. Launch Workers
echo -e "\033[1;36m[2/3] Launching Celery Worker Queues in background (Concurrency: $CONCURRENCY per worker)...\033[0m"

# Tier 1: Scraper
if [ "$NO_SCRAPER" = false ]; then
    echo -e "  -> Starting \033[1;33mTier 1: Scraper Worker [scraping_queue] (concurrency=$CONCURRENCY)\033[0m..."
    nohup "$CELERY_BIN" -A tasks.celery_app worker -Q scraping_queue -c "$CONCURRENCY" -n worker_scraper@local --loglevel=INFO > "$PROJECT_ROOT/logs/worker_scraper.log" 2>&1 &
    echo $! >> "$PID_FILE"
else
    echo "  [*] Skipping Tier 1 Scraper Worker (--no-scraper)."
fi

# Tier 2: Document & OCR
echo -e "  -> Starting \033[1;36mTier 2: Document and OCR Worker [document_queue] (concurrency=$CONCURRENCY)\033[0m..."
nohup "$CELERY_BIN" -A tasks.celery_app worker -Q document_queue -c "$CONCURRENCY" -n worker_document@local --loglevel=INFO > "$PROJECT_ROOT/logs/worker_document.log" 2>&1 &
echo $! >> "$PID_FILE"

# Tier 3: ATC & RAG
echo -e "  -> Starting \033[1;35mTier 3: ATC and RAG Worker [atc_rag_queue] (concurrency=$CONCURRENCY)\033[0m..."
nohup "$CELERY_BIN" -A tasks.celery_app worker -Q atc_rag_queue -c "$CONCURRENCY" -n worker_atc@local --loglevel=INFO > "$PROJECT_ROOT/logs/worker_atc.log" 2>&1 &
echo $! >> "$PID_FILE"

# Optional Beat
if [ "$WITH_BEAT" = true ]; then
    echo -e "  -> Starting \033[1;32mCelery Beat Periodic Scheduler\033[0m..."
    nohup "$CELERY_BIN" -A tasks.celery_app beat -s "$PROJECT_ROOT/logs/celerybeat-schedule" --loglevel=INFO > "$PROJECT_ROOT/logs/celery_beat.log" 2>&1 &
    echo $! >> "$PID_FILE"
fi

# Optional Flower
if [ "$WITH_FLOWER" = true ]; then
    echo -e "  -> Starting \033[1;32mFlower Web Dashboard on http://localhost:5555\033[0m..."
    nohup "$CELERY_BIN" -A tasks.celery_app flower --port=5555 > "$PROJECT_ROOT/logs/flower.log" 2>&1 &
    echo $! >> "$PID_FILE"
fi

# Optional Gateway
if [ "$WITH_GATEWAY" = true ]; then
    echo -e "  -> Starting \033[1;36mFastAPI REST Gateway on http://localhost:8000\033[0m..."
    nohup "$UVICORN_BIN" gateway.main:app --host 0.0.0.0 --port 8000 --reload > "$PROJECT_ROOT/logs/gateway.log" 2>&1 &
    echo $! >> "$PID_FILE"
fi

echo -e "\n\033[1;32m[OK] All requested services launched successfully!\033[0m"
echo -e "Logs are writing to: \033[0;33m$PROJECT_ROOT/logs/\033[0m"
echo -e "To tail all worker logs live: \033[0;36mtail -f logs/*.log\033[0m"
echo -e "To stop all workers anytime:  \033[0;33m./start_workers.sh -Stop\033[0m\n"
