-- =========================================================================
-- GeMBridge Database Schema v3.0 (Hybrid Enterprise Edition)
-- Standard DDL for PostgreSQL 16+ (with pgvector & pg_trgm)
-- Target Database: "gem-bridge"
-- =========================================================================

-- 1. Activate Required Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Master Bids Table
CREATE TABLE IF NOT EXISTS bids (
    id                              VARCHAR(64) PRIMARY KEY,
    bid_no                          VARCHAR(64) NOT NULL UNIQUE,
    ra_no                           VARCHAR(64),
    bid_type                        VARCHAR(64) NOT NULL,
    product_type                    VARCHAR(64) NOT NULL,
    base_type                       VARCHAR(64) NOT NULL,
    process_kind                    VARCHAR(64) NOT NULL,
    bid_packet_type                 VARCHAR(64),
    status                          VARCHAR(32) DEFAULT 'ongoing',
    ministry_state_name             VARCHAR(255),
    department_name                 VARCHAR(255),
    organisation_name               VARCHAR(255),
    office_name                     VARCHAR(255),
    start_datetime                  TIMESTAMPTZ,
    end_datetime                    TIMESTAMPTZ NOT NULL,
    card_start_datetime             VARCHAR(64),
    card_end_datetime               VARCHAR(64),
    bid_opening_datetime            TIMESTAMPTZ,
    bid_offer_validity_days         INT,
    bid_duration_days               NUMERIC(6,2),
    days_remaining                  NUMERIC(6,2),
    is_expired                      BOOLEAN DEFAULT FALSE,
    is_corrigendum                  BOOLEAN DEFAULT FALSE,
    estimated_value                 NUMERIC(38,2),
    is_high_value                   BOOLEAN DEFAULT FALSE,
    emd_required                    BOOLEAN DEFAULT FALSE,
    emd_amount                      NUMERIC(38,2),
    emd_advisory_bank               VARCHAR(128),
    epbg_required                   BOOLEAN DEFAULT FALSE,
    epbg_percent                    NUMERIC(5,2),
    epbg_duration_months            INT,
    epbg_advisory_bank              VARCHAR(128),
    evaluation_method               VARCHAR(128) NOT NULL,
    bid_to_ra_enabled               BOOLEAN DEFAULT FALSE,
    ra_qualification_rule           VARCHAR(128),
    clarification_window_days       INT,
    inspection_required             BOOLEAN DEFAULT FALSE,
    inspection_agency               VARCHAR(128),
    arbitration_clause              BOOLEAN DEFAULT FALSE,
    mediation_clause                BOOLEAN DEFAULT FALSE,
    show_docs_to_all                BOOLEAN DEFAULT FALSE,
    allow_only_class_1_2            BOOLEAN DEFAULT FALSE,
    mse_preference                  BOOLEAN DEFAULT FALSE,
    mse_price_band_percent          NUMERIC(5,2),
    mse_max_quantity_percent        NUMERIC(5,2),
    mse_relaxation                  BOOLEAN DEFAULT FALSE,
    startup_relaxation              BOOLEAN DEFAULT FALSE,
    mii_preference                  BOOLEAN DEFAULT FALSE,
    mii_price_band_percent          NUMERIC(5,2),
    mii_max_quantity_percent        NUMERIC(5,2),
    auto_extension_enabled          BOOLEAN DEFAULT FALSE,
    min_bids_disable_extension      INT,
    auto_extend_days                INT,
    auto_extension_count            INT,
    total_items_count               INT DEFAULT 1,
    total_quantity                  NUMERIC(38,2),
    quantity_match_flag             VARCHAR(16),
    bid_pdf_url                     TEXT,
    ra_pdf_url                      TEXT,
    required_documents              TEXT[],                         -- Native PostgreSQL array
    raw_data                        JSONB,                          -- Full unaltered JSON backup
    created_at                      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Child Table: Items
CREATE TABLE IF NOT EXISTS bid_items (
    id             BIGSERIAL PRIMARY KEY,
    bid_id         VARCHAR(64) NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    item_index     INT NOT NULL DEFAULT 1,
    item_category  VARCHAR(500) NOT NULL,
    quantity       NUMERIC(38,2),
    source         VARCHAR(16) NOT NULL DEFAULT 'card',
    specifications JSONB                                            -- Technical parameters
);

-- 4. Child Table: Consignees & Reporting Officers
CREATE TABLE IF NOT EXISTS bid_consignees (
    id            BIGSERIAL PRIMARY KEY,
    bid_id        VARCHAR(64) NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    officer_name  VARCHAR(255),
    address       TEXT NOT NULL,
    pincode       CHAR(6),
    city          VARCHAR(100),
    quantity_raw  TEXT,
    quantity      NUMERIC(38,2),
    is_lumpsum    BOOLEAN DEFAULT FALSE,
    delivery_days INT
);

-- 5. Child Table: Evaluation Schedules (Multi-Lot Bids)
CREATE TABLE IF NOT EXISTS bid_evaluation_schedules (
    id                BIGSERIAL PRIMARY KEY,
    bid_id            VARCHAR(64) NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    schedule_name     VARCHAR(128) NOT NULL,
    item_category     VARCHAR(500),
    quantity          NUMERIC(38,2),
    estimated_value   NUMERIC(38,2),
    consignee_officer VARCHAR(255),
    consignee_address TEXT,
    grouped_items     JSONB                                         -- Sub-items for group-wise bids
);

-- 6. Child Table: ATC Compliance Checklist Items
CREATE TABLE IF NOT EXISTS bid_atc_checklist_items (
    id            BIGSERIAL PRIMARY KEY,
    bid_id        VARCHAR(64) NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    category      VARCHAR(64) NOT NULL,
    clause_text   TEXT NOT NULL,
    display_order INT NOT NULL DEFAULT 0
);

-- 7. Child Table: ATC Physical Offline Submissions
CREATE TABLE IF NOT EXISTS bid_atc_physical_submissions (
    id                   BIGSERIAL PRIMARY KEY,
    bid_id               VARCHAR(64) NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    item_name            VARCHAR(255) NOT NULL,
    deadline             VARCHAR(255),
    in_favor_of          VARCHAR(255),
    payable_at           VARCHAR(255),
    delivery_address     TEXT,
    original_clause_text TEXT
);

-- 8. Child Table: Embedded Hyperlinks Catalog
CREATE TABLE IF NOT EXISTS bid_hyperlinks (
    id          BIGSERIAL PRIMARY KEY,
    bid_id      VARCHAR(64) NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    page_number INT,
    link_name   VARCHAR(255),
    url         TEXT NOT NULL,
    source      VARCHAR(16) NOT NULL DEFAULT 'bid'
);

-- 9. Decoupled 1:1 Heavy Terms & Markdown Content
CREATE TABLE IF NOT EXISTS bid_terms (
    bid_id                VARCHAR(64) PRIMARY KEY REFERENCES bids(id) ON DELETE CASCADE,
    special_terms_version VARCHAR(64),
    special_terms_text    TEXT,
    buyer_atc_text        TEXT,
    emd_exemption_text    TEXT,
    disclaimer            TEXT,
    full_pdf_text         TEXT
);

-- 10. AI Telemetry & Cost Tracking Table
CREATE TABLE IF NOT EXISTS bid_atc_analyses (
    bid_id          VARCHAR(64) PRIMARY KEY REFERENCES bids(id) ON DELETE CASCADE,
    status          VARCHAR(32) NOT NULL,
    has_atc         BOOLEAN NOT NULL DEFAULT FALSE,
    elapsed_seconds NUMERIC(8,3),
    cost_usd        NUMERIC(8,6),
    cost_inr        NUMERIC(8,4),
    input_tokens    INT,
    output_tokens   INT,
    error_message   TEXT
);

-- 11. pgvector Semantic Chunks Table (RAG Engine)
CREATE TABLE IF NOT EXISTS gem_bid_chunks (
    id          BIGSERIAL PRIMARY KEY,
    bid_id      VARCHAR(64) NOT NULL REFERENCES bids(id) ON DELETE CASCADE,
    chunk_type  VARCHAR(32) NOT NULL DEFAULT 'general_pdf',
    chunk_text  TEXT NOT NULL,
    metadata    JSONB,
    embedding   vector(768) NOT NULL
);

-- =========================================================================
-- OPTIMIZED B-TREE, GIN & HNSW INDEXES
-- =========================================================================

-- Master Table B-Tree & GIN Indexes
CREATE INDEX IF NOT EXISTS idx_bids_bid_no ON bids(bid_no);
CREATE INDEX IF NOT EXISTS idx_bids_end_datetime ON bids(end_datetime);
CREATE INDEX IF NOT EXISTS idx_bids_department ON bids(department_name);
CREATE INDEX IF NOT EXISTS idx_bids_org ON bids(organisation_name);
CREATE INDEX IF NOT EXISTS idx_bids_estimated_val ON bids(estimated_value);
CREATE INDEX IF NOT EXISTS idx_bids_emd ON bids(emd_required, emd_amount);
CREATE INDEX IF NOT EXISTS idx_bids_status ON bids(status, is_expired);
CREATE INDEX IF NOT EXISTS idx_bids_req_docs ON bids USING GIN (required_documents);

-- Child Table Foreign Key & Search Indexes
CREATE INDEX IF NOT EXISTS idx_bid_items_bid ON bid_items(bid_id);
CREATE INDEX IF NOT EXISTS idx_bid_items_category_trgm ON bid_items USING gin (item_category gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_bid_consignees_bid ON bid_consignees(bid_id);
CREATE INDEX IF NOT EXISTS idx_bid_consignees_pin ON bid_consignees(pincode);
CREATE INDEX IF NOT EXISTS idx_bid_consignees_city ON bid_consignees(city);
CREATE INDEX IF NOT EXISTS idx_bid_schedules_bid ON bid_evaluation_schedules(bid_id);
CREATE INDEX IF NOT EXISTS idx_bid_checklist_bid_cat ON bid_atc_checklist_items(bid_id, category);
CREATE INDEX IF NOT EXISTS idx_bid_checklist_text_gin ON bid_atc_checklist_items USING gin (to_tsvector('english', clause_text));
CREATE INDEX IF NOT EXISTS idx_bid_phys_bid ON bid_atc_physical_submissions(bid_id);
CREATE INDEX IF NOT EXISTS idx_bid_links_bid ON bid_hyperlinks(bid_id);

-- pgvector HNSW Cosine Index for Sub-5ms Vector Search
CREATE INDEX IF NOT EXISTS idx_gem_bid_chunks_hnsw ON gem_bid_chunks USING hnsw (embedding vector_cosine_ops);
