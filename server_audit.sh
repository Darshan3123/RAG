#!/usr/bin/env bash
# ==============================================================================
# server_audit.sh — Linux & Ubuntu Server Workload & Worker Capacity Inspector
# Specifically tuned for Hostinger KVM 4 (4 vCPU / 16 GB RAM) and Ubuntu Nodes
# ==============================================================================

# Exit on unexpected pipe failures
set -o pipefail

# ANSI Color Codes
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
MAGENTA="\033[0;35m"
DIM="\033[2m"
NC="\033[0m" # No Color

clear 2>/dev/null || true

echo -e "${CYAN}${BOLD}"
echo "=========================================================================="
echo "    🏛️  GeMBridge — Ubuntu Server Audit & Worker Capacity Profiler       "
echo "        Target: Hostinger KVM 4 & Multi-Ubuntu Deployment Systems         "
echo "=========================================================================="
echo -e "${NC}"

# ------------------------------------------------------------------------------
# 1. HARDWARE & OPERATING SYSTEM SPECS
# ------------------------------------------------------------------------------
echo -e "${BOLD}${MAGENTA}▶ 1. SYSTEM HARDWARE & OS PROFILE${NC}"

# OS Name
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME="$PRETTY_NAME"
else
    OS_NAME="$(uname -s) $(uname -r)"
fi

# CPU Specs
CPU_MODEL=$(grep -m1 "model name" /proc/cpuinfo | cut -d: -f2 | sed 's/^[ \t]*//' || echo "Unknown CPU")
CPU_CORES=$(nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo)
LOAD_1M=$(awk '{print $1}' /proc/loadavg)
LOAD_5M=$(awk '{print $2}' /proc/loadavg)
LOAD_15M=$(awk '{print $3}' /proc/loadavg)

# RAM Specs (in MB)
MEM_TOTAL_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
MEM_AVAIL_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
MEM_FREE_KB=$(grep MemFree /proc/meminfo | awk '{print $2}')
SWAP_TOTAL_KB=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
SWAP_FREE_KB=$(grep SwapFree /proc/meminfo | awk '{print $2}')

MEM_TOTAL_MB=$((MEM_TOTAL_KB / 1024))
MEM_AVAIL_MB=$((MEM_AVAIL_KB / 1024))
MEM_USED_MB=$((MEM_TOTAL_MB - MEM_AVAIL_MB))
MEM_USED_PCT=$(( (MEM_USED_MB * 100) / MEM_TOTAL_MB ))

SWAP_TOTAL_MB=$((SWAP_TOTAL_KB / 1024))
SWAP_FREE_MB=$((SWAP_FREE_KB / 1024))
SWAP_USED_MB=$((SWAP_TOTAL_MB - SWAP_FREE_MB))

# Disk Usage
DISK_TOTAL=$(df -h / | awk 'NR==2 {print $2}')
DISK_USED=$(df -h / | awk 'NR==2 {print $3}')
DISK_AVAIL=$(df -h / | awk 'NR==2 {print $4}')
DISK_USED_PCT=$(df -h / | awk 'NR==2 {print $5}')

printf "  %-22s: %s\n" "Operating System" "$OS_NAME ($(uname -m))"
printf "  %-22s: %s\n" "CPU Architecture" "$CPU_MODEL"
printf "  %-22s: %s Cores | Load: %s (1m), %s (5m), %s (15m)\n" "vCPU Count & Load" "$CPU_CORES" "$LOAD_1M" "$LOAD_5M" "$LOAD_15M"
printf "  %-22s: %d MB Total | %s%d MB Used (%d%%)%s | %s%d MB Available%s\n" \
    "Physical RAM" "$MEM_TOTAL_MB" \
    "${YELLOW}" "$MEM_USED_MB" "$MEM_USED_PCT" "${NC}" \
    "${GREEN}" "$MEM_AVAIL_MB" "${NC}"

if [ "$SWAP_TOTAL_MB" -eq 0 ]; then
    printf "  %-22s: %s0 MB (NO SWAP CONFIGURED! Risk of OOM Crashes)%s\n" "Swap Memory" "${RED}${BOLD}" "${NC}"
else
    printf "  %-22s: %d MB Total | %d MB Used | %d MB Free\n" "Swap Memory" "$SWAP_TOTAL_MB" "$SWAP_USED_MB" "$SWAP_FREE_MB"
fi
printf "  %-22s: %s Total | %s Used (%s) | %s Free\n" "Root Disk (/)" "$DISK_TOTAL" "$DISK_USED" "$DISK_USED_PCT" "$DISK_AVAIL"

echo ""

# ------------------------------------------------------------------------------
# 2. RUNNING PROJECTS & ACTIVE WORKLOADS INSPECTION
# ------------------------------------------------------------------------------
echo -e "${BOLD}${MAGENTA}▶ 2. CURRENT RUNNING PROJECTS & BACKGROUND SERVICES${NC}"

# A. Docker Containers Check
echo -e "  ${CYAN}[A] Docker Containers & Stacks:${NC}"
if command -v docker &>/dev/null && docker ps &>/dev/null; then
    RUNNING_CONTAINERS=$(docker ps -q | wc -l)
    if [ "$RUNNING_CONTAINERS" -gt 0 ]; then
        echo -e "      Found ${GREEN}$RUNNING_CONTAINERS${NC} active Docker container(s):"
        docker ps --format "table   • {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" | sed '2,$s/^/    /'
        echo ""
        echo -e "      ${DIM}Container Memory & CPU Consumption:${NC}"
        docker stats --no-stream --format "        {{.Name}}: Mem: {{.MemUsage}} ({{.MemPerc}}) | CPU: {{.CPUPerc}}"
    else
        echo -e "      ${DIM}Docker is installed, but 0 containers are currently running.${NC}"
    fi
else
    echo -e "      ${DIM}Docker daemon is not running or not installed.${NC}"
fi

echo ""

# B. PM2 / Node.js Apps Check
echo -e "  ${CYAN}[B] PM2 & Node.js Applications:${NC}"
if command -v pm2 &>/dev/null; then
    PM2_COUNT=$(pm2 jlist 2>/dev/null | grep -o '"name":' | wc -l || echo 0)
    if [ "$PM2_COUNT" -gt 0 ]; then
        echo -e "      Found ${GREEN}$PM2_COUNT${NC} PM2 managed process(es):"
        pm2 list | grep -E "│ [0-9]" | awk -F'│' '{printf "        • %-20s Status: %-10s Mem: %-8s CPU: %s\n", $3, $10, $12, $11}'
    else
        echo -e "      ${DIM}PM2 installed, but 0 processes registered.${NC}"
    fi
else
    NODE_COUNT=$(pgrep -f "node" | wc -l || echo 0)
    if [ "$NODE_COUNT" -gt 0 ]; then
        echo -e "      Found ${GREEN}$NODE_COUNT${NC} standalone Node.js process(es) running."
    else
        echo -e "      ${DIM}No active Node.js / PM2 apps found.${NC}"
    fi
fi

echo ""

# C. Web Servers, Proxies, and Databases
echo -e "  ${CYAN}[C] Common Web Servers, Proxies & Databases:${NC}"
SERVICES=("nginx" "apache2" "caddy" "postgresql" "mysql" "mariadb" "redis-server" "redis" "mongod" "celery" "gunicorn" "uvicorn")
FOUND_SERVICES=0
for s in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$s" 2>/dev/null || pgrep -f "$s" &>/dev/null; then
        MEM_KB=$(ps -C "$s" -o rss= 2>/dev/null | awk '{s+=$1} END {print s+0}')
        MEM_MB=$((MEM_KB / 1024))
        printf "      • %-16s : ${GREEN}ACTIVE${NC} (Consuming ~%d MB RAM)\n" "$s" "$MEM_MB"
        FOUND_SERVICES=$((FOUND_SERVICES + 1))
    fi
done
if [ "$FOUND_SERVICES" -eq 0 ]; then
    echo -e "      ${DIM}None of the standard standalone database/proxy services detected as active services.${NC}"
fi

echo ""

# D. Existing Python Processes Check
echo -e "  ${CYAN}[D] Active Python Applications & Workers:${NC}"
PYTHON_PROCS=$(pgrep -a -f python | grep -v "server_audit.sh" || true)
if [ -n "$PYTHON_PROCS" ]; then
    echo -e "      Found the following Python processes currently running:"
    ps -eo pid,user,%cpu,%mem,rss,args --sort=-%mem | grep -i "[p]ython" | head -n 8 | while read -r pid user cpu mem rss args; do
        RSS_MB=$((rss / 1024))
        TRUNC_CMD=$(echo "$args" | cut -c1-65)
        printf "        PID %-6s | %-8s | CPU: %-4s%% | RAM: %4d MB (%s%%) | %s\n" "$pid" "$user" "$cpu" "$RSS_MB" "$mem" "$TRUNC_CMD"
    done
else
    echo -e "      ${DIM}No existing Python workloads running.${NC}"
fi

echo ""

# E. Top 8 Overall Memory-Consuming Processes
echo -e "  ${CYAN}[E] Top 8 Memory-Consuming Processes on the System:${NC}"
printf "      %-7s %-10s %-8s %-8s %s\n" "PID" "USER" "RAM(MB)" "%MEM" "COMMAND"
ps -eo pid,user,rss,%mem,comm --sort=-rss | head -n 9 | tail -n 8 | while read -r pid user rss mem comm; do
    RSS_MB=$((rss / 1024))
    printf "      %-7s %-10s %-8d %-8s %s\n" "$pid" "$user" "$RSS_MB" "$mem" "$comm"
done

echo ""

# ------------------------------------------------------------------------------
# 3. WORKER CAPACITY CALCULATION FOR GeM SCRAPER & RAG
# ------------------------------------------------------------------------------
echo -e "${BOLD}${MAGENTA}▶ 3. GeM SCRAPER & RAG WORKER CAPACITY SIZING${NC}"

# Worker Memory Profiling Constants
PLAYWRIGHT_BASE_MB=320   # Single Chromium headless browser tab loading GeM Angular DOM
PYTHON_PROCESS_MB=120    # Parser, BeautifulSoup, requests, SQLite worker thread
RAG_EMBEDDING_MB=550     # BAAI/bge-base-en-v1.5 + BGE Reranker (loaded once in memory)
SYSTEM_SAFETY_BUFFER=1500 # 1.5 GB OS, SSH, Disk cache buffer

ESTIMATED_PER_WORKER_MB=$((PLAYWRIGHT_BASE_MB + PYTHON_PROCESS_MB)) # ~440 MB per concurrent worker

# Usable RAM for new workers
USABLE_RAM_MB=$((MEM_AVAIL_MB - SYSTEM_SAFETY_BUFFER))
if [ "$USABLE_RAM_MB" -lt 0 ]; then
    USABLE_RAM_MB=0
fi

# Calculate Max Workers based on RAM
CALC_WORKERS_RAM=$((USABLE_RAM_MB / ESTIMATED_PER_WORKER_MB))

# Calculate Max Workers based on CPU (1 to 2 workers per vCPU core)
CALC_WORKERS_CPU=$((CPU_CORES * 2))

# Optimal Worker Sizing
RECOMMENDED_WORKERS=$CALC_WORKERS_RAM
if [ "$RECOMMENDED_WORKERS" -gt "$CALC_WORKERS_CPU" ]; then
    RECOMMENDED_WORKERS=$CALC_WORKERS_CPU
fi

# Floor at 1 if some RAM is available, or 0 if completely constrained
if [ "$RECOMMENDED_WORKERS" -lt 1 ] && [ "$MEM_AVAIL_MB" -gt 800 ]; then
    RECOMMENDED_WORKERS=1
fi

echo -e "  ${BOLD}Resource Budgeting Analysis:${NC}"
printf "  • Current Available RAM              : %d MB (~%.2f GB)\n" "$MEM_AVAIL_MB" "$(awk "BEGIN {print $MEM_AVAIL_MB/1024}")"
printf "  • OS & Kernel Safety Buffer Reserved : %d MB\n" "$SYSTEM_SAFETY_BUFFER"
printf "  • Usable RAM Headroom for Workers    : %d MB\n" "$USABLE_RAM_MB"
printf "  • Estimated RAM per Playwright Worker: ~%d MB (Chromium headless + parser)\n" "$ESTIMATED_PER_WORKER_MB"
printf "  • One-Time RAG Model Overhead (if on): ~%d MB (BGE embeddings + reranker)\n" "$RAG_EMBEDDING_MB"

echo ""
echo -e "  ${BOLD}${GREEN}Recommended Worker Concurrency on this Host:${NC}"
echo -e "  ┌────────────────────────────────────────────────────────┐"
printf "  │  ${BOLD}%-32s : ${YELLOW}%d Worker(s)${NC}       │\n" "Safe Scraping Concurrency" "$RECOMMENDED_WORKERS"
printf "  │  %-32s : %d vCPUs           │\n" "Available CPU Cores" "$CPU_CORES"
printf "  │  %-32s : ~%d MB            │\n" "Projected Worker RAM Footprint" "$((RECOMMENDED_WORKERS * ESTIMATED_PER_WORKER_MB))"
printf "  │  %-32s : ~%d MB            │\n" "Remaining Free RAM Headroom" "$((MEM_AVAIL_MB - (RECOMMENDED_WORKERS * ESTIMATED_PER_WORKER_MB)))"
echo -e "  └────────────────────────────────────────────────────────┘"

echo ""

# ------------------------------------------------------------------------------
# 4. ACTIONABLE ADVICE & SERVER HARDENING FOR HOSTINGER KVM 4
# ------------------------------------------------------------------------------
echo -e "${BOLD}${MAGENTA}▶ 4. DEPLOYMENT RECOMMENDATIONS & SYSTEM CHECKS${NC}"

# Check 1: SWAP Check
if [ "$SWAP_TOTAL_MB" -eq 0 ]; then
    echo -e "  ${RED}${BOLD}⚠️  CRITICAL: NO SWAP MEMORY DETECTED!${NC}"
    echo -e "     Hostinger KVM VPS instances often default to 0 swap."
    echo -e "     If Chromium experiences a brief memory spike, the Linux OOM-killer"
    echo -e "     will terminate your scraper without any error message."
    echo -e "     ${YELLOW}To fix this, create a 4GB Swapfile immediately:${NC}"
    echo -e "     ${CYAN}sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile${NC}"
    echo -e "     ${CYAN}echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab${NC}"
    echo ""
else
    echo -e "  ${GREEN}✓ Swap memory is enabled (${SWAP_TOTAL_MB} MB). Helps cushion memory spikes.${NC}"
fi

# Check 2: Playwright Chromium System Dependencies
if command -v python3 &>/dev/null; then
    MISSING_LIBS=0
    for lib in "libnss3.so" "libatk-1.0.so.0" "libasound.so.2" "libgbm.so.1"; do
        if ! ldconfig -p 2>/dev/null | grep -q "$lib"; then
            MISSING_LIBS=$((MISSING_LIBS + 1))
        fi
    done
    if [ "$MISSING_LIBS" -gt 0 ]; then
        echo -e "  ${YELLOW}⚠️  Playwright System Dependencies Check:${NC}"
        echo -e "     Some system shared libraries required by headless Chromium might be missing."
        echo -e "     Run this command inside your project venv:"
        echo -e "     ${CYAN}playwright install --with-deps chromium${NC}"
    else
        echo -e "  ${GREEN}✓ Essential headless browser libraries detected.${NC}"
    fi
fi

# Check 3: Optimal .env Configuration
echo ""
echo -e "  ${BOLD}Recommended Configuration for .env on this server:${NC}"
echo -e "${CYAN}------------------------------------------------------------"
echo "TARGET_PER_TYPE=10"
echo "MAX_CONCURRENT_WORKERS=$RECOMMENDED_WORKERS"
echo "OCR_PROVIDER=mistral  # Use Cloud API (Mistral/Gemini) to save server RAM"
echo "ENABLE_PDF_ATC_SPLIT=true # Saves 30%-50% API calls and cuts parse time"
echo -e "------------------------------------------------------------${NC}"

echo -e "\n${BOLD}${GREEN}Audit complete! Run 'python benchmark_workers.py' to execute live concurrency stress tests.${NC}\n"
