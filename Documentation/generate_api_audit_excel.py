"""
generate_api_audit_excel.py
Generates an executive-ready, professionally styled Excel workbook:
Documentation/API_PLAN_AND_IMPLEMENTATION_AUDIT.xlsx

Covers:
1. API Implementation Audit (Planned Plan vs. Darshan's Implementation)
2. Data Partitions & Frontend Mapping (P1 - P10)
3. Commands & Schedulers Execution Runbook (Starting, Stopping, --once, bid_type)
"""

import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def create_styled_workbook(output_path: str):
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Common Styles
    font_family = "Segoe UI"
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    
    sub_header_fill = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
    sub_header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")

    alt_row_fill = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")
    white_row_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    status_green_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    status_green_font = Font(name=font_family, size=9.5, bold=True, color="276A3C")

    status_blue_fill = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
    status_blue_font = Font(name=font_family, size=9.5, bold=True, color="1F4E78")

    status_amber_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    status_amber_font = Font(name=font_family, size=9.5, bold=True, color="B25E00")

    thin_border_side = Side(border_style="thin", color="E5E7EB")
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

    # -------------------------------------------------------------------------
    # TAB 1: API Implementation Audit
    # -------------------------------------------------------------------------
    ws1 = wb.create_sheet(title="API Implementation Audit")
    ws1.views.sheetView[0].showGridLines = True

    headers_1 = [
        "Group ID",
        "API Group Name",
        "Feature / Endpoint Name",
        "Method",
        "Planned Route (API Plan)",
        "Implemented Route (Darshan's Commit)",
        "Status",
        "Source File / Handler",
        "Key Request Parameters",
        "Response Model / Schema",
        "Architectural & Comparison Notes",
    ]

    ws1.append(headers_1)

    api_rows = [
        # System Health & Root
        ("G0", "System Health", "Gateway Root Welcome", "GET", "/", "/", "✅ Implemented & Active", 
         "gateway/routes/health.py::root", "None", "JSON Dictionary", 
         "Returns service title, version, documentation URLs (/docs, /redoc), and core endpoint directory."),
        ("G0", "System Health", "System Health Check", "GET", "/health", "/health", "✅ Implemented & Active", 
         "gateway/routes/health.py::health_check", "None", "HealthResponse", 
         "Actively verifies 3 subsystems: PostgreSQL 18 connection pool, Redis message broker ping, and MinIO S3 bucket. Returns HTTP 503 if degraded."),

        # Group 1: Master Suite
        ("G1", "Master & General", "Master Paginated Tender List", "GET", "/api/v1/bids", "/api/v1/bids", "✅ Implemented & Active", 
         "gateway/routes/bids.py::list_bids", "limit, offset, search, status, is_expired", "BidListResponse (items, total)", 
         "Sub-50ms query on PostgreSQL 'bids' table with indexed filters and total count. Supports live frontend card grids."),
        ("G1", "Master & General", "Master Tender Dossier (Path)", "GET", "/api/v1/bids/{bid_no}", "/api/v1/bids/{bid_id}", "✅ Implemented & Active", 
         "gateway/routes/bids.py::get_bid", "bid_id (path, supports '/' and '_')", "BidDetailResponse", 
         "The Master Dossier: Joins all 10 relational tables (scalars, items, consignees, schedules, atc_checklist, submissions, AI telemetry) in one ACID query."),
        ("G1", "Master & General", "Master Tender Dossier (Query)", "GET", "/api/v1/bids/{bid_no}", "/api/v1/bids/detail?bid_no=...", "✅ Implemented & Active", 
         "gateway/routes/bids.py::get_bid_by_query", "bid_no (query param)", "BidDetailResponse", 
         "Convenience query endpoint matching the master detail view for frontends that prefer query parameters."),
        ("G1", "Master & General", "Original Scraped Raw JSON", "GET", "/api/v1/bids/{bid_no}/raw", "Included in master detail (raw_data)", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py (db.get_bid_by_no)", "bid_no", "JSONB Document", 
         "The full unaltered raw scraped JSON is stored in PostgreSQL bids.raw_data and returned in master detail. Dedicated /raw slice endpoint planned."),

        # Group 2: Data Partitions
        ("G2", "Data Partitions", "Lifecycle & Identity (Header)", "GET", "/api/v1/bids/{bid_no}/header", "Included in master detail", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py", "bid_no", "BidDetailResponse (scalars)", 
         "Contains bid_no, ra_no, start/end dates, opening date, days remaining, status. Sub-route can be isolated for lightweight summary widgets."),
        ("G2", "Data Partitions", "Buyer & Governance", "GET", "/api/v1/bids/{bid_no}/buyer", "Included in master detail", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py", "bid_no", "Buyer fields in BidDetailResponse", 
         "Ministry, department, procuring organization, and office. Fully indexed and returned in master record."),
        ("G2", "Data Partitions", "Items & Technical Specs", "GET", "/api/v1/bids/{bid_no}/items", "Returned in BidDetailResponse.items", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py (bid_items)", "bid_no", "List[BidItemSchema]", 
         "Product catalogue items, quantities, and JSONB technical attribute specifications. Dedicated /items sub-route planned for supplier feeds."),
        ("G2", "Data Partitions", "Logistics & Consignees", "GET", "/api/v1/bids/{bid_no}/consignees", "Returned in BidDetailResponse.consignees", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py (bid_consignees)", "bid_no", "List[BidConsigneeSchema]", 
         "Consignee officer names, delivery addresses, cities, 6-digit pincodes, and delivery days. Dedicated /consignees route planned for logistics portals."),
        ("G2", "Data Partitions", "Financials & EMD Guarantees", "GET", "/api/v1/bids/{bid_no}/financials", "Returned in BidDetailResponse", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py", "bid_no", "Financial scalar fields", 
         "Estimated value, EMD requirement, EMD amount, advisory bank, and EPBG %. Dedicated /financials route planned for fintech/banking feeds."),
        ("G2", "Data Partitions", "Policy & Relaxations", "GET", "/api/v1/bids/{bid_no}/policy", "Returned in BidDetailResponse", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py", "bid_no", "Policy scalar fields", 
         "MSE purchase preference %, MSE relaxation flag, Startup exemption flag, Make in India (MII) preference."),
        ("G2", "Data Partitions", "Mandatory Required Documents", "GET", "/api/v1/bids/{bid_no}/documents", "Returned in BidDetailResponse.required_documents", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py (bids.required_documents)", "bid_no", "List[str]", 
         "Array of mandatory seller compliance certificates required by the buyer (e.g. Past Performance, Bidder Turnover, OEM Auth)."),
        ("G2", "Data Partitions", "ATC Compliance Checklist", "GET", "/api/v1/bids/{bid_no}/atc", "Returned in BidDetailResponse.atc_checklist", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py (bid_atc_checklist_items)", "bid_no", "Dict[str, List[str]]", 
         "Categorized compliance checklist generated by Gemini AI across 8 legal and operational domains."),
        ("G2", "Data Partitions", "Physical Offline Submissions", "GET", "/api/v1/bids/{bid_no}/submissions", "Returned in BidDetailResponse.physical_submissions", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py (bid_atc_physical_submissions)", "bid_no", "List[Dict]", 
         "Hardcopy instruments (Demand Drafts, lab samples, banker checks) with deadlines and payee authority details."),
        ("G2", "Data Partitions", "Evaluation Schedules", "GET", "/api/v1/bids/{bid_no}/schedules", "Returned in BidDetailResponse.evaluation_schedules", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py (bid_evaluation_schedules)", "bid_no", "List[Dict]", 
         "Multi-lot bidding schedules with grouped line items and estimated schedule values."),

        # Group 3: Discovery & Filter Aggregations
        ("G3", "Discovery & Filters", "Bid Types Aggregation", "GET", "/api/v1/types", "Planned discovery router", "📋 Planned Extension", 
         "gateway/routes/discovery.py (to be added)", "None", "TypesAggregationResponse", 
         "Aggregates total active tender counts and estimated budget values grouped by procurement bid type (Product, Service, BOQ, Custom)."),
        ("G3", "Discovery & Filters", "Procuring Organizations Directory", "GET", "/api/v1/organizations", "Partially via /api/v1/bids?search=...", "📋 Planned Extension", 
         "gateway/routes/discovery.py (to be added)", "min_bids, limit", "OrganizationsDirectoryResponse", 
         "Directory of top procuring central and state government organizations with active tender counts and pipeline INR values."),
        ("G3", "Discovery & Filters", "State-Level Procurement", "GET", "/api/v1/locations/states/{state}/bids", "Planned discovery router", "📋 Planned Extension", 
         "gateway/routes/discovery.py (to be added)", "state_name, limit", "StateBidsResponse", 
         "Returns tenders originating in or delivering to specific states (e.g. Gujarat, Maharashtra, Rajasthan)."),
        ("G3", "Discovery & Filters", "Pincode Logistics Explorer", "GET", "/api/v1/locations/pincode/{pin}/bids", "Planned discovery router", "📋 Planned Extension", 
         "gateway/routes/discovery.py (to be added)", "pincode", "PincodeBidsResponse", 
         "Discovers freight tenders requiring delivery to a specific 6-digit postal code based on bid_consignees index."),

        # Group 4: Search & AI Semantic Retrieval
        ("G4", "Search & AI", "Semantic RAG Search (pgvector)", "POST", "/api/v1/search/semantic", "/api/v1/bids/ask", "✅ Implemented & Active", 
         "gateway/routes/rag.py::ask_rag", "query, top_k, bid_id, synthesize_answer", "RagQueryResponse", 
         "Implemented by Darshan! Sub-5ms cosine similarity retrieval over PostgreSQL 18 gem_bid_chunks using 768-dim BGE embeddings + optional Gemini LLM answer synthesis."),
        ("G4", "Search & AI", "Trigram Fuzzy Keyword Search", "GET", "/api/v1/search/keyword", "Integrated in /api/v1/bids?search=...", "✅ Implemented & Active", 
         "gateway/routes/bids.py::list_bids", "search (query string)", "BidListResponse", 
         "Fuzzy text search matching bid numbers, organization names, and item categories in PostgreSQL."),

        # Group 5: Document Storage & Streaming (MinIO)
        ("G5", "Document Storage", "Presigned Tender PDF Link (Path)", "GET", "/api/v1/documents/{bid_no}/pdf", "/api/v1/bids/{bid_id}/pdf", "✅ Implemented & Active", 
         "gateway/routes/bids.py::get_bid_pdf", "bid_id", "HTTP 307 Redirect (Presigned S3 URL)", 
         "Implemented by Darshan! Generates secure 24-hour presigned MinIO S3 URL. Redirects client browser directly to MinIO without API server memory overhead."),
        ("G5", "Document Storage", "Presigned Tender PDF Link (Query)", "GET", "/api/v1/documents/{bid_no}/pdf", "/api/v1/bids/download-pdf?bid_no=...", "✅ Implemented & Active", 
         "gateway/routes/bids.py::get_bid_pdf_by_query", "bid_no (query param)", "HTTP 307 Redirect (Presigned S3 URL)", 
         "Convenience query endpoint for downloading tender PDFs with zero memory buffering."),

        # Group 6: Tasks & Crawler Orchestration
        ("G6", "Worker Tasks", "Trigger On-Demand Scraper", "POST", "/api/v1/tasks/scrape-bid", "/api/v1/bids/scrape-ondemand", "✅ Implemented & Active", 
         "gateway/routes/admin.py::trigger_ondemand_scrape", "bid_no (or category, target_count)", "TaskStatusResponse (HTTP 202)", 
         "Implemented by Darshan! Submits crawl task directly to Redis scraping_queue in 2ms. Supports single bid search or category crawling with custom count."),
        ("G6", "Worker Tasks", "Check Celery Task Status", "GET", "/api/v1/tasks/{task_id}", "/api/v1/tasks/{task_id}", "✅ Implemented & Active", 
         "gateway/routes/admin.py::get_task_status", "task_id (path param)", "TaskStatusResponse", 
         "Implemented by Darshan! Direct AsyncResult inspection of Celery task state (PENDING, STARTED, SUCCESS, FAILURE) and execution result payload."),

        # Group 7: Analytics & Telemetry
        ("G7", "Analytics & KPIs", "System Health & Pipeline KPIs", "GET", "/api/v1/analytics/overview", "Tracked in DB, planned dedicated route", "📋 Planned Extension", 
         "gateway/routes/analytics.py (to be added)", "None", "AnalyticsOverviewResponse", 
         "Aggregates total tenders scraped (61), ongoing active tenders, total pipeline INR value, item counts, and average EMD values."),
        ("G7", "Analytics & KPIs", "AI & OCR Telemetry Audit", "GET", "/api/v1/analytics/ai-telemetry", "Returned inside BidDetailResponse.ai_telemetry", "🔄 Covered in Master Payload", 
         "gateway/routes/bids.py (bids.ai_telemetry)", "None", "AITelemetryResponse", 
         "Tracks total token consumption, Gemini cost in USD/INR, and Mistral OCR page counts across pipeline runs."),
    ]

    for row in api_rows:
        ws1.append(row)

    # Style Tab 1
    for col_idx in range(1, len(headers_1) + 1):
        cell = ws1.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws1.row_dimensions[1].height = 28

    for row_idx in range(2, len(api_rows) + 2):
        ws1.row_dimensions[row_idx].height = 22
        is_alt = (row_idx % 2 == 0)
        status_val = ws1.cell(row=row_idx, column=7).value

        for col_idx in range(1, len(headers_1) + 1):
            c = ws1.cell(row=row_idx, column=col_idx)
            c.border = cell_border
            c.font = Font(name=font_family, size=9.5)
            c.fill = alt_row_fill if is_alt else white_row_fill

            # Alignments
            if col_idx in (1, 4):  # Group ID, Method
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 7:     # Status column
                c.alignment = Alignment(horizontal="center", vertical="center")
                if "Implemented & Active" in status_val:
                    c.fill = status_green_fill
                    c.font = status_green_font
                elif "Covered in Master" in status_val:
                    c.fill = status_blue_fill
                    c.font = status_blue_font
                else:
                    c.fill = status_amber_fill
                    c.font = status_amber_font
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

    # -------------------------------------------------------------------------
    # TAB 2: Data Partitions & Frontend Map
    # -------------------------------------------------------------------------
    ws2 = wb.create_sheet(title="Data Partitions & Frontend Map")
    ws2.views.sheetView[0].showGridLines = True

    headers_2 = [
        "Partition ID",
        "Partition Module Name",
        "Database Source Table",
        "Planned Sub-Route",
        "Current Exposure in Darshan's Code",
        "Target Frontend Component / B2B Commercial Feed",
        "Next Implementation Step",
    ]

    ws2.append(headers_2)

    partitions_data = [
        ("P1", "Lifecycle & Identity", "bids (scalar columns)", "/api/v1/bids/{bid_no}/header", 
         "Exposed in GET /api/v1/bids/{bid_id} (id, bid_no, ra_no, start/end dates, remaining days)", 
         "Tender Header Card, Countdown Timer, Status Badge", "Add isolated /header sub-route for fast card refreshes"),
        ("P2", "Buyer & Governance", "bids (ministry, dept, org)", "/api/v1/bids/{bid_no}/buyer", 
         "Exposed in GET /api/v1/bids/{bid_id} (ministry_state_name, department_name, organisation_name)", 
         "Buyer Info Sidebar, Ministry & Department Breadcrumbs", "Add isolated /buyer sub-route"),
        ("P3", "Items & Specifications", "bid_items (with specifications JSONB)", "/api/v1/bids/{bid_no}/items", 
         "Exposed in GET /api/v1/bids/{bid_id} under 'items' array with full JSONB specs", 
         "Product Specs Tab, Supplier Match Feed, OEM Quoting Tool", "Add isolated /items sub-route with category filtering"),
        ("P4", "Logistics & Consignees", "bid_consignees (officer, address, pincode)", "/api/v1/bids/{bid_no}/consignees", 
         "Exposed in GET /api/v1/bids/{bid_id} under 'consignees' array", 
         "Consignee Map/Table Tab, Logistics Freight Quote Feed, Pincode Routing", "Add isolated /consignees sub-route"),
        ("P5", "Financials & Bonds", "bids (estimated_value, emd_amount, epbg)", "/api/v1/bids/{bid_no}/financials", 
         "Exposed in GET /api/v1/bids/{bid_id} root financial fields", 
         "Financial Overview Tab, Fintech Lending & Bank Guarantee (BG) Feed", "Add isolated /financials sub-route with currency conversions"),
        ("P6", "Policy Preferences", "bids (mse_preference, startup_relaxation)", "/api/v1/bids/{bid_no}/policy", 
         "Exposed in GET /api/v1/bids/{bid_id} policy flags", 
         "Eligibility Modal, MSME & Startup Qualification Calculator", "Add isolated /policy sub-route"),
        ("P7", "Mandatory Documents", "bids (required_documents TEXT[])", "/api/v1/bids/{bid_no}/documents", 
         "Exposed in GET /api/v1/bids/{bid_id} under 'required_documents' array", 
         "Pre-Bid Document Checklist, Bidder Readiness Stepper", "Add isolated /documents sub-route"),
        ("P8", "ATC Compliance Clauses", "bid_atc_checklist_items (8 domains)", "/api/v1/bids/{bid_no}/atc", 
         "Exposed in GET /api/v1/bids/{bid_id} under 'atc_checklist' grouped by domain", 
         "Compliance Checklist Tab, Legal Risk Audit, Penalty Warning Alerts", "Add isolated /atc sub-route with domain query filters"),
        ("P9", "Physical Submissions", "bid_atc_physical_submissions", "/api/v1/bids/{bid_no}/submissions", 
         "Exposed in GET /api/v1/bids/{bid_id} under 'physical_submissions' array", 
         "Offline Submission Tracker, Sample Courier Alerts, DD Payment Details", "Add isolated /submissions sub-route"),
        ("P10", "Evaluation Schedules", "bid_evaluation_schedules", "/api/v1/bids/{bid_no}/schedules", 
         "Exposed in GET /api/v1/bids/{bid_id} under 'evaluation_schedules' array", 
         "Multi-Lot Bidding Matrix, Segmented Quoting Interface", "Add isolated /schedules sub-route"),
    ]

    for row in partitions_data:
        ws2.append(row)

    for col_idx in range(1, len(headers_2) + 1):
        cell = ws2.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws2.row_dimensions[1].height = 28

    for row_idx in range(2, len(partitions_data) + 2):
        ws2.row_dimensions[row_idx].height = 24
        is_alt = (row_idx % 2 == 0)

        for col_idx in range(1, len(headers_2) + 1):
            c = ws2.cell(row=row_idx, column=col_idx)
            c.border = cell_border
            c.font = Font(name=font_family, size=9.5)
            c.fill = alt_row_fill if is_alt else white_row_fill

            if col_idx == 1:
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.font = Font(name=font_family, size=9.5, bold=True)
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

    # -------------------------------------------------------------------------
    # TAB 3: Commands & Schedulers Runbook
    # -------------------------------------------------------------------------
    ws3 = wb.create_sheet(title="Commands & Schedulers Guide")
    ws3.views.sheetView[0].showGridLines = True

    headers_3 = [
        "Operation Scenario",
        "Execution Method",
        "Exact Command / Payload",
        "Underlying Celery / Code Mechanism",
        "Process Control: Start & Stop Behavior",
    ]

    ws3.append(headers_3)

    runbook_data = [
        ("Start 3 Worker Queues (Local)", "PowerShell Script", 
         ".\\start_workers.ps1", 
         "Spawns 3 dedicated Celery processes in Solo mode (-P solo) on Windows: scraping_queue, document_queue, and atc_rag_queue.", 
         "START: Opens separate PowerShell worker windows.\nSTOP: Run '.\\start_workers.ps1 -Stop' to kill all Celery worker processes via Win32 WMI."),

        ("Start Workers + Periodic Scheduler", "PowerShell Script", 
         ".\\start_workers.ps1 -WithBeat", 
         "Spawns the 3 queue workers plus Celery Beat periodic clock daemon using tasks/beat_schedule.py.", 
         "START: Starts workers + Beat clock daemon.\nBEAT CYCLE: Automatically fires tasks.tier1_scraper.crawl_all_categories every 30 minutes.\nSTOP: Run '.\\start_workers.ps1 -Stop'."),

        ("Stop All Running Workers & Schedulers", "PowerShell Script", 
         ".\\start_workers.ps1 -Stop", 
         "Queries Win32_Process for 'tasks.celery_app' and forces immediate termination of all worker and beat PIDs.", 
         "Immediate termination of all background Python and Celery processes. Clean exit."),

        ("Run One-Shot Crawl via REST API (Single Tender)", "REST API (FastAPI Gateway)", 
         "POST /api/v1/bids/scrape-ondemand\nPayload: {\"bid_no\": \"GEM/2026/B/8113926\"}", 
         "Calls tasks.tier1_scraper.scrape_single_bid.delay(). Searches specifically for that tender card, downloads PDF, and pipelines to Tier 2 and Tier 3.", 
         "START: Enqueues in ~2ms, returns Celery task_id.\nEXECUTION: Executes once for that single bid number.\nSTOP: Finishes automatically upon completing the 3 worker tiers."),

        ("Run One-Shot Crawl via REST API (By Bid Type)", "REST API (FastAPI Gateway)", 
         "POST /api/v1/bids/scrape-ondemand\nPayload: {\"category\": \"Product Bid/RAs\", \"target_count\": 5}", 
         "Calls tasks.tier1_scraper.scrape_category.delay(bid_type='Product Bid/RAs', target_count=5). Applies the category filter on GeM portal.", 
         "START: Enqueues in ~2ms, returns task_id.\nEXECUTION: Crawls until 5 un-seen tender cards are processed.\nSTOP: Terminates automatically when target_count is reached."),

        ("Check Task Status via REST API", "REST API (FastAPI Gateway)", 
         "GET /api/v1/tasks/{task_id}", 
         "gateway/routes/admin.py::get_task_status inspects Celery AsyncResult.", 
         "Returns real-time status: PENDING -> STARTED -> SUCCESS (with tender ID & chunk count) or FAILURE."),

        ("Run One-Shot Crawl via Python CLI (Single Tender)", "Python Command", 
         ".\\venv\\Scripts\\python -c \"from tasks.tier1_scraper import scrape_single_bid; print(scrape_single_bid('GEM/2026/B/8113926'))\"", 
         "Direct synchronous invocation of the crawler function without requiring Celery daemon.", 
         "Runs directly in foreground. Crawls the target bid, streams to MinIO, enqueues Tier 2, and exits cleanly."),

        ("Run One-Shot Crawl via Python CLI (By Bid Type)", "Python Command", 
         ".\\venv\\Scripts\\python -c \"from tasks.tier1_scraper import scrape_category; print(scrape_category('Product Bid/RAs', target_count=2))\"", 
         "Direct synchronous invocation of category crawler.", 
         "Opens browser, selects category filter 'Product Bid/RAs', downloads up to 2 un-seen tenders, closes browser, and exits."),

        ("Launch FastAPI REST Gateway (Local)", "Uvicorn ASGI Server", 
         ".\\venv\\Scripts\\uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload", 
         "Launches FastAPI Gateway with PostgreSQL connection pool (minconn=2, maxconn=10), MinIO S3 integration, and telemetry middleware.", 
         "Runs on http://localhost:8000. Interactive docs available at /docs and /redoc. Stop with Ctrl+C."),

        ("Run Production Stack (Docker / Dokploy)", "Docker Compose (VPS)", 
         "docker compose -f docker-compose.prod.yml up -d", 
         "Spins up the full 7-service enterprise stack: redis, worker-scraper, worker-document, worker-atc, celery-beat, fastapi-gateway, and flower.", 
         "START: Runs continuously in background with healthchecks and restart policies.\nSTOP: 'docker compose -f docker-compose.prod.yml down'."),
    ]

    for row in runbook_data:
        ws3.append(row)

    for col_idx in range(1, len(headers_3) + 1):
        cell = ws3.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws3.row_dimensions[1].height = 28

    for row_idx in range(2, len(runbook_data) + 2):
        ws3.row_dimensions[row_idx].height = 45
        is_alt = (row_idx % 2 == 0)

        for col_idx in range(1, len(headers_3) + 1):
            c = ws3.cell(row=row_idx, column=col_idx)
            c.border = cell_border
            c.font = Font(name=font_family, size=9.5)
            c.fill = alt_row_fill if is_alt else white_row_fill

            if col_idx in (1, 2):
                c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                if col_idx == 1:
                    c.font = Font(name=font_family, size=9.5, bold=True)
            elif col_idx == 3:
                c.font = Font(name="Consolas", size=9, color="1E293B")
                c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            else:
                c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # -------------------------------------------------------------------------
    # Auto-adjust column widths across all sheets
    # -------------------------------------------------------------------------
    for ws in [ws1, ws2, ws3]:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or "")
                # ignore multi-line length explosions
                first_line = val_str.split("\n")[0]
                if len(first_line) > max_len:
                    max_len = len(first_line)
            # clamp width
            ws.column_dimensions[col_letter].width = max(12, min(max_len + 4, 45))

    # Fine-tune specific column widths for best aesthetic readability
    ws1.column_dimensions["A"].width = 12
    ws1.column_dimensions["B"].width = 22
    ws1.column_dimensions["C"].width = 30
    ws1.column_dimensions["D"].width = 10
    ws1.column_dimensions["E"].width = 32
    ws1.column_dimensions["F"].width = 35
    ws1.column_dimensions["G"].width = 28
    ws1.column_dimensions["H"].width = 38
    ws1.column_dimensions["I"].width = 35
    ws1.column_dimensions["J"].width = 28
    ws1.column_dimensions["K"].width = 50

    ws2.column_dimensions["A"].width = 14
    ws2.column_dimensions["B"].width = 28
    ws2.column_dimensions["C"].width = 35
    ws2.column_dimensions["D"].width = 32
    ws2.column_dimensions["E"].width = 45
    ws2.column_dimensions["F"].width = 45
    ws2.column_dimensions["G"].width = 45

    ws3.column_dimensions["A"].width = 35
    ws3.column_dimensions["B"].width = 24
    ws3.column_dimensions["C"].width = 45
    ws3.column_dimensions["D"].width = 45
    ws3.column_dimensions["E"].width = 45

    # Save
    wb.save(output_path)
    print(f"Successfully generated Excel workbook: {output_path}")

if __name__ == "__main__":
    out_dir = r"c:\Projects\GeM\Scrapper & RAG Pipeline\Documentation"
    out_file = os.path.join(out_dir, "API_PLAN_AND_IMPLEMENTATION_AUDIT.xlsx")
    create_styled_workbook(out_file)
