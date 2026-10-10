# 🧠 brain.md — GeMBridge Master System Blueprint & Architecture

> **Last Updated:** September 2026  
> **Originating Specification:** [`C:\Users\Darshan\Downloads\GeM.md`](file:///C:/Users/Darshan/Downloads/GeM.md)  
> **Dual-Repository Sync (Keep Synchronized):**  
> - Parent Platform (Django + Next.js): [`F:\Projects\GEM\GEM\brain.md`](file:///F:/Projects/GEM/GEM/brain.md)  
> - Scraper & AI/RAG Engine (Playwright + Mineru/Mistral + Qwen3): [`F:\Projects\gem_scraper\brain.md`](file:///F:/Projects/gem_scraper/brain.md)  

---

## 🧭 1. Executive Summary & Platform Purpose

**GeMBridge** is an enterprise AI procurement platform built to help Indian manufacturers, vendors, and service contractors discover, analyze, qualify for, and win public procurement bids on the **Government e-Marketplace (GeM)** (`bidplus.gem.gov.in`).

The platform bridges the gap between raw, complex government tender documents and vendor decision-making through two tightly connected codebases:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              GeMBridge System Architecture                             │
│                                                                                        │
│  ┌───────────────────────────────────────────┐      JSON /      ┌────────────────────┐ │
│  │      gem_scraper (AI & Data Layer)        │      SQLite      │ GEM App (Platform) │ │
│  │      F:\Projects\gem_scraper\             │      Import      │ F:\Projects\GEM\GEM│ │
│  │                                           │  ──────────────► │                    │ │
│  │  • Playwright Stealth Portal Scraper      │                  │ • Django REST API  │ │
│  │  • Mineru VLM / Mistral OCR (v2 branch)   │                  │ • Next.js 16 UI    │ │
│  │  • Regex Domain Parser (core/parser.py)   │                  │ • 9-Step Onboarding│ │
│  │  • PyMuPDF Hyperlink & Document Harvester │  ◄─────────────  │ • Vendor Profiles  │ │
│  │  • BGE Dense + BM25 + Cross-Encoder RAG   │     RAG Proxy    │ • Eligibility Match│ │
│  │  • Qwen3-4B ATC Extractor (llama-server)  │     /api/bids/   │ • Bid Marketplace  │ │
│  └───────────────────────────────────────────┘       ask/       └────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

The system's business logic, parsing engines, database models, and UI types are built upon the foundational master specification documented in [`GeM.md`](file:///C:/Users/Darshan/Downloads/GeM.md).

---

## 🏛️ 2. GeM Domain Knowledge Base & Taxonomy (from `GeM.md`)

[`GeM.md`](file:///C:/Users/Darshan/Downloads/GeM.md) provides the complete domain taxonomy of Indian Government procurement rules under GFR (General Financial Rules) and GeM Guidelines:

### A. The 10 Types of GeM Bids
1. **All Bid/RAs:** Global unfiltered listing of all live portal bids.
2. **Product Bid/RAs:** Standard procurement for physical goods available in the GeM catalogue.
3. **Service Bid/RAs:** Services such as Manpower, Security, Facility Management, IT Support, Consulting.
4. **Bid to RA:** Two-stage procurement:
   - *Stage 1:* Technical evaluation and qualification.
   - *Stage 2:* Automated Reverse Auction (RA) conducted among qualified bidders.
5. **Product Custom Bid/RAs:** Procurement for items missing from the standard GeM catalogue; requires generation of a **GeMARPTS** (GeM Availability Report & Past Transaction Summary).
6. **BOQ Bids (Bill of Quantities):** Configured when bids have $>5$ line items (consumables/spare parts) valued $> ₹5$ Lakhs. Evaluation can be Total-value-wise, Item-wise, or Group-wise.
7. **Rate Contract Bids (RC):** Standing framework agreements fixing rates and terms once; multiple purchase orders placed repeatedly during the contract tenure without fresh tenders.
8. **Global Tender (GTE):** High-value or technology-intensive procurement open to international suppliers.
9. **Limited Tender Enquiry (Rule 162 GFR):** Restricted competition directly inviting $\ge 3$ pre-approved suppliers.
10. **Single Tender Enquiry (Rule 166 GFR):** Proprietary or emergency procurement from a sole source.

### B. The 3 Primary Bidding Processes
- **Catalogue Bidding:** Catalogue items configured using GeM "Golden Parameters" and bunch bidding options.
- **BoQ Bidding:** Spare parts/consumables with detailed BoQ specification sheets; prohibited for bids below ₹5 Lakhs.
- **Custom Bidding:** Custom specifications uploaded after preparing a custom catalogue (selecting up to 3 similar categories).

### C. The 8-Pillar General Questionnaire
Every tender parsed by GeMBridge must extract and answer:
1. **Identity & Classification:** Bid Number, RA Number, Product vs Service, Process Kind (Catalogue/BoQ/Custom), Tender Mode.
2. **Scope of Procurement:** Item category/subcategories, single vs bunch/multi-item BoQ.
3. **Competition Structure:** Single-Packet vs Two-Packet bid, Evaluation method (Total/Item/Group), Bid splitting rules, Auto-extension rules.
4. **Eligibility & Qualifications:** Past experience years, Minimum average annual turnover, MSE / Startup relaxations, required seller documents.
5. **Financial Terms & Instruments:** EMD requirement/amount/bank, ePBG percentage/duration/bank, estimated bid value.
6. **Timelines & Milestones:** Start datetime, End datetime, Opening datetime, Bid validity days, Technical clarification window.
7. **Consignees & Delivery:** Locations, pincodes, quantities, and delivery schedule days.
8. **Policy / Preference / Compliance:** Make in India (MII) price band (L1+X%) and quantity %, MSE preference band and quantity %, Land Border sharing restrictions (GTC Clause 26), and Buyer Added ATC clauses.

### D. The 7 Core Analytical Questions & Decision Rules
1. **Is it Product or Service?** Checked from HTML card attribute `Product/Service` and PDF header.
2. **Is it Catalogue, BoQ, or Custom?** Inferred from GeMARPTS section, BoQ attachments, or Custom Bid text.
3. **Single Packet or Two Packet?** Single packet opens price directly; Two-packet requires technical evaluation before financial opening.
4. **Is Bid Splitting applied?** Inferred from bid splitting clause defining L1, L2, L3 allocation ratios.
5. **Is there Bid to RA and what is the qualification rule?** Extracted from RA section (e.g. H1 elimination rule).
6. **What are the Auto-Extension rules?** Extracted minimum bids to disable extension, auto-extend days, and max extension count.
7. **What are MII & ATC details?** Make in India margin over L1; Buyer Added ATC mandatory requirements and checklists.

---

## 📋 3. Comprehensive Field $\rightarrow$ Source Mapping (HTML Card vs. PDF)

Based on the 17-section mapping in [`GeM.md`](file:///C:/Users/Darshan/Downloads/GeM.md):

| # | Domain Section | Key Fields | Source in HTML Card | Source in Bid Document PDF |
|:---:|:---|:---|:---|:---|
| **1** | **Core Bid & Card** | `bid_no`, `ra_no`, `bid_type`, `product_type`, `base_type`, `process_kind` | Card header, link text, category tag | Header block / Watermark |
| **2** | **Card Items & Depts** | `card.items[]`, `card.departments[]` | "Items", "Quantity", "Department Name And Address" | First page buyer detail |
| **3** | **Timing Details** | `start_date`, `end_date`, `bid_end_datetime`, `bid_opening_datetime`, `bid_offer_validity_days` | Card start/end text | Rows: "Bid End Date/Time", "Bid Opening Date/Time", "Bid Offer Validity" |
| **4** | **Department Hierarchy** | `ministry_state_name`, `department_name`, `organisation_name`, `office_name` | Top card line | Rows: "Ministry/State Name", "Department Name", "Organisation Name", "Office Name" |
| **5** | **Items & Schedules** | `schedule_no`, `item_category`, `quantity` | Card Items block | Schedule table / "Total Quantity" row |
| **6** | **Seller Documents** | `required_from_seller[]`, `show_uploaded_docs_to_all_bidders`, attachments | N/A | Row: "Document required from seller" (comma-separated), Attachment list |
| **7** | **Consignees** | `consignee_name`, `address_raw`, `pincode`, `city`, `state`, `quantity`, `delivery_days` | N/A | Table: "Consignees/Reporting Officer" |
| **8** | **Relaxations** | `mse_relaxation_experience_turnover`, `startup_relaxation_experience_turnover` | N/A | Rows: "MSE Relaxation...", "Startup Relaxation..." |
| **9** | **Auto Extension** | `min_bids_to_disable_extension`, `auto_extend_days`, `auto_extension_count` | N/A | Rows: "Minimum number of bids required...", "Number of days...", "Number of Auto Extension count" |
| **10** | **Reverse Auction** | `bid_to_ra_enabled`, `ra_qualification_rule` | N/A | Rows: "Bid to RA enabled", "RA Qualification Rule" |
| **11** | **Packet & Clarification** | `type_of_bid`, `technical_clarification_window_days` | N/A | Rows: "Type of Bid", "Time allowed for Technical Clarifications..." |
| **12** | **Inspection** | `inspection_required`, `inspection_agency_type` | N/A | Row: "Inspection Required (By Empanelled Inspection Authority...)" |
| **13** | **Evaluation Method** | `evaluation_method`, `schedules[]` | N/A | Row: "Evaluation Method" (Total value wise / Item wise / Group wise) |
| **14** | **Legal Clauses** | `arbitration_clause`, `mediation_clause`, Land border restriction | N/A | Rows: "Arbitration Clause", "Mediation Clause", GTC Clause 26 |
| **15** | **MII Preference** | `mii_purchase_preference`, `mii_price_band_percent` (L1+X%), `mii_max_quantity_percent` | N/A | Rows: "MII Purchase Preference", "Purchase Preference to MII sellers available upto...", "Maximum Percentage..." |
| **16** | **MSE Preference** | `mse_purchase_preference`, `mse_price_band_percent` (L1+X%), `mse_max_quantity_percent` | N/A | Rows: "MSE Purchase Preference", "Purchase Preference to MSE OEMs...", "Maximum Percentage..." |
| **17** | **Financials (EMD/ePBG)**| `emd.required`, `emd.amount_total`, `advisory_bank`, `epbg.percent`, `epbg.duration_months` | N/A | Sections: "EMD Detail" and "ePBG Detail" |
| **18** | **Terms & ATC** | `special_terms_text`, `buyer_atc.generic`, `buyer_atc.items[]`, `buyer_atc.hard_requirements[]` | N/A | Sections: "Special terms and conditions", "Buyer Added Bid Specific Terms and Conditions" |

---

## 📐 4. Target JSON Schemas (V1, V2, and V3)

### A. V1 & V2 Flat/Nested Schema (Backend Django & TypeScript Model Base)
Used in Django [`apps.bids.models.Bid`](file:///F:/Projects/GEM/GEM/backend/apps/bids/models.py) and frontend [`src/types/bid.ts`](file:///F:/Projects/GEM/GEM/frontend/src/types/bid.ts):
```typescript
interface Bid {
  id: string;
  bidNo: string;
  raNo: string;
  items: string;
  quantity: number;
  departmentName: string;
  subDepartment: string;
  startDate: string;        // DD-MM-YYYY hh:mm AM/PM (web card)
  endDate: string;          // DD-MM-YYYY hh:mm AM/PM (web card)
  bid_end_date?: string;    // PDF Bid End Date/Time
  bid_opening_date?: string;// PDF Bid Opening Date/Time
  bidType: string;
  status: 'ongoing' | 'status' | string;
  highValue: boolean;
  estimated_value?: string;
  bid_packet_type?: string;
  earnest_amount?: string;
  bid_pdf?: string;         // Renamed from document_url
  bid_pdf_path?: string;    // Renamed from document_path
  pdf_intelligence?: {
    timeline?: { bid_opening_datetime?: string; bid_validity_days?: number; clarification_window_days?: number };
    eligibility?: { min_turnover_lakhs?: number; mse_relaxed_turnover_lakhs?: number; startup_exempt?: boolean; required_docs?: string[] };
    ra_rules?: { ra_enabled?: boolean; elimination_rule?: string; auto_extend_days?: number; auto_extend_max?: number; min_bids_to_disable_extension?: number };
    financials?: { emd_amount?: number; advisory_bank?: string; epbg_percent?: number; epbg_duration_months?: number };
    consignee_items?: Array<{ item_name?: string; consignee_name?: string; consignee_location?: string; pincode?: string; quantity?: number; delivery_days?: number }>;
    policy?: { mii_margin_percent?: number; mii_max_quantity_percent?: number; mse_margin_percent?: number; mse_max_quantity_percent?: number };
  };
  tender_record?: { tender_id?: string; tender_status?: string; work_desc?: string; tender_value?: any };
  normalized?: { base_type?: string; process_kind?: string; ra_mode?: string; tender_mode?: string };
}
```

### B. V3 Hierarchical Standard (Pipeline Output Schema)
Generated by `gem_scraper` per bid inside `downloads/<Bid_No>/<Bid_No>.json`:
```json
{
  "_id": "GEM_2026_B_XXXXXXX",
  "bid": {
    "bid_no": "GEM/2026/B/XXXXXXX",
    "ra_no": "GEM/2026/R/XXXXXX",
    "bid_type": "Product Bid/RAs",
    "product_type": "Product",
    "base_type": "PRODUCT",
    "process_kind": "CATALOGUE"
  },
  "card": {
    "items": [{ "name": "...", "quantity": 50 }],
    "departments": [{ "name": "...", "address": "...", "city": "...", "state": "...", "pincode": "..." }],
    "start_datetime": "27-06-2026 13:00",
    "end_datetime": "29-06-2026 13:09",
    "bid_pdf_url": "https://bidplus.gem.gov.in/showbidDocument/XXXXXXX",
    "ra_pdf_url": "https://bidplus.gem.gov.in/showbidDocument/XXXXXX"
  },
  "pdf": {
    "timing": { "bid_end_datetime": "...", "bid_opening_datetime": "...", "bid_offer_validity_days": 180 },
    "departments": [{ "ministry_state_name": "...", "department_name": "...", "organisation_name": "...", "office_name": "..." }],
    "items": [{ "schedule_no": 1, "item_category": "...", "quantity": 50 }],
    "documents": {
      "required_from_seller": ["Experience Criteria", "Bidder Turnover", "Certificate (Requested in ATC)"],
      "show_uploaded_docs_to_all_bidders": true,
      "attachments": [{ "kind": "SCOPE_OF_WORK", "filename": "SOW.pdf" }]
    },
    "consignees": [{ "consignee_name": "...", "address_raw": "...", "pincode": "...", "city": "...", "state": "...", "quantity": 50, "delivery_days": 30 }],
    "relaxations": { "mse_relaxation_experience_turnover": true, "startup_relaxation_experience_turnover": true },
    "auto_extension": { "min_bids_to_disable_extension": 3, "auto_extend_days": 7, "auto_extension_count": 3 },
    "ra": { "bid_to_ra_enabled": true, "ra_qualification_rule": "H1-Highest Priced Bid Elimination" },
    "bid_type": { "type_of_bid": "Two Packet Bid", "technical_clarification_window_days": 2 },
    "evaluation": { "evaluation_method": "Total value wise evaluation", "schedules": [] },
    "mii": { "mii_purchase_preference": true, "mii_price_band_percent": 20, "mii_max_quantity_percent": 50, "allow_only_class_1_2_local_suppliers": false },
    "mse": { "mse_purchase_preference": true, "mse_price_band_percent": 15, "mse_max_quantity_percent": 25 },
    "financials": {
      "emd": { "required": true, "advisory_bank": "State Bank of India", "amount_total": 50000 },
      "epbg": { "required": true, "percent": 5, "duration_months": 14 }
    },
    "terms": {
      "special_terms_text": "...",
      "buyer_atc": { "generic": "...", "hard_requirements": [...], "info_clauses": [...] }
    }
  },
  "hyperlinks": [{ "url": "https://...", "name": "Buyer uploaded ATC document", "source": "bid" }],
  "normalized": {},
  "validation": { "issues": [] },
  "full_pdf_text": "..."
}
```

---

## 🔵 5. Project 1 Deep-Dive: `gem_scraper` (Data & AI Engine)

**Location:** `F:\Projects\gem_scraper\`  
**Runtime:** Python 3.12 (Ubuntu on WSL2) with CUDA 13.0  
**Active Branches:**  
- `development`: Stable pipeline running local Mineru VLM on vLLM server.
- `development_v2`: Active refactor replacing Mineru with Mistral OCR API (`mistral-ocr-latest`).

### A. Core File Roles
- [`main.py`](file:///f:/Projects/gem_scraper/main.py): CLI dispatcher (`--once`, `--bid`, `--ask`, `--chat`, `--stats`, `--reindex`, `--reset`).
- [`core/browser.py`](file:///f:/Projects/gem_scraper/core/browser.py): Stealth Playwright browser automation (Chromium), handles anti-bot, pagination, and download hooks.
- [`core/parser.py`](file:///f:/Projects/gem_scraper/core/parser.py): Parses HTML DOM cards and regex parses PDF Markdown into the 17 domain sections.
- [`pipeline/scraper.py`](file:///f:/Projects/gem_scraper/pipeline/scraper.py): Orchestrates browser, PDF downloads, OCR engine, PyMuPDF links, Markdown assembly, SQLite upsert, and ChromaDB indexing.
- [`pipeline/scheduler.py`](file:///f:/Projects/gem_scraper/pipeline/scheduler.py): Hourly cron scheduler with `SIGINT`/`SIGTERM` graceful shutdown and new-bid detection alerts.
- [`storage/database.py`](file:///f:/Projects/gem_scraper/storage/database.py): SQLite storage manager for `bids` and `run_log` tables with deduplication on `document_url`.
- [`ATC EXTRACTOR/INFERENCE_ON_MARKDOWN.py`](file:///f:/Projects/gem_scraper/ATC%20EXTRACTOR/INFERENCE_ON_MARKDOWN.py): Dual-mode procurement terms & conditions analyzer:
  - **Gemini API Mode (Default):** Runs high-fidelity Full-Context Direct Analysis across all embedded Markdown and external attachments (PDF/DOCX) using the 1M token context window (`gemini-2.5-flash`). Zero local GPU or server overhead!
  - **Local Qwen Mode (Fallback):** MAP-REDUCE chunking pipeline with dynamic self-healing batching queues running against local `llama-server` (Qwen3-4B, port 8080).
  Categorizes ATC clauses into 5 actionable buckets:
  1. `STANDARD_DOCS`
  2. `ATC_PLACEHOLDER_CLARIFICATION`
  3. `EXEMPTION`
  4. `PHYSICAL_SUBMISSION`
  5. `COMMERCIAL_TERMS`

### B. Hybrid RAG Architecture (`rag/`)
- **Dense Leg:** `BAAI/bge-base-en-v1.5` embeddings (768-dim) in ChromaDB collection `gem_bids`.
- **Sparse Leg:** `rank-bm25` (BM25Okapi) indexing metadata cards (item name, department, bid no) and text passages.
- **Fusion:** Reciprocal Rank Fusion (RRF, $k=60$).
- **Reranker:** `BAAI/bge-reranker-base` cross-encoder with sigmoid probability normalization.
- **LLM Synthesis:** Ollama (`llama3`) or OpenAI (`gpt-4o-mini`) using a zero-hallucination, strict context prompt.

---

## 🟢 6. Project 2 Deep-Dive: `GEM` (Full-Stack Platform)

**Location:** `F:\Projects\GEM\GEM\`  
**Backend:** Django 5.1.4, Django REST Framework 3.15, SimpleJWT, SQLite/PostgreSQL  
**Frontend:** Next.js 16.2.6 (App Router), React 19.2.4, TypeScript 5, Tailwind CSS v4, Zod, React Hook Form  

### A. Backend Architecture (`backend/`)
- [`apps/auth/models.py`](file:///F:/Projects/GEM/GEM/backend/apps/auth/models.py): `CustomUser` with UUID PK, dual login (Email OR Mobile), 60-min JWT access token / 7-day refresh, and OTP recovery.
- [`apps/bids/models.py`](file:///F:/Projects/GEM/GEM/backend/apps/bids/models.py): `Bid` model matching GeM schema, with polymorphic lookup (UUID, `mongo_id`, or `bid_no`).
- [`apps/onboarding/models.py`](file:///F:/Projects/GEM/GEM/backend/apps/onboarding/models.py): `OnboardingProfile` with 8 JSON step payloads linked 1:1 with `CustomUser`.

### B. Frontend Architecture (`frontend/`)
- **9-Step Onboarding Engine (`src/app/onboarding/`):** Directly captures vendor qualifications required to evaluate eligibility against `GeM.md` tender rules:
  - `Step1AuthorizedPerson`: Legal signatory, Aadhaar, PAN.
  - `Step2BusinessIdentity`: GSTIN, Business Type, Organization structure.
  - `Step3Compliance`: **MSME / Udyam & DPIIT Startup Status** $\rightarrow$ Matches `pdf.relaxations`!
  - `Step4Banking`: Bank details, solvency certificate, EMD/ePBG capacity.
  - `Step5GeMReadiness`: GeM Seller ID, Primary categories.
  - `Step6ProductsServices`: Product offerings, catalogue mapping.
  - `Step7BidPreferences`: Preferred bid types, geographic states, value brackets.
  - `Step8Qualifications`: **3-Year Annual Turnover & Past Experience** $\rightarrow$ Matches `pdf.eligibility`!
  - `Step9ReviewSubmit`: Validation, verification, profile submission.
- **Bid Explorer UI (`src/app/bids/`):**
  - Bid cards with countdown timers, category tags, EMD values, and corrigendum badges.
  - Dedicated Reverse Auction `/bids/ra` interface.
  - Detail page `/bids/[id]` displaying summary and tender records.

---

## 🤝 7. Two-Way Integration Architecture

```
                    ┌───────────────────────────────┐
                    │     gem_scraper (WSL)         │
                    │   SQLite (gem_bids.db)        │
                    │   + JSON Artifacts            │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
             ETL Command: python manage.py import_scraped_bids
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │     GEM Django Backend        │
                    │                               │
                    │   • Bid Model (DB)            │
                    │   • Eligibility Match Engine  │
                    │   • /api/bids/ask/ RAG Proxy  │
                    └──────────────┬────────────────┘
                                   │
                                   ▼  REST API / JWT
                    ┌───────────────────────────────┐
                    │     GEM Next.js Frontend      │
                    │                               │
                    │   • Live Marketplace          │
                    │   • 1-Click Eligibility Badge │
                    │   • Actionable ATC Checklist  │
                    │   • Natural Language Q&A      │
                    └───────────────────────────────┘
```

### Integration Objectives:
1. **Automated ETL Ingestion:** Eliminate manual JSON copying into `frontend/src/data/` by writing a Django management command (`import_scraped_bids`) to read `gem_scraper/storage/gem_bids.db` directly.
2. **Vendor Eligibility Matching Engine:** Automatically compare `OnboardingProfile` (MSME status, annual turnover, experience years) against `Bid.pdf_intelligence`:
   - *Turnover Check:* Vendor Turnover $\ge$ `min_turnover_lakhs`? (Or relaxed for MSE?)
   - *Experience Check:* Vendor Experience $\ge$ `years_of_experience`? (Or Startup exempt?)
   - *UI Badge:* Display `Eligible`, `Eligible with MSE Relaxation`, or `Ineligible` on bid cards.
3. **ATC Checklist UI:** Display the 5-bucket output from `ATC EXTRACTOR/INFERENCE_ON_MARKDOWN.py` on `/bids/[id]` so vendors get an actionable checklist of required documents before bidding.
4. **Interactive Tender Q&A:** Expose `gem_scraper.rag.query_engine.QueryEngine` as a backend proxy endpoint `/api/bids/ask/` so vendors can chat with any tender document from the UI.

---

## 🚦 8. Implementation Status & Master Gap Matrix

| # | Feature / Module | Blueprint Reference | `gem_scraper` | `GEM` App | Status |
|:---:|:---|:---|:---:|:---:|:---:|
| **1** | **Playwright Scraper** | GeM 10 Bid Types | ✅ All 9 ongoing types scraped | N/A | **DONE** |
| **2** | **Document OCR** | PDF $\rightarrow$ Markdown | ✅ Mineru VLM (v1)<br>🟡 Mistral OCR (v2 branch) | N/A | **IN PROGRESS** |
| **3** | **Card Parsing** | HTML Card Details | ✅ Full card parser | ✅ Model & Serializers | **DONE** |
| **4** | **PDF Parser** | 17 PDF Sections | ✅ `core/parser.py` | ✅ `Bid` & `bid.ts` | **DONE** |
| **5** | **Multi-Item / BoQ** | BoQ tables $>5$ items | 🟡 Test script exists | 🟡 String field only | **PARTIAL** |
| **6** | **Hyperlinks & ATC Files** | PyMuPDF Link Harvest | ✅ Links extracted & injected | 🟡 URL stored only | **PARTIAL** |
| **7** | **ATC Clause Extraction** | Buyer Added ATC Analysis | ✅ Qwen3-4B MAP-REDUCE | ❌ UI display pending | **IN PROGRESS** |
| **8** | **Hybrid RAG Engine** | Bid Q&A & Search | ✅ Dense + BM25 + Cross-Encoder | ❌ API endpoint pending | **IN PROGRESS** |
| **9** | **Vendor Onboarding** | Eligibility Profiles | N/A | ✅ 9-Step wizard built | **DONE** |
| **10**| **Eligibility Matching** | Vendor vs Tender Rules | ❌ Engine pending | ❌ UI badge pending | **ROADMAP** |
| **11**| **Live Data Bridge** | Automated ETL Sync | ✅ SQLite/JSON exported | ❌ Direct import pending | **ROADMAP** |

---

## 🏃 9. Operational Cheat-Sheet (Commands)

### Scraper & RAG Operations (WSL / Linux)
```bash
# Enter environment
cd /mnt/f/Projects/gem_scraper
source ~/VLLM_Env/bin/activate

# Single targeted bid scrape
python main.py --bid "GEM/2026/B/7853146"

# Single full-pass scrape run
python main.py --once

# Continuous hourly scraper loop
python main.py

# RAG tender search & question query
python main.py --ask "Show me medical equipment tenders with MSE relaxation"

# Run ATC extraction on downloaded bid Markdowns via Gemini API (default, 1M context, no local server needed)
python "ATC EXTRACTOR/INFERENCE_ON_MARKDOWN.py" downloads/

# (Optional) Run ATC extraction via local Qwen (requires local llama-server running first):
# bash "ATC EXTRACTOR/Start_Llama_CPP_Qwen3_4B_GGUF_Server.sh"
# ATC_LLM_PROVIDER=local_qwen python "ATC EXTRACTOR/INFERENCE_ON_MARKDOWN.py" downloads/
```

### Full-Stack Platform Operations (Windows)
```bash
# Terminal 1 — Django Backend
cd F:\Projects\GEM\GEM\backend
venv\Scripts\activate
python manage.py runserver 8000
# API Base: http://localhost:8000/api/

# Terminal 2 — Next.js Frontend
cd F:\Projects\GEM\GEM\frontend
npm run dev
# Web UI: http://localhost:3000
```

---

*GeMBridge Master Architecture Document — Authoritative blueprint synchronized across both repositories.*
