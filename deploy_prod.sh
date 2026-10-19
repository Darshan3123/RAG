#!/usr/bin/env bash
# ==============================================================================
# deploy_prod.sh — Production Deployment Script for GeMBridge Engine
# Optimized for Dokploy, Traefik & Hostinger KVM 4 VPS (srv1701681)
# ==============================================================================

set -eo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
NC="\033[0m"

echo -e "${CYAN}${BOLD}"
echo "=========================================================================="
echo "    🚀  GeMBridge — Production Dokploy & Docker Compose Deployment        "
echo "        Target: Hostinger KVM 4 VPS (srv1701681)                          "
echo "=========================================================================="
echo -e "${NC}"

# 1. Verify Docker and Docker Compose
echo -e "${BOLD}${YELLOW}▶ Step 1: Checking Docker Environment...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed or not in PATH.${NC}"
    exit 1
fi

COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}❌ Docker Compose plugin is not installed.${NC}"
    exit 1
fi
echo -e "   ${GREEN}✓ Docker Engine & Compose verified (${COMPOSE_CMD})${NC}"

# 2. Check for .env file
echo -e "\n${BOLD}${YELLOW}▶ Step 2: Verifying Environment Configuration (.env)...${NC}"
if [ ! -f .env ]; then
    if [ -f .env.production.example ]; then
        echo -e "${YELLOW}   ⚠️ .env not found. Copying .env.production.example -> .env${NC}"
        cp .env.production.example .env
        echo -e "${RED}   ❗ Please edit .env with your real PostgreSQL, MinIO, and API secrets!${NC}"
    else
        echo -e "${RED}❌ Missing .env file. Please create .env before deploying.${NC}"
        exit 1
    fi
else
    echo -e "   ${GREEN}✓ Production .env configuration found.${NC}"
fi

# 3. Pull latest Git changes if in a repository
if [ -d .git ]; then
    echo -e "\n${BOLD}${YELLOW}▶ Step 3: Checking for Git Updates...${NC}"
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    echo -e "   Current branch: ${CYAN}${CURRENT_BRANCH}${NC}"
    read -p "   Pull latest commits from origin/${CURRENT_BRANCH}? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git pull origin "$CURRENT_BRANCH"
        echo -e "   ${GREEN}✓ Codebase up to date.${NC}"
    fi
fi

# 4. Build and Launch Production Stack
echo -e "\n${BOLD}${YELLOW}▶ Step 4: Building & Starting Containers with Strict Ceilings...${NC}"
echo -e "   Stack: ${CYAN}docker-compose.prod.yml${NC}"
$COMPOSE_CMD -f docker-compose.prod.yml up -d --build --remove-orphans

# 5. Wait and Verify Health
echo -e "\n${BOLD}${YELLOW}▶ Step 5: Awaiting Service Initialization (15s)...${NC}"
sleep 15

echo -e "\n${BOLD}${GREEN}==========================================================================${NC}"
echo -e "${BOLD}${GREEN}    🎉  GeMBridge Production Stack Successfully Deployed!               ${NC}"
echo -e "${BOLD}${GREEN}==========================================================================${NC}"

echo -e "\n${BOLD}📊 Container Status:${NC}"
$COMPOSE_CMD -f docker-compose.prod.yml ps

echo -e "\n${BOLD}🌐 Exposed Production Endpoints:${NC}"
echo -e "   • FastAPI Gateway   : ${CYAN}http://localhost:8000${NC} (Docs: ${CYAN}http://localhost:8000/docs${NC})"
echo -e "   • Flower Dashboard  : ${CYAN}http://localhost:5555${NC}"
echo -e "   • Health Endpoint   : ${CYAN}http://localhost:8000/health${NC}"

echo -e "\n${BOLD}📜 Quick Operational Commands:${NC}"
echo -e "   • View Live Scraper Logs : ${CYAN}$COMPOSE_CMD -f docker-compose.prod.yml logs -f worker-scraper${NC}"
echo -e "   • View API Gateway Logs  : ${CYAN}$COMPOSE_CMD -f docker-compose.prod.yml logs -f fastapi-gateway${NC}"
echo -e "   • Real-Time Resource Use : ${CYAN}docker stats gem-worker-scraper gem-worker-document gem-worker-atc gem-fastapi-gateway${NC}"
echo -e "   • Stop Production Stack  : ${CYAN}$COMPOSE_CMD -f docker-compose.prod.yml down${NC}"
echo ""
