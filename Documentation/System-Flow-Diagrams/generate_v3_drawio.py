"""
generate_v3_drawio.py
Generates the comprehensive GeM-Bridge-v3.drawio file
matching the diagrams.net / draw.io XML schema with embedded Mermaid definitions.
"""

import os
import xml.sax.saxutils as saxutils

def generate_v3_drawio(out_path: str):
    mermaid_code = """flowchart TD
    subgraph CLIENTS ["1. Client & Integration Layer"]
        WEB["React / Next.js Web App"]
        MOBILE["Mobile Applications"]
        B2B_CLIENTS["B2B Enterprise Consumers"]
        SWAGGER_UI["Interactive Swagger UI (/docs)"]
    end

    subgraph GATEWAY ["2. REST API Gateway (FastAPI Port 8000)"]
        SECURITY["CORS & Request Security Middleware"]
        TELEMETRY_LATENCY["Latency & Telemetry Middleware (X-Process-Time-Ms)"]
        
        subgraph ROUTE_MODULES ["Gateway Endpoint Modules (gateway/routes/)"]
            R_BIDS["routes/bids.py (Master Dossier & 10 Partition Slices)"]
            R_SEARCH["routes/search.py (Prefix, Trigram & pgvector Semantic)"]
            R_DOCS["routes/documents.py (MinIO Presigned PDF Redirect)"]
            R_DISCOVERY["routes/discovery.py (Aggregations by Type & Org)"]
            R_TASKS["routes/tasks.py (Async Scraper Triggers & Task Status)"]
            R_ANALYTICS["routes/analytics.py (System KPIs & Token Costs)"]
            R_HEALTH["routes/health.py (Postgres, Redis, MinIO Health)"]
        end
    end

    subgraph BROKER ["3. Message Broker & Distributed Queues (Redis 7)"]
        CELERY_BEAT["Celery Beat Periodic Scheduler (Every 30 Mins)"]
        Q_SCRAPING["Redis Queue: scraping_queue"]
        Q_DOCUMENT["Redis Queue: document_queue"]
        Q_ATC["Redis Queue: atc_rag_queue"]
        DEDUP_STORE["Redis Deduplication Store (gem:seen:{bid_no} - 7 Days TTL)"]
    end

    subgraph WORKERS ["4. Distributed 3-Tier Queue Worker Layer"]
        subgraph TIER1 ["Tier 1: Playwright Web Scraper Worker"]
            CHROMIUM["Playwright Chromium Stealth (2GB /dev/shm)"]
            INMEM_SCRAPE["Zero-Disk In-Memory PDF Capture"]
        end

        subgraph TIER2 ["Tier 2: Document Processing & OCR Worker"]
            PYMUPDF_SLICE["PyMuPDF Front-Page Slicer (<0.2s In-Memory)"]
            MISTRAL_OCR["Mistral Cloud OCR (Scanned Annexures Fallback)"]
            NORMALIZER_ENGINE["Core Normalizer & Validator (ACID Schema)"]
        end

        subgraph TIER3 ["Tier 3: ATC Compliance & AI Vector Worker"]
            GEMINI_ENGINE["Google Gemini 2.5 Flash (8-Domain Legal ATC Analyzer)"]
            BGE_EMBEDDER["BAAI/bge-base-en-v1.5 (768-dim Dense Vector Engine)"]
        end
    end

    subgraph PERSISTENCE ["5. Enterprise Hybrid Persistence Layer"]
        subgraph S3_STORAGE ["MinIO S3 Object Storage (Bucket: gem-tenders)"]
            OBJ_PDF["bids/{bid_no}/bid.pdf (Raw Bid PDF)"]
            OBJ_MD["bids/{bid_no}/document.md (Parsed Markdown)"]
            OBJ_META["bids/{bid_no}/metadata.json (Normalized JSON Schema)"]
            OBJ_ATC["bids/{bid_no}/atc_compliance.json (Compliance Checklist)"]
        end

        subgraph POSTGRES_DB ["PostgreSQL 18 Hybrid Relational & Vector Database"]
            PG_BIDS[("bids (Master Header, Dates, Scalars, raw_data JSONB)")]
            PG_ITEMS[("bid_items (Line Items with specifications JSONB)")]
            PG_CONSIGNEES[("bid_consignees (Delivery Addresses, Officers, Pincodes)")]
            PG_SCHEDULES[("bid_evaluation_schedules (Multi-Lot Lots & Matrices)")]
            PG_TERMS[("bid_terms (Payment, Delivery, Warranty Clauses)")]
            PG_HYPERLINKS[("bid_hyperlinks (Extracted Document URIs)")]
            PG_ATC[("bid_atc_checklist_items (8-Domain Categorized Clauses)")]
            PG_SUBMISSIONS[("bid_atc_physical_submissions (Demand Drafts & Samples)")]
            PG_TELEMETRY[("bid_atc_analyses (AI Token Telemetry & Mistral Costs)")]
            PG_CHUNKS[("gem_bid_chunks (768-dim Vectors + HNSW Cosine Index)")]
        end
    end

    %% Edge Connections
    WEB & MOBILE & B2B_CLIENTS & SWAGGER_UI --> SECURITY --> TELEMETRY_LATENCY --> ROUTE_MODULES
    R_BIDS --> PG_BIDS & PG_ITEMS & PG_CONSIGNEES
    R_SEARCH --> PG_CHUNKS
    R_DOCS -->|Generate 24h Presigned URL| OBJ_PDF
    R_TASKS -->|Dispatch delay()| Q_SCRAPING
    R_HEALTH --> PG_BIDS & BROKER & S3_STORAGE

    CELERY_BEAT -->|Cron Category Sweep| Q_SCRAPING
    Q_SCRAPING --> CHROMIUM --> INMEM_SCRAPE
    INMEM_SCRAPE -->|Deduplication Check| DEDUP_STORE
    INMEM_SCRAPE -->|Stream PDF Bytes| OBJ_PDF
    INMEM_SCRAPE -->|Enqueue process_document| Q_DOCUMENT

    Q_DOCUMENT --> PYMUPDF_SLICE
    OBJ_PDF -->|Stream into Memory| PYMUPDF_SLICE
    PYMUPDF_SLICE -->|If Scanned| MISTRAL_OCR
    PYMUPDF_SLICE & MISTRAL_OCR --> NORMALIZER_ENGINE
    NORMALIZER_ENGINE -->|Upload Artifacts| OBJ_MD & OBJ_META
    NORMALIZER_ENGINE -->|ACID Multi-Table Upsert| PG_BIDS & PG_ITEMS & PG_CONSIGNEES & PG_SCHEDULES & PG_TERMS
    NORMALIZER_ENGINE -->|Enqueue process_atc_and_embed| Q_ATC

    Q_ATC --> GEMINI_ENGINE
    OBJ_META -->|Legal Boundary Context| GEMINI_ENGINE
    GEMINI_ENGINE -->|Populate 8 Domains| PG_ATC & PG_SUBMISSIONS & PG_TELEMETRY
    GEMINI_ENGINE -->|Upload Checklist| OBJ_ATC
    GEMINI_ENGINE --> BGE_EMBEDDER
    BGE_EMBEDDER -->|Bulk Insert Chunks| PG_CHUNKS"""

    # Escape for XML and draw.io UserObject attribute
    escaped_mermaid = saxutils.escape(mermaid_code).replace('"', '&quot;').replace('\n', '&#xa;')

    xml_content = f"""<mxfile host="app.diagrams.net">
  <diagram name="GeMBridge-v3-Architecture" id="GeMBridge_v3_Enterprise_Architecture">
    <mxGraphModel grid="1" page="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" pageScale="1" pageWidth="1600" pageHeight="2200" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        
        <!-- Embedded Mermaid Engine Layer -->
        <UserObject label="" mermaidData="{{&#xa;  &quot;data&quot;: &quot;{escaped_mermaid}&quot;,&#xa;  &quot;config&quot;: null,&#xa;  &quot;version&quot;: &quot;12&quot;&#xa;}}" id="v3_mermaid_container">
          <mxCell connectable="0" parent="1" style="group;transparentBounds=1;editIcon=1;lockedGroup=0;groupPadding=10;" vertex="1">
            <mxGeometry as="geometry" />
          </mxCell>
        </UserObject>

        <!-- Visual High-Level Containers -->
        <!-- Layer 1: Client & Integration Layer -->
        <mxCell id="box_layer1" value="1. CLIENT &amp; INTEGRATION LAYER" parent="1" style="rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fontSize=15;fillColor=#EFF6FF;strokeColor=#3B82F6;strokeWidth=2;fontColor=#1E3A8A;spacingTop=10;" vertex="1">
          <mxGeometry x="80" y="40" width="1440" height="130" as="geometry" />
        </mxCell>
        <mxCell id="node_web" value="React / Next.js Web App&#xa;(Port 3000)" parent="box_layer1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#2563EB;strokeWidth=1.5;fontStyle=1;fontSize=12;" vertex="1">
          <mxGeometry x="50" y="50" width="260" height="55" as="geometry" />
        </mxCell>
        <mxCell id="node_mobile" value="Mobile Apps &amp; Notifications&#xa;(iOS / Android)" parent="box_layer1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#2563EB;strokeWidth=1.5;fontStyle=1;fontSize=12;" vertex="1">
          <mxGeometry x="380" y="50" width="260" height="55" as="geometry" />
        </mxCell>
        <mxCell id="node_b2b" value="B2B Enterprise Data Feeds&#xa;(Commercial Webhook Feeds)" parent="box_layer1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#2563EB;strokeWidth=1.5;fontStyle=1;fontSize=12;" vertex="1">
          <mxGeometry x="710" y="50" width="280" height="55" as="geometry" />
        </mxCell>
        <mxCell id="node_docs" value="Interactive Swagger &amp; ReDoc&#xa;(/docs &amp; /redoc)" parent="box_layer1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#2563EB;strokeWidth=1.5;fontStyle=1;fontSize=12;" vertex="1">
          <mxGeometry x="1060" y="50" width="280" height="55" as="geometry" />
        </mxCell>

        <!-- Layer 2: FastAPI REST Gateway Layer -->
        <mxCell id="box_layer2" value="2. REST API GATEWAY LAYER (FastAPI Port 8000)" parent="1" style="rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fontSize=15;fillColor=#F0FDF4;strokeColor=#22C55E;strokeWidth=2;fontColor=#14532D;spacingTop=10;" vertex="1">
          <mxGeometry x="80" y="220" width="1440" height="210" as="geometry" />
        </mxCell>
        <mxCell id="gw_mw" value="Middleware Engine: CORS Validation | Latency Telemetry (X-Process-Time-Ms) | Lifespan DB Pool Manager" parent="box_layer2" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DCFCE7;strokeColor=#16A34A;strokeWidth=1;fontSize=11;fontStyle=2;" vertex="1">
          <mxGeometry x="50" y="45" width="1340" height="35" as="geometry" />
        </mxCell>
        <mxCell id="r_bids" value="/api/v1/bids&#xa;(Master Dossier &amp; 10 Partitions)" parent="box_layer2" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#16A34A;strokeWidth=1.5;fontSize=11;fontStyle=1;" vertex="1">
          <mxGeometry x="50" y="100" width="200" height="85" as="geometry" />
        </mxCell>
        <mxCell id="r_search" value="/api/v1/search&#xa;(Prefix, Trigram &amp; pgvector)" parent="box_layer2" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#16A34A;strokeWidth=1.5;fontSize=11;fontStyle=1;" vertex="1">
          <mxGeometry x="280" y="100" width="200" height="85" as="geometry" />
        </mxCell>
        <mxCell id="r_docs" value="/api/v1/documents&#xa;(MinIO S3 Presigned Streaming)" parent="box_layer2" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#16A34A;strokeWidth=1.5;fontSize=11;fontStyle=1;" vertex="1">
          <mxGeometry x="510" y="100" width="200" height="85" as="geometry" />
        </mxCell>
        <mxCell id="r_disc" value="/api/v1/discovery&#xa;(Types, Ministries, Depts)" parent="box_layer2" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#16A34A;strokeWidth=1.5;fontSize=11;fontStyle=1;" vertex="1">
          <mxGeometry x="740" y="100" width="200" height="85" as="geometry" />
        </mxCell>
        <mxCell id="r_tasks" value="/api/v1/tasks&#xa;(Async Scrape Enqueue &amp; Poll)" parent="box_layer2" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#16A34A;strokeWidth=1.5;fontSize=11;fontStyle=1;" vertex="1">
          <mxGeometry x="970" y="100" width="200" height="85" as="geometry" />
        </mxCell>
        <mxCell id="r_analytics" value="/api/v1/analytics &amp; /health&#xa;(System Health, KPIs &amp; Costs)" parent="box_layer2" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#16A34A;strokeWidth=1.5;fontSize=11;fontStyle=1;" vertex="1">
          <mxGeometry x="1190" y="100" width="200" height="85" as="geometry" />
        </mxCell>

        <!-- Layer 3: Message Broker & Distributed Queues -->
        <mxCell id="box_layer3" value="3. MESSAGE BROKER &amp; DISTRIBUTED QUEUES (Redis 7)" parent="1" style="rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fontSize=15;fillColor=#FEF2F2;strokeColor=#EF4444;strokeWidth=2;fontColor=#991B1B;spacingTop=10;" vertex="1">
          <mxGeometry x="80" y="480" width="1440" height="150" as="geometry" />
        </mxCell>
        <mxCell id="q_beat" value="Celery Beat Scheduler&#xa;(Periodic Cron: Every 30 Mins)" parent="box_layer3" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FEE2E2;strokeColor=#DC2626;strokeWidth=1.5;fontStyle=1;fontSize=12;" vertex="1">
          <mxGeometry x="50" y="55" width="270" height="65" as="geometry" />
        </mxCell>
        <mxCell id="q_scrape" value="Queue: scraping_queue&#xa;(Playwright Web Crawler)" parent="box_layer3" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#DC2626;strokeWidth=1.5;fontStyle=1;fontSize=12;" vertex="1">
          <mxGeometry x="370" y="55" width="260" height="65" as="geometry" />
        </mxCell>
        <mxCell id="q_doc" value="Queue: document_queue&#xa;(PyMuPDF, OCR &amp; Normalizer)" parent="box_layer3" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#DC2626;strokeWidth=1.5;fontStyle=1;fontSize=12;" vertex="1">
          <mxGeometry x="680" y="55" width="260" height="65" as="geometry" />
        </mxCell>
        <mxCell id="q_atc" value="Queue: atc_rag_queue&#xa;(Gemini ATC &amp; pgvector)" parent="box_layer3" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#DC2626;strokeWidth=1.5;fontStyle=1;fontSize=12;" vertex="1">
          <mxGeometry x="990" y="55" width="260" height="65" as="geometry" />
        </mxCell>
        <mxCell id="q_dedup" value="Deduplication&#xa;gem:seen:{id}" parent="box_layer3" style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=10;fillColor=#FFFFFF;strokeColor=#DC2626;strokeWidth=1;fontSize=10;" vertex="1">
          <mxGeometry x="1300" y="45" width="90" height="85" as="geometry" />
        </mxCell>

        <!-- Layer 4: 3-Tier Distributed Queue Worker Layer -->
        <mxCell id="box_layer4" value="4. DISTRIBUTED 3-TIER QUEUE WORKER LAYER" parent="1" style="rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fontSize=15;fillColor=#FAF5FF;strokeColor=#A855F7;strokeWidth=2;fontColor=#581C87;spacingTop=10;" vertex="1">
          <mxGeometry x="80" y="680" width="1440" height="240" as="geometry" />
        </mxCell>
        <mxCell id="w_tier1" value="TIER 1: Web Scraper Worker&#xa;(Playwright Chromium Stealth | 2GB /dev/shm)&#xa;&#xa;• Bypasses anti-bot rate limits with randomized jitter&#xa;• Captures bid and RA tender PDFs directly in-memory&#xa;• Streams raw PDF bytes to MinIO S3 (Zero local disk)" parent="box_layer4" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#9333EA;strokeWidth=1.5;verticalAlign=top;align=left;spacing=12;fontSize=11;fontStyle=0;" vertex="1">
          <mxGeometry x="50" y="50" width="410" height="160" as="geometry" />
        </mxCell>
        <mxCell id="w_tier2" value="TIER 2: Document Processing Worker&#xa;(PyMuPDF In-Memory Slicing &amp; Mistral Cloud OCR)&#xa;&#xa;• Selective front-page slicing in &lt;0.2s without local disk&#xa;• Mistral Cloud OCR fallback on scanned image annexures&#xa;• Cleanses financials (Lakhs/Crores) and validates ISO timestamps&#xa;• Executes ACID relational multi-table upsert into PostgreSQL" parent="box_layer4" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#9333EA;strokeWidth=1.5;verticalAlign=top;align=left;spacing=12;fontSize=11;fontStyle=0;" vertex="1">
          <mxGeometry x="510" y="50" width="420" height="160" as="geometry" />
        </mxCell>
        <mxCell id="w_tier3" value="TIER 3: ATC Compliance &amp; Vector Worker&#xa;(Google Gemini 2.5 Flash &amp; BAAI/bge-base-en-v1.5)&#xa;&#xa;• Extracts 8 legal compliance domains (LD, warranties, exemptions)&#xa;• Extracts offline hardcopy submissions (Demand Drafts, samples)&#xa;• Chunks text into Item, Compliance &amp; General PDF passages&#xa;• Generates 768-dim embeddings into PostgreSQL HNSW cosine index" parent="box_layer4" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#9333EA;strokeWidth=1.5;verticalAlign=top;align=left;spacing=12;fontSize=11;fontStyle=0;" vertex="1">
          <mxGeometry x="980" y="50" width="410" height="160" as="geometry" />
        </mxCell>

        <!-- Layer 5: Enterprise Persistence Layer -->
        <mxCell id="box_layer5" value="5. ENTERPRISE HYBRID PERSISTENCE LAYER (MinIO S3 + PostgreSQL 18)" parent="1" style="rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fontSize=15;fillColor=#FFFBEB;strokeColor=#F59E0B;strokeWidth=2;fontColor=#78350F;spacingTop=10;" vertex="1">
          <mxGeometry x="80" y="970" width="1440" height="340" as="geometry" />
        </mxCell>
        
        <!-- MinIO S3 -->
        <mxCell id="box_s3" value="MinIO S3 Object Storage (Bucket: gem-tenders)" parent="box_layer5" style="rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fontSize=13;fillColor=#FEF3C7;strokeColor=#D97706;strokeWidth=1.5;fontColor=#92400E;spacingTop=8;" vertex="1">
          <mxGeometry x="50" y="50" width="530" height="260" as="geometry" />
        </mxCell>
        <mxCell id="s3_pdf" value="bids/{{bid_no}}/bid.pdf&#xa;(Raw PDF Document Stream)" parent="box_s3" style="shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;fillColor=#FFFFFF;strokeColor=#D97706;fontSize=10;fontStyle=1;" vertex="1">
          <mxGeometry x="30" y="50" width="200" height="80" as="geometry" />
        </mxCell>
        <mxCell id="s3_md" value="bids/{{bid_no}}/document.md&#xa;(Parsed Markdown Text)" parent="box_s3" style="shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;fillColor=#FFFFFF;strokeColor=#D97706;fontSize=10;fontStyle=1;" vertex="1">
          <mxGeometry x="290" y="50" width="200" height="80" as="geometry" />
        </mxCell>
        <mxCell id="s3_meta" value="bids/{{bid_no}}/metadata.json&#xa;(Full Relational Schema Backup)" parent="box_s3" style="shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;fillColor=#FFFFFF;strokeColor=#D97706;fontSize=10;fontStyle=1;" vertex="1">
          <mxGeometry x="30" y="150" width="200" height="80" as="geometry" />
        </mxCell>
        <mxCell id="s3_atc" value="bids/{{bid_no}}/atc_compliance.json&#xa;(8-Domain AI Legal Checklist)" parent="box_s3" style="shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;fillColor=#FFFFFF;strokeColor=#D97706;fontSize=10;fontStyle=1;" vertex="1">
          <mxGeometry x="290" y="150" width="200" height="80" as="geometry" />
        </mxCell>

        <!-- PostgreSQL 18 -->
        <mxCell id="box_pg" value="PostgreSQL 18 Hybrid Database (gem-bridge with pgvector &amp; pg_trgm)" parent="box_layer5" style="rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fontSize=13;fillColor=#FEF3C7;strokeColor=#D97706;strokeWidth=1.5;fontColor=#92400E;spacingTop=8;" vertex="1">
          <mxGeometry x="630" y="50" width="760" height="260" as="geometry" />
        </mxCell>
        <mxCell id="pg_relational" value="10 Relational ACID Tables:&#xa;• bids (Master Header &amp; Dates)&#xa;• bid_items (Specs JSONB)&#xa;• bid_consignees (Locations &amp; Pins)&#xa;• bid_evaluation_schedules (Lots)&#xa;• bid_terms &amp; bid_hyperlinks" parent="box_pg" style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=12;fillColor=#FFFFFF;strokeColor=#D97706;fontSize=11;align=left;spacing=8;" vertex="1">
          <mxGeometry x="40" y="50" width="320" height="180" as="geometry" />
        </mxCell>
        <mxCell id="pg_vector" value="AI &amp; Semantic Vector Engine:&#xa;• gem_bid_chunks (768-dim BGE Vectors)&#xa;• HNSW Cosine Index (vector_cosine_ops)&#xa;• bid_atc_checklist_items (8 Domains)&#xa;• bid_atc_physical_submissions (DDs)&#xa;• bid_atc_analyses (Token Telemetry)" parent="box_pg" style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=12;fillColor=#FFFFFF;strokeColor=#D97706;fontSize=11;align=left;spacing=8;" vertex="1">
          <mxGeometry x="400" y="50" width="320" height="180" as="geometry" />
        </mxCell>

        <!-- Inter-Layer Connecting Edges -->
        <mxCell id="edge1" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#2563EB;" edge="1" parent="1" source="node_web" target="box_layer2">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="edge2" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#16A34A;" edge="1" parent="1" source="r_tasks" target="q_scrape">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="edge3" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#DC2626;" edge="1" parent="1" source="q_scrape" target="w_tier1">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="edge4" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#9333EA;" edge="1" parent="1" source="w_tier1" target="q_doc">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="edge5" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#DC2626;" edge="1" parent="1" source="q_doc" target="w_tier2">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="edge6" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#9333EA;" edge="1" parent="1" source="w_tier2" target="q_atc">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="edge7" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#DC2626;" edge="1" parent="1" source="q_atc" target="w_tier3">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="edge8" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#9333EA;" edge="1" parent="1" source="w_tier2" target="box_layer5">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="edge9" style="edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=2;strokeColor=#9333EA;" edge="1" parent="1" source="w_tier3" target="pg_vector">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>

      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"Successfully generated GeMBridge v3 draw.io diagram: {out_path}")

if __name__ == "__main__":
    dir_path = r"c:\Projects\GeM\Scrapper & RAG Pipeline\Documentation\System-Flow-Diagrams"
    out_file = os.path.join(dir_path, "GeM-Bridge-v3.drawio")
    generate_v3_drawio(out_file)
