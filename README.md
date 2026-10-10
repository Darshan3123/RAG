# 🏛️ GeMBridge

> **Enterprise AI Public Procurement Platform for Government e-Marketplace (GeM)**  
> Comprehensive end-to-end tender discovery, VLM/OCR document extraction, hybrid RAG semantic search, and supplier compliance onboarding.

---

## 📌 Repository Structure

This repository is organized into two primary sub-projects:

1. **[`Scrapper & RAG Pipeline/`](./Scrapper%20&%20RAG%20Pipeline/)** *(Git Branch: `development_v2`)*
   - Playwright stealth scraper for active GeM tenders (`bidplus.gem.gov.in`).
   - PyMuPDF hyperlink extraction & document harvesting (Bid PDF, RA PDF, Corrigenda).
   - Mistral OCR API document conversion into high-fidelity Markdown.
   - Domain-specific regex field extraction (hierarchies, financials, EMD/ePBG, relaxations).
   - SQLite deduplication & catalog storage (`storage/gem_bids.db`, `gem_bids.json`).
   - Hybrid dense (`BAAI/bge-base-en-v1.5`) + sparse (`BM25Okapi`) + cross-encoder reranker vector store (ChromaDB).
   - Buyer-Added ATC clause analysis engine (`ATC EXTRACTOR/`) supporting Gemini (Flash / Flash Lite) and OpenAI (GPT-4o / GPT-4o-mini).

2. **[`Web App/`](./Web%20App/)**
   - **`backend/`**: Django 5.1.4 REST Framework API with JWT authentication (`apps/auth`), Tender Catalog (`apps/bids`), and progressive 8-step vendor registration (`apps/onboarding`).
   - **`frontend/`**: Next.js 16 (React 19, Tailwind v4, Framer Motion) vendor portal featuring an 8-step onboarding wizard, readiness scoring, responsive dual-view bid exploration (cards/tables), and sector-wise tender browsing.

---

## 📖 Complete Master Documentation

For an exhaustive, line-by-line architectural breakdown of every module, database model, API endpoint, and pipeline stage, please refer to:

👉 **[`GEMBRIDGE_MASTER_WORKFLOW.md`](./GEMBRIDGE_MASTER_WORKFLOW.md)**

---

## 🚀 Quick Start

### Scraper & RAG Pipeline
```powershell
cd "Scrapper & RAG Pipeline"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
python main.py --once
```

### Web App Backend
```powershell
cd "Web App\backend"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8000
```

### Web App Frontend
```powershell
cd "Web App\frontend"
npm install
npm run dev
# Open http://localhost:3000
```
