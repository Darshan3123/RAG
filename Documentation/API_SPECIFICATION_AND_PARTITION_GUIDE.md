# 📘 GeMBridge REST API Gateway: Complete Specification & Partitioning Guide

> **Document Version:** 3.0.0 — Production Standard  
> **Target Audience:** Frontend Engineers, Backend Developers, B2B Partners, Enterprise Clients  
> **Base URL (Local):** `http://localhost:8000/api/v1`  
> **Interactive Swagger UI:** `http://localhost:8000/docs`  
> **Interactive ReDoc UI:** `http://localhost:8000/redoc`  
> **Underlying Stack:** FastAPI (ASGI), PostgreSQL 18 (`pgvector` & `pg_trgm`), MinIO S3 Object Storage, Redis 7 & Celery Workers  

---

## 📑 Table of Contents

1. [Executive Overview: Architecture & Partitioning Philosophy](#1-executive-overview-architecture--partitioning-philosophy)
2. [Data Partitioning Strategy (10 Logical Modules)](#2-data-partitioning-strategy-10-logical-modules)
3. [Authentication, Headers & Error Formats](#3-authentication-headers--error-formats)
4. [GROUP 1: General & Master APIs (The "All Data" Suite)](#group-1-general--master-apis-the-all-data-suite)
5. [GROUP 2: Partitioned Sub-Resource APIs (Frontend Tabs & B2B Feeds)](#group-2-partitioned-sub-resource-apis-frontend-tabs--b2b-feeds)
6. [GROUP 3: Discovery & Filter Aggregations (Types, Organizations & Geography)](#group-3-discovery--filter-aggregations-types-organizations--geography)
7. [GROUP 4: Search & AI Semantic Retrieval APIs](#group-4-search--ai-semantic-retrieval-apis)
8. [GROUP 5: Document Storage & Streaming APIs (MinIO S3)](#group-5-document-storage--streaming-apis-minio-s3)
9. [GROUP 6: Asynchronous Operations & Worker Task APIs](#group-6-asynchronous-operations--worker-task-apis)
10. [GROUP 7: Analytics & System Telemetry APIs](#group-7-analytics--system-telemetry-apis)

---

## 1. Executive Overview: Architecture & Partitioning Philosophy

The **GeMBridge REST Gateway** provides a unified, high-speed interface to Indian government procurement data from `bidplus.gem.gov.in`. 

### Dual-Purpose API Design:
1. **Frontend Optimization:** Government tenders contain deep technical specifications, multi-location delivery consignees, and 50+ compliance clauses. Decomposing tenders into modular partitions allows frontend applications (React, Vue, Mobile Apps) to render lightning-fast tables (<1.2 KB per row) and load tabbed components on demand without lag.
2. **B2B Partner Monetization / Scoped Data Feeds:** Third-party clients and partners often need only specific subsets of procurement data:
   * **Manufacturers & Suppliers** $\rightarrow$ Request only **Item Categories, Quantities & Specs**.
   * **Regional Contractors** $\rightarrow$ Request only **State, City & Pincode Logistics**.
   * **Fintech Lenders & Banks** $\rightarrow$ Request only **Estimated Values, EMD Amounts & Bank Guarantees**.
   * **Bidding & Legal Consultants** $\rightarrow$ Request only **Required Documents & ATC Compliance Clauses**.

---

## 2. Data Partitioning Strategy (10 Logical Modules)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 MASTER TENDER DOSSIER                                  │
├──────────────┬──────────────────┬─────────────────┬────────────────┬───────────────────┤
│ [P1: Header] │ [P2: Buyer Org]  │ [P3: Items]     │ [P4: Logistics]│ [P5: Financials]  │
├──────────────┼──────────────────┼─────────────────┼────────────────┼───────────────────┤
│ [P6: Policy] │ [P7: Documents]  │ [P8: ATC AI]    │ [P9: Submits]  │ [P10: Schedules]  │
└──────────────┴──────────────────┴─────────────────┴────────────────┴───────────────────┘
```

* **P1: Lifecycle & Identity:** Tender ID, RA number, start/end dates, opening date, days remaining, status.
* **P2: Buyer & Governance:** Central Ministry, State Government, Department, Procuring Organisation, Office.
* **P3: Items & Technical Specs:** Product names, quantities, units, and JSONB technical attribute specifications.
* **P4: Logistics & Consignees:** Delivery locations, consignee officers, pincodes, quantities, and delivery days.
* **P5: Financials & Bonds:** Estimated tender value, EMD required flag, EMD amount, advisory bank, EPBG %.
* **P6: Policy Preferences:** MSE purchase preference %, MSE relaxation, Startup waiver, Make in India local class.
* **P7: Mandatory Documents:** Exact list of mandatory certificates required from the seller.
* **P8: ATC Compliance Clauses:** AI-extracted 8-domain clauses (Standard Docs, Uploads, Exemptions, LD penalties, Warranties).
* **P9: Physical Submissions:** Offline hardcopy instruments (Demand Drafts, samples, payee names, deadlines).
* **P10: Evaluation Schedules:** Multi-lot / item-wise lot schedules for segmented bidding.

---

## 3. Authentication, Headers & Error Formats

### Standard Request Headers
```http
Accept: application/json
Content-Type: application/json
X-API-Key: gem_live_your_api_key_here
```

### Standard Error Response Format
```json
{
  "success": false,
  "error_code": "RESOURCE_NOT_FOUND",
  "message": "Tender 'GEM/2026/B/9999999' was not found in database.",
  "timestamp": "2026-10-19T11:45:00Z"
}
```

---

## GROUP 1: General & Master APIs (The "All Data" Suite)

### 1.1 Get Complete Tender Dossier
* **Route:** `GET /api/v1/bids/{bid_no}`
* **Description:** Returns the **complete, exhaustive tender record** across all 10 PostgreSQL tables, including master header, items, consignees, compliance clauses, offline submissions, and MinIO S3 presigned PDF links.
* **Path Parameter:** `bid_no` (string, e.g. `GEM/2025/B/6726924` or `GEM_2025_B_6726924`)
* **Query Parameter:** `include` (optional string, comma-separated list of partitions, or `all`. Default: `all`).

#### Example Request:
```http
GET /api/v1/bids/GEM_2025_B_6726924?include=all HTTP/1.1
Host: localhost:8000
Accept: application/json
```

#### Example Response:
```json
{
  "success": true,
  "bid_no": "GEM/2025/B/6726924",
  "ra_no": "GEM/2026/R/751289",
  "bid_type": "Product Bid/RAs",
  "product_type": "Product",
  "status": "ongoing",
  "timing": {
    "start_datetime": "2026-10-13T17:00:00+05:30",
    "end_datetime": "2026-11-17T18:00:00+05:30",
    "bid_opening_datetime": "2026-11-17T18:30:00+05:30",
    "bid_offer_validity_days": 180,
    "days_remaining": 29.5
  },
  "buyer": {
    "ministry_state_name": "Gujarat",
    "department_name": "Health & Family Welfare Department Gujarat",
    "organisation_name": "Gujarat Medical Services Corporation Limited (gmscl)",
    "office_name": "Gmscl"
  },
  "financials": {
    "estimated_value": 2532000.00,
    "emd_required": true,
    "emd_amount": 75960.00,
    "emd_advisory_bank": "State Bank of India",
    "epbg_required": true,
    "epbg_percent": 5.00
  },
  "policy": {
    "mse_preference": true,
    "mse_price_band_percent": 10.00,
    "mse_max_quantity_percent": 70.00,
    "mse_relaxation": false,
    "startup_relaxation": false,
    "mii_preference": false
  },
  "required_documents": [
    "Past Performance",
    "Bidder Turnover",
    "Certificate (Requested in ATC)",
    "OEM Authorization Certificate",
    "OEM Annual Turnover"
  ],
  "items": [
    {
      "item_index": 1,
      "item_category": "Centrifuge Tubes (V2) (Q3)",
      "quantity": 5064.00,
      "specifications": {
        "capacity_ml": 15,
        "material": "Polypropylene",
        "sterility": "Sterile",
        "graduated": "Yes"
      }
    }
  ],
  "consignees": [
    {
      "officer_name": "Makwana Mukeshbhai Manubhai",
      "address": "GMSCL-Ware House_Amreli, Near Civil Hospital, Amreli",
      "city": "Amreli",
      "pincode": "365601",
      "quantity": 255.00,
      "delivery_days": 330
    },
    {
      "officer_name": "Joshi Mitesh Amrutlal",
      "address": "GMSCL-Ware House_Bhuj, RTO Circle, Bhuj",
      "city": "Bhuj",
      "pincode": "370001",
      "quantity": 193.00,
      "delivery_days": 330
    }
  ],
  "atc_checklist": {
    "STANDARD_DOCS": [
      "Upload certified audited balance sheets of previous 3 years.",
      "Upload manufacturer authorization certificate for quoted item."
    ],
    "PHYSICAL_SUBMISSIONS": [
      "Physical sample of 100 units must reach GMSCL Gandhinagar within 7 working days."
    ],
    "PENALTIES_REJECTION_AND_LEGAL_TERMS": [
      "Liquidated damages of 0.5% per week of delayed quantity up to 5% maximum."
    ]
  },
  "physical_submissions": [
    {
      "item_name": "Product Samples (100 units)",
      "deadline": "Within 7 working days of bid closure",
      "in_favor_of": "Managing Director, GMSCL",
      "payable_at": "Gandhinagar",
      "delivery_address": "Block-14, Dr. Jivraj Mehta Bhavan, Gandhinagar, Gujarat"
    }
  ],
  "documents": {
    "bid_pdf_download_url": "http://localhost:9000/gem-tenders/bids/GEM_2025_B_6726924/bid.pdf?X-Amz-Signature=...",
    "atc_compliance_url": "http://localhost:9000/gem-tenders/bids/GEM_2025_B_6726924/atc_compliance.json?X-Amz-Signature=..."
  }
}
```

---

### 1.2 Master Paginated & Filterable Tender List
* **Route:** `GET /api/v1/bids`
* **Description:** High-speed paginated tender listing with composite filters. Designed for frontend tables and live search interfaces.

#### Example Request:
```http
GET /api/v1/bids?status=ongoing&bid_type=Product+Bid%2FRAs&min_value=1000000&max_value=5000000&page=1&limit=2 HTTP/1.1
Host: localhost:8000
Accept: application/json
```

#### Example Response:
```json
{
  "success": true,
  "pagination": {
    "total_records": 48,
    "current_page": 1,
    "limit": 2,
    "total_pages": 24
  },
  "data": [
    {
      "bid_no": "GEM/2025/B/6726924",
      "bid_type": "Product Bid/RAs",
      "product_type": "Product",
      "status": "ongoing",
      "title_item": "Centrifuge Tubes (V2) (Q3)",
      "total_quantity": 5064.00,
      "estimated_value": 2532000.00,
      "emd_amount": 75960.00,
      "department": "Health & Family Welfare Department Gujarat",
      "organisation": "Gujarat Medical Services Corporation Limited",
      "state": "Gujarat",
      "end_datetime": "2026-11-17T18:00:00+05:30",
      "days_remaining": 29.5
    },
    {
      "bid_no": "GEM/2026/B/7548490",
      "bid_type": "Product Bid/RAs",
      "product_type": "Product",
      "status": "ongoing",
      "title_item": "Submersible Pump Set 5HP",
      "total_quantity": 12.00,
      "estimated_value": 1850000.00,
      "emd_amount": 55500.00,
      "department": "Public Health Engineering Department",
      "organisation": "PHED Rajasthan",
      "state": "Rajasthan",
      "end_datetime": "2026-11-20T15:00:00+05:30",
      "days_remaining": 32.1
    }
  ]
}
```

---

### 1.3 Get Original Scraped Raw JSON Backup
* **Route:** `GET /api/v1/bids/{bid_no}/raw`
* **Description:** Returns the raw unaltered JSON payload directly from the database's `raw_data` JSONB column.

#### Example Request:
```http
GET /api/v1/bids/GEM_2025_B_6726924/raw HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "_id": "GEM_2025_B_6726924",
  "bid": {
    "bid_no": "GEM/2025/B/6726924",
    "ra_no": "GEM/2026/R/751289",
    "bid_type": "Product Bid/RAs"
  },
  "card": {
    "items": [{"name": "Centrifuge Tubes (V2) (Q3)", "quantity": 5064}],
    "start_datetime": "13-10-2026 17:00:00",
    "end_datetime": "14-10-2026 17:32:00"
  }
}
```

---

## GROUP 2: Partitioned Sub-Resource APIs (Frontend Tabs & B2B Feeds)

These endpoints allow clients to fetch **strictly isolated slices** of a tender.

### 2.1 Items & Technical Specifications Partition
* **Route:** `GET /api/v1/bids/{bid_no}/items`
* **Description:** Returns the product catalogue items, requested quantities, and technical parameters for a tender.

#### Example Request:
```http
GET /api/v1/bids/GEM_2025_B_6726924/items HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "bid_no": "GEM/2025/B/6726924",
  "total_items_count": 1,
  "total_quantity": 5064.00,
  "items": [
    {
      "item_index": 1,
      "item_category": "Centrifuge Tubes (V2) (Q3)",
      "quantity": 5064.00,
      "source": "pdf",
      "specifications": {
        "Volume": "15 ml",
        "Graduation": "Conical bottom with printed graduations",
        "Max RCF Rating": "12000 x g",
        "Autoclavable": "Yes at 121 C",
        "Cap Type": "Flat screw cap with leak-proof seal"
      }
    }
  ]
}
```

---

### 2.2 Logistics & Consignees Partition
* **Route:** `GET /api/v1/bids/{bid_no}/consignees`
* **Description:** Returns delivery locations, warehouse consignee officers, delivery turnaround days, and regional pincodes.

#### Example Request:
```http
GET /api/v1/bids/GEM_2025_B_6726924/consignees HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "bid_no": "GEM/2025/B/6726924",
  "total_locations": 11,
  "consignees": [
    {
      "officer_name": "Makwana Mukeshbhai Manubhai",
      "address": "GMSCL-Ware House_Amreli, Near Civil Hospital, Amreli",
      "city": "Amreli",
      "pincode": "365601",
      "quantity": 255.00,
      "delivery_days": 330,
      "is_lumpsum": false
    },
    {
      "officer_name": "Raval Maulikkumar Rasiklal",
      "address": "GMSCL-Ware House_Patan, General Hospital Campus, Patan",
      "city": "Patan",
      "pincode": "384265",
      "quantity": 1373.00,
      "delivery_days": 330,
      "is_lumpsum": false
    }
  ]
}
```

---

### 2.3 Financials & EMD / Bank Guarantees Partition
* **Route:** `GET /api/v1/bids/{bid_no}/financials`
* **Description:** Returns financial sizing, earnest money deposit requirements, and performance security guidelines.

#### Example Request:
```http
GET /api/v1/bids/GEM_2025_B_6726924/financials HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "bid_no": "GEM/2025/B/6726924",
  "estimated_value": 2532000.00,
  "currency": "INR",
  "is_high_value": false,
  "emd": {
    "required": true,
    "amount": 75960.00,
    "percent_of_estimated_value": 3.00,
    "advisory_bank": "State Bank of India",
    "exemption_allowed_for_mse": true,
    "exemption_terms": "Under MSE category, only manufacturers for goods and service providers are eligible for exemption. Traders are excluded."
  },
  "epbg": {
    "required": true,
    "percent": 5.00,
    "advisory_bank": "State Bank of India",
    "duration_months": 12
  }
}
```

---

### 2.4 Mandatory Documents Required Partition
* **Route:** `GET /api/v1/bids/{bid_no}/documents`
* **Description:** Pre-bid document checklist outlining all mandatory uploads requested by the buyer.

#### Example Request:
```http
GET /api/v1/bids/GEM_2025_B_6726924/documents HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "bid_no": "GEM/2025/B/6726924",
  "show_docs_to_all_bidders": true,
  "mandatory_documents_count": 6,
  "required_documents": [
    "Past Performance Experience Certificate",
    "Bidder Financial Turnover (Last 3 Years)",
    "Certificate (Requested in ATC)",
    "OEM Authorization Certificate",
    "OEM Annual Turnover Certificate",
    "Additional Doc 1 (Requested in ATC)"
  ]
}
```

---

### 2.5 ATC AI Compliance Checklist Partition
* **Route:** `GET /api/v1/bids/{bid_no}/atc`
* **Description:** Returns the 8-domain structured compliance checklist analyzed by Gemini AI.

#### Example Request:
```http
GET /api/v1/bids/GEM_2025_B_6726924/atc HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "bid_no": "GEM/2025/B/6726924",
  "has_atc": true,
  "domains": {
    "ELIGIBILITY_AND_QUALIFICATION": [
      "The bidder must be an Indian Manufacturer or Authorized Distributor for imported items.",
      "Distributors of Indian OEMs shall not be allowed to participate."
    ],
    "PENALTIES_REJECTION_AND_LEGAL_TERMS": [
      "Liquidated Damages: 0.5% per week of delayed quantity up to a maximum deduction of 5%.",
      "Back out from tender will attract forfeiture of EMD and 1 year debarment."
    ],
    "SCOPE_DELIVERY_WARRANTY_AND_SUPPORT": [
      "Goods must carry minimum 5/6th of total shelf life at the time of delivery to consignees.",
      "Outer boxes must prominently display: FOR THE USE OF GOVT. OF GUJARAT. NOT FOR SALE."
    ]
  }
}
```

---

### 2.6 Physical Submissions Partition
* **Route:** `GET /api/v1/bids/{bid_no}/submissions`
* **Description:** Returns offline physical submissions (Demand drafts, lab samples, physical guarantees) that must be delivered to avoid disqualification.

#### Example Request:
```http
GET /api/v1/bids/GEM_2025_B_6726924/submissions HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "bid_no": "GEM/2025/B/6726924",
  "submissions_count": 1,
  "items": [
    {
      "item_name": "Physical Product Sample (100 units)",
      "deadline": "Within 7 working days of bid closure",
      "in_favor_of": "Managing Director, Gujarat Medical Services Corporation Limited",
      "payable_at": "Gandhinagar",
      "delivery_address": "Block-14, Dr. Jivraj Mehta Bhavan, Gandhinagar, Gujarat"
    }
  ]
}
```

---

## GROUP 3: Discovery & Filter Aggregations (Types, Organizations & Geography)

### 3.1 Bid Types Aggregation
* **Route:** `GET /api/v1/types`
* **Description:** Returns live aggregate tender counts and estimated budget values grouped by procurement bid type.

#### Example Request:
```http
GET /api/v1/types HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "total_active_bids": 61,
  "types": [
    {
      "type_name": "Product Bid/RAs",
      "category_label": "Product",
      "active_bids_count": 48,
      "total_estimated_value": 142500000.00
    },
    {
      "type_name": "Service Bid/RAs",
      "category_label": "Service",
      "active_bids_count": 9,
      "total_estimated_value": 38900000.00
    },
    {
      "type_name": "BOQ Bids",
      "category_label": "BOQ",
      "active_bids_count": 4,
      "total_estimated_value": 21300000.00
    }
  ]
}
```

---

### 3.2 Procuring Organizations Directory
* **Route:** `GET /api/v1/organizations`
* **Description:** Lists top procuring government organizations and their active tender counts.
* **Query Parameters:** `min_bids` (default: 1), `limit` (default: 50)

#### Example Request:
```http
GET /api/v1/organizations?min_bids=2 HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "total_organizations": 18,
  "organizations": [
    {
      "organisation_name": "Gujarat Medical Services Corporation Limited (gmscl)",
      "department_name": "Health & Family Welfare Department Gujarat",
      "state": "Gujarat",
      "active_bids_count": 14,
      "total_pipeline_value": 45200000.00
    },
    {
      "organisation_name": "Western Railway",
      "department_name": "Ministry of Railways",
      "state": "Central Government",
      "active_bids_count": 6,
      "total_pipeline_value": 28400000.00
    }
  ]
}
```

---

### 3.3 State & Geographic Slicing
* **Route:** `GET /api/v1/locations/states/{state_name}/bids`
* **Description:** Returns tenders published by or requiring delivery in a specific Indian state.

#### Example Request:
```http
GET /api/v1/locations/states/Gujarat/bids?limit=2 HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "state": "Gujarat",
  "active_tenders_count": 14,
  "bids": [
    {
      "bid_no": "GEM/2025/B/6726924",
      "organisation": "Gujarat Medical Services Corporation Limited",
      "title_item": "Centrifuge Tubes (V2) (Q3)",
      "estimated_value": 2532000.00,
      "end_datetime": "2026-11-17T18:00:00+05:30"
    }
  ]
}
```

---

### 3.4 Pincode & Delivery Logistics Explorer
* **Route:** `GET /api/v1/locations/pincode/{pincode}/bids`
* **Description:** Discovers tenders requiring freight delivery to a specific 6-digit postal code.

#### Example Request:
```http
GET /api/v1/locations/pincode/365601/bids HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "pincode": "365601",
  "city": "Amreli",
  "matching_tenders": 1,
  "bids": [
    {
      "bid_no": "GEM/2025/B/6726924",
      "organisation": "Gujarat Medical Services Corporation Limited",
      "delivery_address": "GMSCL-Ware House_Amreli, Near Civil Hospital, Amreli",
      "quantity": 255.00,
      "delivery_days": 330
    }
  ]
}
```

---

## GROUP 4: Search & AI Semantic Retrieval APIs

### 4.1 Natural Language Semantic Search (`pgvector`)
* **Route:** `POST /api/v1/search/semantic`
* **Description:** Takes natural language user intent, generates a 768-dimensional BGE embedding vector on the fly, and queries PostgreSQL's `gem_bid_chunks` via the HNSW cosine distance index in under 5 milliseconds.

#### Example Request:
```http
POST /api/v1/search/semantic HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "query": "Centrifuge tubes 15ml sterile for medical warehouse",
  "top_k": 3,
  "filter_state": "Gujarat"
}
```

#### Example Response:
```json
{
  "success": true,
  "query": "Centrifuge tubes 15ml sterile for medical warehouse",
  "retrieval_latency_ms": 3.42,
  "results_count": 3,
  "results": [
    {
      "bid_no": "GEM/2025/B/6726924",
      "chunk_type": "item",
      "similarity_score": 0.912,
      "distance": 0.088,
      "matching_text": "GeM Tender Summary & Metadata Card:\nBid Number: GEM/2025/B/6726924\nMinistry/State: Gujarat\nOrganisation: Gujarat Medical Services Corporation Limited\nItems / Categories:\n  - Centrifuge Tubes (V2) (Q3) (Qty: 5064)"
    },
    {
      "bid_no": "GEM/2025/B/6726924",
      "chunk_type": "compliance",
      "similarity_score": 0.845,
      "distance": 0.155,
      "matching_text": "ATC Compliance Checklist:\nScope & Warranty: Goods must carry minimum 5/6th shelf life at time of delivery."
    }
  ]
}
```

---

### 4.2 Fast Fuzzy Keyword Search (`pg_trgm`)
* **Route:** `GET /api/v1/search/keyword`
* **Description:** High-speed trigram search over item categories, departments, and tender titles.

#### Example Request:
```http
GET /api/v1/search/keyword?q=tubes HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "query": "tubes",
  "matches": [
    {
      "bid_no": "GEM/2025/B/6726924",
      "matched_category": "Centrifuge Tubes (V2) (Q3)",
      "organisation": "Gujarat Medical Services Corporation Limited",
      "quantity": 5064.00,
      "estimated_value": 2532000.00
    }
  ]
}
```

---

## GROUP 5: Document Storage & Streaming APIs (MinIO S3)

### 5.1 Presigned Tender PDF Download Link
* **Route:** `GET /api/v1/documents/{bid_no}/pdf`
* **Description:** Returns a secure, time-limited presigned S3 URL (valid for 15 minutes) for direct client streaming from MinIO without placing memory overhead on the API server.

#### Example Request:
```http
GET /api/v1/documents/GEM_2025_B_6726924/pdf HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "bid_no": "GEM/2025/B/6726924",
  "document_type": "bid_pdf",
  "expires_in_seconds": 900,
  "download_url": "http://localhost:9000/gem-tenders/bids/GEM_2025_B_6726924/bid.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin...&X-Amz-Signature=847a9..."
}
```

---

## GROUP 6: Asynchronous Operations & Worker Task APIs

### 6.1 Trigger Immediate Tender Scrape
* **Route:** `POST /api/v1/tasks/scrape-bid`
* **Description:** Enqueues an ad-hoc crawling task for a single bid into Celery's `scraping_queue`.

#### Example Request:
```http
POST /api/v1/tasks/scrape-bid HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "bid_no": "GEM/2026/B/8113926"
}
```

#### Example Response:
```json
{
  "success": true,
  "task_id": "7a35e802-99cf-4a11-b924-ce9f91a5db12",
  "status": "QUEUED",
  "queue": "scraping_queue",
  "message": "Crawl task dispatched for GEM/2026/B/8113926"
}
```

---

### 6.2 Check Celery Task Execution Status
* **Route:** `GET /api/v1/tasks/{task_id}`
* **Description:** Checks the real-time processing stage of any background job (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`).

#### Example Request:
```http
GET /api/v1/tasks/7a35e802-99cf-4a11-b924-ce9f91a5db12 HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "task_id": "7a35e802-99cf-4a11-b924-ce9f91a5db12",
  "status": "SUCCESS",
  "result": {
    "status": "completed",
    "bid_no": "GEM_2026_B_8113926",
    "has_atc": true,
    "chunks_indexed": 14
  }
}
```

---

## GROUP 7: Analytics & System Telemetry APIs

### 7.1 Overall System Health & Pipeline KPIs
* **Route:** `GET /api/v1/analytics/overview`
* **Description:** Real-time KPI counters aggregating total tenders, ongoing tenders, total pipeline value, and total units required.

#### Example Request:
```http
GET /api/v1/analytics/overview HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "metrics": {
    "total_tenders_scraped": 61,
    "active_ongoing_tenders": 58,
    "expired_tenders": 3,
    "total_estimated_pipeline_inr": 202700000.00,
    "total_items_procured": 413,
    "total_delivery_locations": 139,
    "average_emd_amount_inr": 68400.00
  }
}
```

---

### 7.2 AI & OCR Telemetry Audit
* **Route:** `GET /api/v1/analytics/ai-telemetry`
* **Description:** Aggregates total token consumption, Mistral OCR page count, and financial costs across Gemini AI runs.

#### Example Request:
```http
GET /api/v1/analytics/ai-telemetry HTTP/1.1
Host: localhost:8000
```

#### Example Response:
```json
{
  "success": true,
  "ai_telemetry": {
    "total_tenders_analyzed": 61,
    "total_input_tokens": 1245000,
    "total_output_tokens": 84200,
    "total_cost_usd": 0.4852,
    "total_cost_inr": 41.97,
    "average_cost_per_bid_inr": 0.68,
    "average_latency_seconds": 3.82
  }
}
```

---

## 🏆 Summary Matrix of All Endpoints

| Group | Method | Route | Description |
|---|---|---|---|
| **1. Master** | `GET` | `/api/v1/bids/{bid_no}` | **The Master Dossier:** All 10 tables + S3 URLs |
| **1. Master** | `GET` | `/api/v1/bids` | Filterable & paginated tender cards table |
| **1. Master** | `GET` | `/api/v1/bids/{bid_no}/raw` | Original unaltered JSON backup |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/header` | Timing, dates, remaining days, status |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/buyer` | Ministry, State, Department, Office |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/items` | Items list, quantities & JSONB specs |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/consignees`| Delivery addresses, officers, pincodes |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/financials`| Value, EMD amount, advisory bank |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/policy` | MSE preference, Startup relaxation |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/documents` | Required seller documents checklist |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/atc` | 8-domain AI compliance checklist |
| **2. Partitions**| `GET` | `/api/v1/bids/{bid_no}/submissions`| Hardcopy delivery deadlines & samples |
| **3. Discovery** | `GET` | `/api/v1/types` | Summary counts by bid type |
| **3. Discovery** | `GET` | `/api/v1/organizations` | Buyer organizations directory |
| **3. Discovery** | `GET` | `/api/v1/locations/states` | State-level procurement explorer |
| **3. Discovery** | `GET` | `/api/v1/locations/pincode/{pin}`| Freight & postal logistics explorer |
| **4. Search** | `GET` | `/api/v1/search/quick` | Instant auto-complete search |
| **4. Search** | `GET` | `/api/v1/search/keyword` | Trigram fuzzy keyword search |
| **4. Search** | `POST`| `/api/v1/search/semantic` | 768-dim BGE vector cosine similarity |
| **5. Documents** | `GET` | `/api/v1/documents/{bid_no}/pdf` | S3 presigned tender PDF download link |
| **6. Tasks** | `POST`| `/api/v1/tasks/scrape-bid` | Enqueue ad-hoc tender scraping job |
| **6. Tasks** | `GET` | `/api/v1/tasks/{task_id}` | Check status of background Celery job |
| **7. Analytics** | `GET` | `/api/v1/analytics/overview` | High-level system KPIs |
| **7. Analytics** | `GET` | `/api/v1/analytics/ai-telemetry` | Token consumption & AI cost audit |

---
*Maintained by GeMBridge Engineering Team.*