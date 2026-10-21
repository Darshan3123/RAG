# GeMBridge REST API — Complete Request, Command & Output Reference

**Base URL**: `http://localhost:8000`  
**Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)  
**ReDoc Specification**: [http://localhost:8000/redoc](http://localhost:8000/redoc)  
**Tender Sample ID Used in Examples**: `GEM_2026_B_7879177` (or `GEM/2026/B/7879177`)

---

## Quick Navigation
1. [Health & System Status](#1-health--system-status)
2. [Master Tender Dossier & Partitions](#2-master-tender-dossier--partitions)
   - [2.1 Master Paginated Tender List](#21-master-paginated-tender-list)
   - [2.2 Complete Exhaustive Master Dossier](#22-complete-exhaustive-master-dossier)
   - [2.3 Raw Unaltered Scraped JSON](#23-raw-unaltered-scraped-json)
   - [2.4 Partition P1: Lifecycle & Identity](#24-partition-p1-lifecycle--identity)
   - [2.5 Partition P2: Buyer & Governance](#25-partition-p2-buyer--governance)
   - [2.6 Partition P3: Items & Tech Specs](#26-partition-p3-items--tech-specs)
   - [2.7 Partition P4: Logistics & Consignees](#27-partition-p4-logistics--consignees)
   - [2.8 Partition P5: Financials, EMD & ePBG](#28-partition-p5-financials-emd--epbg)
   - [2.9 Partition P6: Policy Preferences (MSE & MII)](#29-partition-p6-policy-preferences-mse--mii)
   - [2.10 Partition P7: Mandatory Upload Documents](#210-partition-p7-mandatory-upload-documents)
   - [2.11 Partition P8: AI-Analyzed ATC Compliance Checklist](#211-partition-p8-ai-analyzed-atc-compliance-checklist)
   - [2.12 Partition P9: Physical Submissions](#212-partition-p9-physical-submissions)
3. [Discovery & Aggregations](#3-discovery--aggregations)
   - [3.1 Bid Types Breakdown](#31-bid-types-breakdown)
   - [3.2 Top Procuring Organizations Directory](#32-top-procuring-organizations-directory)
   - [3.3 State-Level Procurement Overview](#33-state-level-procurement-overview)
   - [3.4 Tenders by State](#34-tenders-by-state)
   - [3.5 Tenders by Freight Delivery Pincode](#35-tenders-by-freight-delivery-pincode)
4. [Search & AI Semantic Retrieval](#4-search--ai-semantic-retrieval)
   - [4.1 Instant Auto-Complete Search](#41-instant-auto-complete-search)
   - [4.2 Fuzzy Trigram Keyword Search](#42-fuzzy-trigram-keyword-search)
   - [4.3 pgvector Natural Language Semantic Search](#43-pgvector-natural-language-semantic-search)
5. [Document Storage & Streaming (MinIO S3)](#5-document-storage--streaming-minio-s3)
   - [5.1 Presigned Tender PDF Download URL](#51-presigned-tender-pdf-download-url)
6. [Asynchronous Celery Operations](#6-asynchronous-celery-operations)
   - [6.1 Trigger Immediate Tender Scrape](#61-trigger-immediate-tender-scrape)
   - [6.2 Trigger Category Portal Crawl](#62-trigger-category-portal-crawl)
   - [6.3 Check Task Execution Status](#63-check-task-execution-status)
7. [Analytics & System Telemetry](#7-analytics--system-telemetry)
   - [7.1 Overall Pipeline KPIs Overview](#71-overall-pipeline-kpis-overview)
   - [7.2 Gemini AI & OCR Financial Telemetry](#72-gemini-ai--ocr-financial-telemetry)

---

## 1. Health & System Status

### `GET /health`
Returns service availability, gateway software version, and UTC timestamp.

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
```

**cURL:**
```bash
curl -X GET "http://localhost:8000/health" -H "Accept: application/json"
```

#### JSON Response (HTTP 200 OK)
```json
{
  "status": "healthy",
  "version": "3.0.0",
  "service": "GeMBridge REST API Gateway",
  "timestamp": "2026-10-21T10:31:47.638373+00:00"
}
```

---

## 2. Master Tender Dossier & Partitions

### 2.1 Master Paginated Tender List
### `GET /api/v1/bids`
High-speed paginated tender listing supporting multi-field filtering (`status`, `bid_type`, `state`, `min_value`, `max_value`, `search`). Response latency is under 5ms.

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids?limit=1&page=1" -Method Get
```

**cURL:**
```bash
curl -X GET "http://localhost:8000/api/v1/bids?limit=1&page=1" -H "Accept: application/json"
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "pagination": {
    "total_records": 20,
    "current_page": 1,
    "limit": 1,
    "total_pages": 20
  },
  "data": [
    {
      "bid_no": "GEM/2026/B/7879177",
      "bid_type": "Product Bid/RAs",
      "product_type": "Product",
      "status": "ongoing",
      "title_item": "8TH GEN 6 CORE INTEL i5 PROCESSOR",
      "total_quantity": 35.0,
      "estimated_value": null,
      "emd_amount": null,
      "department": "Department Of Military Affairs",
      "organisation": "Indian Air Force",
      "state": "Ministry Of Defence",
      "end_datetime": "2026-10-21T10:25:00+05:30",
      "days_remaining": 0.0
    }
  ]
}
```

---

### 2.2 Complete Exhaustive Master Dossier
### `GET /api/v1/bids/{bid_no}`
Aggregates all 10 normalized PostgreSQL tables into a single unified JSON dossier, including technical items, consignees, financial rules, policy preferences, and AI compliance audit.

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177" -Method Get
```

**cURL:**
```bash
curl -X GET "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177" -H "Accept: application/json"
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "ra_no": "GEM/2026/R/755008",
  "bid_type": "Product Bid/RAs",
  "product_type": "Product",
  "status": "ongoing",
  "timing": {
    "start_datetime": "2026-10-20T10:00:00+05:30",
    "end_datetime": "2026-10-21T10:25:00+05:30",
    "bid_opening_datetime": "2026-08-17T15:00:00+05:30",
    "bid_offer_validity_days": 180,
    "days_remaining": 0.0
  },
  "buyer": {
    "ministry_state_name": "Ministry Of Defence",
    "department_name": "Department Of Military Affairs",
    "organisation_name": "Indian Air Force",
    "office_name": "***"
  },
  "financials": {
    "estimated_value": null,
    "emd_required": false,
    "emd_amount": null,
    "emd_advisory_bank": "",
    "epbg_required": false,
    "epbg_percent": null
  },
  "policy": {
    "mse_preference": true,
    "mse_price_band_percent": 15.0,
    "mse_max_quantity_percent": 25.0,
    "mse_relaxation": true,
    "startup_relaxation": true,
    "mii_preference": false
  },
  "items": [
    {
      "item_index": 1,
      "item_category": "8TH GEN 6 CORE INTEL i5 PROCESSOR",
      "quantity": 35.0,
      "specifications": null
    }
  ],
  "consignees": [
    {
      "officer_name": "***",
      "address": "***NORTH 24 PARAGANAS",
      "city": null,
      "pincode": null,
      "quantity": 35.0,
      "delivery_days": 30
    }
  ],
  "atc": {
    "has_atc": true,
    "domains": {
      "STANDARD_DOCS": [
        "Experience Criteria",
        "Past Performance",
        "Bidder Turnover",
        "OEM Annual Turnover"
      ],
      "ATC_DOCUMENTS_AND_UPLOADS": [
        "Certificate",
        "Compliance statement regarding Processor specification (Intel i5 8th Gen, Windows 11 compatibility, TPM 2.0)",
        "Any certificates/documents sought in the Bid document, ATC and Corrigendum"
      ],
      "ELIGIBILITY_AND_QUALIFICATION": [
        "Bidder's offer is liable to be rejected if they don't upload any of the certificates / documents sought in the Bid document, ATC and Corrigendum",
        "No refurbish material will be accepted."
      ],
      "SCOPE_DELIVERY_WARRANTY_AND_SUPPORT": [
        "Option Clause: Purchaser reserves the right to increase or decrease the quantity to be ordered up to 50 percent of bid quantity at the time of placement of contract.",
        "Intel Processor i5 8th Gen must be compatible with Windows 11 OS.",
        "Processor must have TPM 2.0.",
        "Warranty: 3 years.",
        "Vender should report to IT section within 24 hours in case of unserviceability.",
        "Unserviceable item to be replaced within 72 hours and unserviceable item will not be returned to supplier."
      ],
      "PENALTIES_REJECTION_AND_LEGAL_TERMS": [
        "Bidder's offer is liable to be rejected if they don't upload any of the certificates / documents sought in the Bid document, ATC and Corrigendum if any."
      ]
    }
  },
  "documents": {
    "bid_pdf_download_url": "http://localhost:9000/gem-tenders/bids/GEM_2026_B_7879177/bid.pdf?...",
    "atc_compliance_url": "http://localhost:9000/gem-tenders/bids/GEM_2026_B_7879177/atc_compliance.json?..."
  }
}
```

---

### 2.3 Raw Unaltered Scraped JSON
### `GET /api/v1/bids/{bid_no}/raw`
Returns the exact original scraped payload directly from the database's `raw_data` backup column.

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/raw" -Method Get
```

---

### 2.4 Partition P1: Lifecycle & Identity
### `GET /api/v1/bids/{bid_no}/header`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/header" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "ra_no": "GEM/2026/R/755008",
  "bid_type": "Product Bid/RAs",
  "product_type": "Product",
  "status": "ongoing",
  "start_datetime": "2026-10-20T10:00:00+05:30",
  "end_datetime": "2026-10-21T10:25:00+05:30",
  "bid_opening_datetime": "2026-08-17T15:00:00+05:30",
  "bid_offer_validity_days": 180,
  "bid_duration_days": 1.02,
  "days_remaining": 0.0,
  "is_expired": false
}
```

---

### 2.5 Partition P2: Buyer & Governance
### `GET /api/v1/bids/{bid_no}/buyer`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/buyer" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "ministry_state_name": "Ministry Of Defence",
  "department_name": "Department Of Military Affairs",
  "organisation_name": "Indian Air Force",
  "office_name": "***"
}
```

---

### 2.6 Partition P3: Items & Tech Specs
### `GET /api/v1/bids/{bid_no}/items`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/items" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "total_items_count": 1,
  "total_quantity": 35.0,
  "items": [
    {
      "item_index": 1,
      "item_category": "8TH GEN 6 CORE INTEL i5 PROCESSOR",
      "quantity": 35.0,
      "source": "pdf",
      "specifications": null
    }
  ]
}
```

---

### 2.7 Partition P4: Logistics & Consignees
### `GET /api/v1/bids/{bid_no}/consignees`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/consignees" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "total_locations": 1,
  "consignees": [
    {
      "officer_name": "***",
      "address": "***NORTH 24 PARAGANAS",
      "city": null,
      "pincode": null,
      "quantity": 35.0,
      "delivery_days": 30,
      "is_lumpsum": false
    }
  ]
}
```

---

### 2.8 Partition P5: Financials, EMD & ePBG
### `GET /api/v1/bids/{bid_no}/financials`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/financials" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "estimated_value": null,
  "currency": "INR",
  "is_high_value": false,
  "emd": {
    "required": false,
    "amount": null,
    "percent_of_estimated_value": null,
    "advisory_bank": ""
  },
  "epbg": {
    "required": false,
    "percent": null,
    "duration_months": null,
    "advisory_bank": ""
  },
  "exemptions": {
    "emd_exemption_clause": ""
  }
}
```

---

### 2.9 Partition P6: Policy Preferences (MSE & MII)
### `GET /api/v1/bids/{bid_no}/policy`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/policy" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "mse_preference": true,
  "mse_price_band_percent": 15.0,
  "mse_max_quantity_percent": 25.0,
  "mse_relaxation": true,
  "startup_relaxation": true,
  "mii_preference": false,
  "mii_class": "Class 1",
  "mii_min_local_content_percent": null
}
```

---

### 2.10 Partition P7: Mandatory Upload Documents
### `GET /api/v1/bids/{bid_no}/documents`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/documents" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "mandatory_documents_count": 5,
  "document_names": [
    "Experience Criteria",
    "Past Performance",
    "Bidder Turnover",
    "Certificate (Requested in ATC)",
    "OEM Annual Turnover"
  ]
}
```

---

### 2.11 Partition P8: AI-Analyzed ATC Compliance Checklist
### `GET /api/v1/bids/{bid_no}/atc`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/atc" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "has_atc": true,
  "domains": {
    "STANDARD_DOCS": [
      "Experience Criteria",
      "Past Performance",
      "Bidder Turnover",
      "OEM Annual Turnover"
    ],
    "ATC_DOCUMENTS_AND_UPLOADS": [
      "Certificate",
      "Compliance statement regarding Processor specification (Intel i5 8th Gen, Windows 11 compatibility, TPM 2.0)",
      "Any certificates/documents sought in the Bid document, ATC and Corrigendum"
    ],
    "ELIGIBILITY_AND_QUALIFICATION": [
      "Bidder's offer is liable to be rejected if they don't upload any of the certificates / documents sought in the Bid document, ATC and Corrigendum",
      "No refurbish material will be accepted."
    ],
    "SCOPE_DELIVERY_WARRANTY_AND_SUPPORT": [
      "Option Clause: Purchaser reserves the right to increase or decrease the quantity to be ordered up to 50 percent of bid quantity at the time of placement of contract.",
      "Option Clause: Purchaser reserves the right to increase the ordered quantity up to 50% of the contracted quantity during the currency of the contract at the contracted rates.",
      "The additional delivery time for option clause is (Increased quantity ÷ Original quantity) × Original delivery period (in days), subject to minimum of 30 days.",
      "If the original delivery period is less than 30 days, the additional time equals the original delivery period.",
      "Intel Processor i5 8th Gen must be compatible with Windows 11 OS.",
      "Processor must have TPM 2.0.",
      "Warranty: 3 years.",
      "Vender should report to IT section within 24 hours in case of unserviceability.",
      "Unserviceable item to be replaced within 72 hours and unserviceable item will not be returned to supplier."
    ],
    "PENALTIES_REJECTION_AND_LEGAL_TERMS": [
      "Bidder's offer is liable to be rejected if they don't upload any of the certificates / documents sought in the Bid document, ATC and Corrigendum if any."
    ]
  }
}
```

---

### 2.12 Partition P9: Physical Submissions
### `GET /api/v1/bids/{bid_no}/submissions`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/bids/GEM_2026_B_7879177/submissions" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "physical_submissions_required": false,
  "submissions": []
}
```

---

## 3. Discovery & Aggregations

### 3.1 Bid Types Breakdown
### `GET /api/v1/types`
Returns aggregate tender counts and estimated budget values grouped by all 9 GeM procurement types.

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/types" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "total_active_bids": 19,
  "types": [
    {
      "type_name": "Product Bid/RAs",
      "category_label": "Product",
      "active_bids_count": 3,
      "total_estimated_value": 0.0
    },
    {
      "type_name": "Limited Tender",
      "category_label": "Limited Tender",
      "active_bids_count": 2,
      "total_estimated_value": 11011641.0
    },
    {
      "type_name": "Service Bid/RAs",
      "category_label": "Service",
      "active_bids_count": 2,
      "total_estimated_value": 9486953.0
    },
    {
      "type_name": "Product Custom Bid/RAs",
      "category_label": "Product",
      "active_bids_count": 2,
      "total_estimated_value": 0.0
    },
    {
      "type_name": "Bid To RAs",
      "category_label": "Bid To RA",
      "active_bids_count": 2,
      "total_estimated_value": 130984.71
    },
    {
      "type_name": "Single Tender",
      "category_label": "Single Tender",
      "active_bids_count": 2,
      "total_estimated_value": 855720.0
    },
    {
      "type_name": "Rate Contract Bids",
      "category_label": "Rate Contract",
      "active_bids_count": 2,
      "total_estimated_value": 103369708.3
    },
    {
      "type_name": "Global Tender",
      "category_label": "Global Tender",
      "active_bids_count": 2,
      "total_estimated_value": 19000000.0
    },
    {
      "type_name": "BOQ Bids",
      "category_label": "BOQ",
      "active_bids_count": 2,
      "total_estimated_value": 1073050.0
    }
  ]
}
```

---

### 3.2 Top Procuring Organizations Directory
### `GET /api/v1/organizations?limit=2`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/organizations?limit=2" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "total_organizations": 2,
  "organizations": [
    {
      "organisation_name": "Indian Air Force",
      "department_name": "Department Of Military Affairs",
      "state": "Ministry Of Defence",
      "active_bids_count": 4,
      "total_pipeline_value": 0.0
    },
    {
      "organisation_name": "N/a",
      "department_name": "Health And Family Welfare Department Delhi",
      "state": "Delhi",
      "active_bids_count": 1,
      "total_pipeline_value": 61369708.3
    }
  ]
}
```

---

### 3.3 State-Level Procurement Overview
### `GET /api/v1/locations/states`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/locations/states" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "total_states": 14,
  "states": [
    {
      "state": "Andhra Pradesh",
      "active_bids_count": 1,
      "total_pipeline_value": 0.0
    },
    {
      "state": "Delhi",
      "active_bids_count": 1,
      "total_pipeline_value": 61369708.3
    },
    {
      "state": "Ministry Of Defence",
      "active_bids_count": 4,
      "total_pipeline_value": 0.0
    },
    {
      "state": "Ministry Of Home Affairs",
      "active_bids_count": 1,
      "total_pipeline_value": 642600.0
    }
  ]
}
```

---

### 3.4 Tenders by State
### `GET /api/v1/locations/states/{state_name}/bids`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/locations/states/Delhi/bids?limit=5" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "state": "Delhi",
  "active_tenders_count": 1,
  "bids": [
    {
      "bid_no": "GEM/2026/B/8032806",
      "organisation": "N/a",
      "title_item": "Adenosine",
      "estimated_value": 61369708.3,
      "end_datetime": "2026-10-21T16:00:00+05:30"
    }
  ]
}
```

---

### 3.5 Tenders by Freight Delivery Pincode
### `GET /api/v1/locations/pincode/{pincode}/bids`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/locations/pincode/110001/bids" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "pincode": "110001",
  "city": "New Delhi",
  "matching_tenders": 1,
  "bids": [
    {
      "bid_no": "GEM/2026/B/8032806",
      "organisation": "Health And Family Welfare Department Delhi",
      "title_item": "Adenosine",
      "quantity": 1000.0,
      "delivery_days": 15
    }
  ]
}
```

---

## 4. Search & AI Semantic Retrieval

### 4.1 Instant Auto-Complete Search
### `GET /api/v1/search/quick?q=GEM`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/search/quick?q=GEM" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "query": "GEM",
  "suggestions": {
    "bids": [
      {
        "bid_no": "GEM/2026/B/7879177",
        "organisation": "Indian Air Force",
        "estimated_value": null
      },
      {
        "bid_no": "GEM/2026/B/7852033",
        "organisation": "Indian Air Force",
        "estimated_value": null
      },
      {
        "bid_no": "GEM/2026/B/8047003",
        "organisation": "Rourkela Steel Plant",
        "estimated_value": null
      },
      {
        "bid_no": "GEM/2026/B/7735850",
        "organisation": "Odisha Power Generation Corporation Limited",
        "estimated_value": null
      },
      {
        "bid_no": "GEM/2026/B/7941225",
        "organisation": "Bharat Sanchar Nigam Limited Portal (bsnl)",
        "estimated_value": 9486953.0
      }
    ],
    "categories": [],
    "organizations": []
  }
}
```

---

### 4.2 Fuzzy Trigram Keyword Search
### `GET /api/v1/search/keyword?q=processor`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/search/keyword?q=processor" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "query": "processor",
  "matches": [
    {
      "bid_no": "GEM/2026/B/7879177",
      "item_category": "8TH GEN 6 CORE INTEL i5 PROCESSOR",
      "organisation": "Indian Air Force",
      "similarity": 0.8
    }
  ]
}
```

---

### 4.3 pgvector Natural Language Semantic Search
### `POST /api/v1/search/semantic`
Generates a 768-dimensional BGE embedding vector on the fly and performs cosine distance vector search against PostgreSQL's `gem_bid_chunks` via the HNSW index.

#### Request Commands
**PowerShell:**
```powershell
$body = @{ query = "cctv surveillance camera"; top_k = 1 } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/search/semantic" -Method Post -ContentType "application/json" -Body $body
```

**cURL:**
```bash
curl -X POST "http://localhost:8000/api/v1/search/semantic" \
     -H "Content-Type: application/json" \
     -d '{"query": "cctv surveillance camera", "top_k": 1}'
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "query": "cctv surveillance camera",
  "retrieval_latency_ms": 32.14,
  "results_count": 1,
  "results": [
    {
      "bid_no": "GEM/2026/B/7779512",
      "chunk_type": "general_pdf",
      "similarity_score": 0.4372,
      "distance": 0.5628,
      "matching_text": "bsequent Orders/Notifications issued by concerned Nodal Ministry for specific Goods/Products. The minimum local content to qualify as a Class 1 local supplier is denoted in the bid document...",
      "metadata": {
        "bid_no": "GEM/2026/B/7779512",
        "source": "general_pdf",
        "chunk_index": 14
      }
    }
  ]
}
```

---

## 5. Document Storage & Streaming (MinIO S3)

### 5.1 Presigned Tender PDF Download URL
### `GET /api/v1/documents/{bid_no}/pdf`
Generates a secure, time-limited presigned MinIO S3 URL (valid for 15 minutes) for high-speed direct document streaming without putting bandwidth burden on the FastAPI server.

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/documents/GEM_2026_B_7879177/pdf" -Method Get
```

**cURL:**
```bash
curl -X GET "http://localhost:8000/api/v1/documents/GEM_2026_B_7879177/pdf" -H "Accept: application/json"
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "bid_no": "GEM/2026/B/7879177",
  "document_type": "bid_pdf",
  "expires_in_seconds": 900,
  "download_url": "http://localhost:9000/gem-tenders/bids/GEM_2026_B_7879177/bid.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20261021%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20261021T103225Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=9a584ad820ad8202e6a4e70612de9e2022d7e083c84cbb2047a5e585f023e187"
}
```

> **Direct Download Tip**: Pass `?redirect=true` to have the browser immediately redirect (HTTP 307) straight to the PDF download stream:
> `http://localhost:8000/api/v1/documents/GEM_2026_B_7879177/pdf?redirect=true`

---

## 6. Asynchronous Celery Operations

### 6.1 Trigger Immediate Tender Scrape
### `POST /api/v1/tasks/scrape-bid`
Dispatches an ad-hoc crawling and processing job for a single tender to Celery's `scraping_queue`.

#### Request Commands
**PowerShell:**
```powershell
$body = @{ bid_no = "GEM/2026/B/7879177" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tasks/scrape-bid" -Method Post -ContentType "application/json" -Body $body
```

**cURL:**
```bash
curl -X POST "http://localhost:8000/api/v1/tasks/scrape-bid" \
     -H "Content-Type: application/json" \
     -d '{"bid_no": "GEM/2026/B/7879177"}'
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "task_id": "42801c93-4f29-47df-9e61-357f8781c7f1",
  "status": "QUEUED",
  "queue": "scraping_queue",
  "message": "Crawl task dispatched for GEM/2026/B/7879177"
}
```

---

### 6.2 Trigger Category Portal Crawl
### `POST /api/v1/tasks/scrape-category`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tasks/scrape-category?bid_type=Product%20Bid/RAs&target_count=2" -Method Post
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "task_id": "35d95873-a0b8-4098-a8c1-7fdfde851503",
  "status": "QUEUED",
  "queue": "scraping_queue",
  "category": "Product Bid/RAs",
  "target_count": 2
}
```

---

### 6.3 Check Task Execution Status
### `GET /api/v1/tasks/{task_id}`

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tasks/42801c93-4f29-47df-9e61-357f8781c7f1" -Method Get
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "task_id": "42801c93-4f29-47df-9e61-357f8781c7f1",
  "status": "SUCCESS",
  "result": {
    "status": "completed",
    "bid_no": "GEM_2026_B_7879177",
    "message": "Tender GEM/2026/B/7879177 processed successfully."
  }
}
```

---

## 7. Analytics & System Telemetry

### 7.1 Overall Pipeline KPIs Overview
### `GET /api/v1/analytics/overview`
Real-time KPI metrics aggregated across all active, ongoing, and completed procurement tenders.

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/analytics/overview" -Method Get
```

**cURL:**
```bash
curl -X GET "http://localhost:8000/api/v1/analytics/overview" -H "Accept: application/json"
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "metrics": {
    "total_tenders_scraped": 20,
    "active_ongoing_tenders": 19,
    "expired_tenders": 1,
    "total_estimated_pipeline_inr": 144928057.01,
    "total_items_procured": 85716.0,
    "total_delivery_locations": 39,
    "average_emd_amount_inr": 377267.5
  }
}
```

---

### 7.2 Gemini AI & OCR Financial Telemetry
### `GET /api/v1/analytics/ai-telemetry`
Aggregates token consumption, AI compliance latency, and financial costs across all analyzed bids.

#### Request Commands
**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/analytics/ai-telemetry" -Method Get
```

**cURL:**
```bash
curl -X GET "http://localhost:8000/api/v1/analytics/ai-telemetry" -H "Accept: application/json"
```

#### JSON Response (HTTP 200 OK)
```json
{
  "success": true,
  "ai_telemetry": {
    "total_tenders_analyzed": 20,
    "total_input_tokens": 356230,
    "total_output_tokens": 20820,
    "total_cost_usd": 0.0165,
    "total_cost_inr": 1.43,
    "average_cost_per_bid_inr": 0.07,
    "average_latency_seconds": 6.81
  }
}
```
