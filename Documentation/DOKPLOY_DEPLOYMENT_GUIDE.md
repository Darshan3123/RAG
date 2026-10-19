# 🚀 GeMBridge: Production Dokploy & Hostinger KVM 4 VPS Deployment Guide

> **Target Server:** Hostinger KVM 4 VPS (`srv1701681`)  
> **OS:** Ubuntu 24.04 LTS (AMD EPYC 9355P, 4 vCPUs, 16 GB RAM, 200 GB NVMe)  
> **Control Panel:** Dokploy & Traefik Reverse Proxy (46 Co-Existing Containers)  
> **Pipeline Architecture:** Celery 3-Tier Distributed Queue + Shared PostgreSQL 16+ (pgvector) + Shared MinIO S3  
> **Document Reference:** `Documentation/DOKPLOY_DEPLOYMENT_GUIDE.md`  

---

## 📑 1. Architectural Blueprint

The production stack uses [`docker-compose.prod.yml`](file:///F:/Projects/gem_scraper/docker-compose.prod.yml) to deploy the distributed worker tiers and REST API with strict resource limits. It connects directly to your **existing, shared PostgreSQL** and **MinIO S3** instances without duplicating databases or storage containers.

```mermaid
flowchart TD
    User["🌐 External Clients & Web Dashboard"] -->|HTTPS / Port 443| Traefik["Dokploy / Traefik Reverse Proxy"]
    
    subgraph Routing ["Traefik SSL Routing"]
        Traefik -->|api.yourdomain.com| Gateway["fastapi-gateway\n(Port 8000)\n0.4 CPU | 350 MB"]
        Traefik -->|flower.yourdomain.com| Flower["flower-telemetry\n(Port 5555)\n0.1 CPU | 150 MB"]
    end

    subgraph InternalStack ["Production Docker Stack (docker-compose.prod.yml)"]
        Redis[("gem-engine-redis\n(Redis 7 Alpine - AOF)\n0.3 CPU | 512 MB")]
        
        Gateway -->|Dispatch On-Demand| Redis
        Beat["gem-celery-beat\n(30-Min Schedule)\n0.1 CPU | 150 MB"] -->|Enqueue Crawl| Redis
        
        Redis -->|scraping_queue| W1["gem-worker-scraper\n(Playwright Chromium)\n1.0 CPU | 1200 MB\nshm_size: 2gb, init: true"]
        Redis -->|document_queue| W2["gem-worker-document\n(PyMuPDF + Mistral OCR)\n0.5 CPU | 600 MB"]
        Redis -->|atc_rag_queue| W3["gem-worker-atc\n(Gemini 2.5 + BGE Embed)\n0.5 CPU | 1200 MB\nVolume: gem_hf_cache"]
    end

    subgraph SharedInfrastructure ["Existing Shared Infrastructure on VPS"]
        SharedPG[("🐘 Shared PostgreSQL 16+\n• Database: gem-bridge\n• pgvector 768-dim HNSW\n• 10 Normalized Tables")]
        SharedMinIO[("🪣 Shared MinIO S3\n• Bucket: gem-tenders\n• Presigned 24h Streaming")]
    end

    W1 -->|Stream In-Memory PDF| SharedMinIO
    W2 -->|Fetch PDF & Upsert Master| SharedMinIO
    W2 -->|Atomic Upsert (10 Tables)| SharedPG
    W3 -->|Insert Checklist & pgvector| SharedPG
    W3 -->|Stream Compliance JSON| SharedMinIO
    Gateway -->|Sub-5ms Query| SharedPG
    Gateway -->|307 Presigned Redirect| SharedMinIO
```

---

## 🔒 2. Hardware Resource Ceilings & Safety Guarantees

Hostinger VPS `srv1701681` already runs 46 containers consuming ~8.5 GB RAM. To protect the host Linux kernel from invoking the OOM Killer (`exit code 137`), the pipeline enforces strict ceilings in [`docker-compose.prod.yml`](file:///F:/Projects/gem_scraper/docker-compose.prod.yml):

| Service | Container Name | CPU Limit | RAM Limit | RAM Reservation | Key Hardening Configuration |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Redis Broker** | `gem-engine-redis` | `0.30` | `512 MB` | — | AOF persistence, `--maxmemory 512mb` |
| **Tier 1 Scraper** | `gem-worker-scraper` | `1.00` | `1200 MB` | `400 MB` | `shm_size: 2gb`, `init: true` (reap zombie Chromium) |
| **Tier 2 Document** | `gem-worker-document` | `0.50` | `600 MB` | `200 MB` | PyMuPDF memory slicing + streaming buffers |
| **Tier 3 ATC / Vector** | `gem-worker-atc` | `0.50` | `1200 MB` | `400 MB` | Persistent HuggingFace model cache volume (`gem_hf_cache`) |
| **Celery Beat** | `gem-celery-beat` | `0.10` | `150 MB` | — | Lightweight periodic scheduler |
| **FastAPI Gateway** | `gem-fastapi-gateway` | `0.40` | `350 MB` | — | 2 Uvicorn workers, Sub-5ms queries |
| **Flower Telemetry** | `gem-flower-telemetry` | `0.10` | `150 MB` | — | Password protected (`admin:password`) |
| **COMBINED MAXIMUM** | — | **≤ 2.9 vCPU** | **≤ 4.16 GB** | **~1.0 GB** | **Guarantees >4 GB RAM & 1.5 vCPU free on VPS** |

### Additional Operational Guarantees:
1. **Log Rotation (`json-file`):** Every container is capped with `max-size: 10m` and `max-file: 3` (maximum 30 MB per container) to prevent root disk exhaustion.
2. **Persistent Vector Model:** The `BAAI/bge-base-en-v1.5` model weights (~440 MB) are persisted in the named volume `gem_hf_cache`. Containers reboot instantly without downloading model weights from HuggingFace.

---

## 🚀 3. Deployment Instructions

### Method A: Deploy via Dokploy Dashboard UI (Recommended)

1. **Log in to Dokploy:**
   - Navigate to `https://your-dokploy-domain:3000`.
2. **Create a New Project / Compose Application:**
   - Click **Projects** -> Select your Project (or create `GeMBridge`).
   - Click **Create Service** -> Select **Compose**.
   - Set Name: `gembridge-pipeline`.
3. **Configure Source Repository:**
   - Select **Git Provider** (GitHub / GitLab).
   - Repository: `your-username/gem_scraper`.
   - Branch: `development_v3` (or `main`).
   - Compose Path: `docker-compose.prod.yml`.
4. **Configure Environment Variables in Dokploy UI:**
   - Click on the **Environment** tab.
   - Copy the contents of [`.env.production.example`](file:///F:/Projects/gem_scraper/.env.production.example) into the text box.
   - Enter your actual production database password, MinIO credentials, and API keys:
     ```ini
     ENABLE_TRAEFIK=true
     TRAEFIK_CERT_RESOLVER=letsencrypt
     GATEWAY_DOMAIN=api.yourgembridge.com
     FLOWER_DOMAIN=flower.yourgembridge.com
     FLOWER_BASIC_AUTH=admin:YourSecurePassword2026!

     # Shared PostgreSQL on VPS:
     POSTGRES_HOST=host.docker.internal
     POSTGRES_PORT=5432
     POSTGRES_DB=gem-bridge
     POSTGRES_USER=postgres
     POSTGRES_PASSWORD=your_actual_db_password
     DATABASE_URL=postgresql://postgres:your_actual_db_password@host.docker.internal:5432/gem-bridge

     # Shared MinIO on VPS:
     MINIO_ENDPOINT=host.docker.internal:9000
     MINIO_ACCESS_KEY=your_minio_access_key
     MINIO_SECRET_KEY=your_minio_secret_key
     MINIO_BUCKET=gem-tenders
     MINIO_SECURE=false

     # Cloud APIs:
     MISTRAL_API_KEY=your_mistral_api_key
     GEMINI_API_KEY=your_gemini_api_key
     ```
5. **Click "Deploy":**
   - Dokploy builds the Dockerfile image, launches the 7 services, configures Traefik SSL certificates, and begins streaming live logs.

---

### Method B: Deploy via VPS SSH Terminal (Fast Shell Script)

If you prefer terminal deployment via SSH:

```bash
# 1. SSH into the Hostinger VPS
ssh root@srv1701681

# 2. Clone or navigate to the repository directory
cd /opt/gem_scraper # or your deployment folder

# 3. Create .env from template
cp .env.production.example .env
nano .env  # Enter your real production credentials

# 4. Make deploy script executable and run
chmod +x deploy_prod.sh
./deploy_prod.sh
```

---

## 🐘 4. Shared PostgreSQL & MinIO One-Time Setup

Before the first crawl runs, verify that the shared PostgreSQL database has the v3.0 schema and extensions installed:

```bash
# 1. Connect to your shared PostgreSQL database
psql -U postgres -d gem-bridge

# 2. Apply the idempotent v3 schema (tables, GIN indexes, pgvector HNSW)
\i storage/init_v3_schema.sql

# 3. Verify that all 10 tables and vector extension exist
\dt
\dx vector
\q
```

---

## 🌐 5. Domain & Traefik Routing Configuration

To route web traffic via Dokploy's Traefik reverse proxy:

1. **Configure DNS Records:**
   - In Cloudflare / your DNS provider, create two `A` records pointing to your Hostinger VPS IP:
     - `api.yourgembridge.com` -> `VPS_IP`
     - `flower.yourgembridge.com` -> `VPS_IP`
2. **Automatic SSL Certificates:**
   - `docker-compose.prod.yml` includes standard Traefik labels that instruct Dokploy's Traefik to request and renew Let's Encrypt certificates automatically over HTTPS (Port 443).

---

## 📊 6. Production Monitoring & Operational Runbook

### Inspect Running Containers
```bash
docker compose -f docker-compose.prod.yml ps
```

### Real-Time CPU & RAM Consumption Telemetry
```bash
docker stats gem-worker-scraper gem-worker-document gem-worker-atc gem-fastapi-gateway gem-engine-redis
```

### Inspect Live Worker Logs
```bash
# View scraper crawler logs
docker logs -f gem-worker-scraper

# View document OCR & database ingestion logs
docker logs -f gem-worker-document

# View AI compliance & vector embedding logs
docker logs -f gem-worker-atc

# View REST API access logs
docker logs -f gem-fastapi-gateway
```

### Web Monitoring Interfaces
- **FastAPI OpenAPI Interactive Docs:** `https://api.yourgembridge.com/docs`
- **FastAPI Health Diagnostic:** `https://api.yourgembridge.com/health`
- **Flower Worker Queue Telemetry:** `https://flower.yourgembridge.com` *(Login: admin / configured password)*

---

## 🔄 7. Updates & Zero-Downtime Reloads

When pulling new code or configuration updates:

```bash
git pull origin development_v3
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
```

Dokploy and Docker Compose perform a rolling rebuild, keeping Redis and active Celery tasks intact.
