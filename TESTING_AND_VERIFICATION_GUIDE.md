# 🧪 GeM Pipeline — Testing & Verification Command Reference

This guide provides end-to-end instructions for testing, inspecting, and verifying the enhancements implemented across **Phase 1** (Normalization & Parsing), **Phase 2** (ATC Compliance Analysis), and **Phase 3** (RAG Vector Search & Clause-Level Q&A).

---

## 🚀 Environment Setup

Open PowerShell or Command Prompt inside the `Scrapper & RAG Pipeline` directory and activate the local virtual environment:

```powershell
cd "c:\Projects\GeM\Scrapper & RAG Pipeline"
.\venv\Scripts\activate
```

---

## ⚡ Option 1: Automated Test Suite (All-In-One)

Run the automated test runner to execute self-contained unit and integration checks across all modules:

```powershell
python test_all_phases.py
```

### Checks Performed:
1. **Normalizer & Validation (Phase 1):** Tests Indian currency conversions (`₹18.85 Lakh`, `1.5 Crore`, `50,000/-` $\rightarrow$ floats & strings), ISO 8601 timestamps, duration/expiration metrics, and data integrity validation.
2. **Core Parser (Phase 1):** Verifies table extraction for `estimated_value`, EMD amounts, and multi-item bunch bid items.
3. **ATC Extractor (Phase 2):** Tests structured 5-section mapping (Standard Docs, Clarified ATC Uploads, Exemptions, Physical Submissions, Key Commercial Terms) and runs a live Gemini API call on test markdowns.
4. **SQLite Database (Phase 2):** Verifies the `atc_analysis` schema column and auto-migration safety.
5. **ChromaDB Vector Store (Phase 3):** Checks collection health, indexed chunk counts, and high-signal ATC chunks.
6. **Hybrid RAG Query Engine (Phase 3):** Tests catalog search and clause-level compliance question answering with auto-fallback to Gemini.

---

## 🛠️ Option 2: Individual Feature Testing Commands

### 1. Database & Vector Store Statistics
Display SQLite record counts, unseen bids, and ChromaDB chunk totals:

```powershell
python main.py --stats
```

---

### 2. ATC Compliance Extraction
Extract and classify procurement obligations, mandatory uploads, exemption proofs, physical submissions, and commercial clauses from any tender markdown:

* **Analyze a specific test tender:**
  ```powershell
  python main.py --analyze-atc "ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2026_B_7495766"
  ```

* **Analyze a tender with extensive medical/commercial terms:**
  ```powershell
  python main.py --analyze-atc "ATC EXTRACTOR/TEST_MARKDOWNS/GEM_2025_B_6904960"
  ```

* **Analyze an entire batch directory:**
  ```powershell
  python main.py --analyze-atc "downloads"
  ```

> **Artifact Output:** Writes `<bid_no>_ATC.md` inside the tender folder and outputs section counts to the terminal.

---

### 3. RAG Clause-Level Compliance Question Answering
Query specific procurement requirements, exemption rules, EMD terms, or warranty clauses across indexed tenders:

```powershell
python main.py --ask "What are the exemption rules and documents required for MSEs in the medical analyzer bid?"
```

```powershell
python main.py --ask "What is the warranty period and SLA penalty for the medical analyzer tender?"
```

> **Expected Output:** Direct, concise answer citing the exact Bid Number and clauses (*e.g., EMD waiver with MSME/NSIC certificate, 2 years warranty + 8 years CMC, 0.5% delay penalty*), followed by source attribution.

---

### 4. RAG Catalog Search & Filtering
Search for matching bids by product type, item name, or department:

```powershell
python main.py --ask "What bids are there for desktop computers?"
```

```powershell
python main.py --ask "desktop computer" --filter product_type=Product
```

> **Expected Output:** Structured cards formatted with Bid Number, Item Title, Department, Start/End Dates, Estimated Value, and Portal Document URL.

---

### 5. Interactive Terminal RAG Chat
Launch an interactive chat session to query the tender database continuously:

```powershell
python main.py --chat
```

* Type any search query or compliance question.
* Special commands in chat:
  * `/search <term>`: Bypasses LLM generation to display raw retrieved chunks.
  * `/stats`: Shows live database and vector store chunk totals.
  * `exit` / `quit`: Exits the session.

---

### 6. Vector Store Re-Indexing (Self-Healing)
Re-index all bids from SQLite into ChromaDB with BGE embeddings, BM25, and ATC compliance chunks:

```powershell
python main.py --reindex
```

---

### 7. Live Web Scraper Execution (Optional)
Scrape live bids directly from the GeM portal using browser automation:

* **Scrape a specific active bid number:**
  ```powershell
  python main.py --bid "GEM/2026/B/7768206"
  ```

* **Run a single scrape pass across all configured categories:**
  ```powershell
  python main.py --once
  ```

* **Launch the continuous hourly scraping daemon:**
  ```powershell
  python main.py
  ```

---

## 📁 Key File Locations

| File / Directory | Description |
| :--- | :--- |
| [`test_all_phases.py`](file:///C:/Projects/GeM/Scrapper%20&%20RAG%20Pipeline/test_all_phases.py) | Automated test suite verifying all modules. |
| [`pipeline/atc_analyzer.py`](file:///C:/Projects/GeM/Scrapper%20&%20RAG%20Pipeline/pipeline/atc_analyzer.py) | 5-section ATC compliance extractor engine. |
| [`core/normalizer.py`](file:///C:/Projects/GeM/Scrapper%20&%20RAG%20Pipeline/core/normalizer.py) | Currency, date, and schema validation engine. |
| [`core/parser.py`](file:///C:/Projects/GeM/Scrapper%20&%20RAG%20Pipeline/core/parser.py) | Multi-item and Markdown table parser. |
| [`storage/gem_bids.db`](file:///C:/Projects/GeM/Scrapper%20&%20RAG%20Pipeline/storage/gem_bids.db) | SQLite database containing scraped bids and ATC text. |
| [`storage/chroma_db/`](file:///C:/Projects/GeM/Scrapper%20&%20RAG%20Pipeline/storage/chroma_db/) | Persistent ChromaDB vector database. |
| [`downloads/`](file:///C:/Projects/GeM/Scrapper%20&%20RAG%20Pipeline/downloads/) | Output folder for scraped artifacts (`.html`, `.pdf`, `.md`, `.json`, `_ATC.md`). |
