# GeM Scraper → Tender API Format Mapping

This document maps the existing GeM scraper fields to the new unified tender format (matching `active_tenders-mittal-ind.json`).

---

## Field Mapping

| **Target Field** | **Source** | **Transformation** | **Status** |
|---|---|---|---|
| `tender_id` | Auto-generated | `TD{random_8_chars}-{6_digits}` | ✅ Auto |
| `tender_no` | PDF/Card | Same as `tender_reference_id` | ✅ Direct |
| `tender_reference_id` | PDF/Card `bid_no` | `GEM/YYYY/B/NNNNNN` pattern | ✅ Direct |
| `tender_status` | Calculated | "OPEN" if `end_date > now`, else "CLOSED" | ✅ Computed |
| `tender_type` | Calculated | "Open Tender" (all GeM bids are open tenders) | ✅ Fixed |
| `tender_value` | PDF | Regex: `Estimated Bid Value\s+(\d[\d,\.]+)` → `{"$numberDecimal": "350000.0"}` | ✅ Parse |
| `tender_summary` | Card + PDF | `"Bids are invited for {full_item_name}"` | ✅ Template |
| `work_desc` | Card + PDF | Template: `"{authority} has published Bids Are invited for {full_item_name}. Last date of submission for this tender is {due_date}. This is a {product_name} tender in {city}, {state}"` | ✅ Template |
| `authority` | PDF | Regex: `Department Name\s*[:\-]?\s*([^\n]{5,200})` (Hindi or English) | ✅ Parse |
| `department` | Card/PDF | Same as `authority` (duplicate field) | ✅ Direct |
| `full_item_name` | Card popover | Already extracted via `get_full_item_name_from_card()` | ✅ Existing |
| `category` | PDF | Regex: `Item Category\s+([^\n]+)` → split on `;` or `,` → take first part | ⚠️ Parse |
| `sub_category` | PDF | Same source → take second part after split | ⚠️ Parse |
| `product_name` | Derived | Map `category` → predefined product names (e.g., "Printing Work") | ⚠️ Helper |
| `sector` | Derived | Map `authority` → sector categories (e.g., "Public Administrative Department", "Defense", "Healthcare") | ⚠️ Helper |
| `procurement_type` | PDF | From `Item Category` or infer from `category` (Services/Goods/Works) | ⚠️ Parse |
| `bidding_type` | Fixed | "Tender" (all GeM bids are tenders, not RFQs) | ✅ Fixed |
| `competition_type` | Fixed | "NCB" (National Competitive Bidding - default for GeM) | ✅ Fixed |
| `ownership` | Fixed | "Government Departments" (all GeM buyers are government) | ✅ Fixed |
| `platforms` | Fixed | `["GEM"]` | ✅ Fixed |
| `procurement_source` | Fixed | `"https://gem.gov.in/"` | ✅ Fixed |
| `procurement_source_name` | Fixed | `"Gem"` | ✅ Fixed |
| `start_date` / `enter_date` / `pub_date` | Card/PDF | Already extracted as `start_date` → convert to `{"$numberLong": "1778457600000"}` (milliseconds UTC) | ✅ Convert |
| `end_date` / `due_date` / `org_subm_date` | Card/PDF | Already extracted as `end_date` → convert to milliseconds | ✅ Convert |
| `open_date` | PDF | Regex: `Bid Opening Date.*?(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})` | ✅ Parse |
| `address` | PDF (Consignee) | Regex: `Consignee.*?\n.*?\n([^\n]+,\s*\d{6}[^\n]*)` | ⚠️ Parse |
| `address_pin` | PDF (Consignee) | Extract 6-digit pin from address | ⚠️ Parse |
| `city` | PDF (Consignee) | Extract city name from address (before pin code) | ⚠️ Helper |
| `state` | PDF (Consignee) | Map city → state using helper function | ⚠️ Helper |
| `contact_person` | PDF (Consignee) | First line under "Consignee/Reporting Officer" | ⚠️ Parse |
| `contact_email` | PDF (Consignee) | Regex: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` near consignee section | ⚠️ Parse |
| `contact_phone` | PDF (Consignee) | Regex: `\+?\d[\d\s\-\(\)]{7,15}` near consignee section | ⚠️ Parse |
| `earnest_amount` | PDF | Regex: `EMD Amount.*?(\d[\d,]+)` → convert to `{"$numberDecimal": "0.0"}` | ✅ Parse |
| `doc_cost` | PDF | Regex: `Document Fee.*?(\d[\d,]+)` or default to 0 | ⚠️ Parse |
| `search_text` | PDF | From `Item Category` full text → format as "Paper and Printing Services, Printing Related Service, Printing Work" | ✅ Parse |
| `is_corrigendum` | Card/PDF | Check if `ra_no` (RA number like `GEM/2026/R/NNNNNN`) exists → `true` if present | ✅ Computed |
| `s3_document_path` | Existing | Transform `document_url` → `[{"download_id": auto, "file_name": "Tender Document", "tender_download_path": document_url}]` | ✅ Transform |
| `document_path` | Existing | Local PDF path from `downloads/` folder | ✅ Direct |
| `attachment` | Fixed | "Tender Document" | ✅ Fixed |
| `created_at` / `updated_at` | Auto | Current timestamp in milliseconds | ✅ Auto |
| `tentative_date` | Fixed | `false` (GeM dates are firm) | ✅ Fixed |
| `random_number` | Auto | UUID v4 uppercase without hyphens | ✅ Auto |
| `country` | Fixed | "India" (all GeM tenders are India) | ✅ Fixed |
| `quantity` | Card/PDF | Already extracted | ✅ Existing |
| `is_file_downloaded` | Computed | Check if PDF exists in `downloads/` | ✅ Computed |

---

## Fields NOT Required

- `org_subm_date`: Same as `due_date` (duplicate)
- `procurement_source_name`: Always "Gem"
- `platforms`: Always `["GEM"]`
- `country`: Always "India"

---

## Helper Functions Needed

### 1. **City Extractor**
```python
def extract_city_from_address(address: str) -> str:
    """
    Extract city name from address like:
    "603102,DPS/IGCAR, Central Stores Unit, Kalpakkam"
    → "Kalpakkam"
    """
```

### 2. **State Mapper**
```python
CITY_TO_STATE_MAP = {
    "Kalpakkam": "Tamil Nadu",
    "Delhi": "Delhi",
    "Mumbai": "Maharashtra",
    ...
}
def get_state_from_city(city: str) -> str:
    """Map city → state using predefined dict + fuzzy matching"""
```

### 3. **Product Name Mapper**
```python
CATEGORY_TO_PRODUCT = {
    "paper and printing": "Printing Work",
    "xlpe cable": "Electrical Cable",
    "cab hiring": "Transportation Services",
    ...
}
def infer_product_name(category: str) -> str:
    """Map item category → clean product name"""
```

### 4. **Sector Classifier**
```python
DEPARTMENT_TO_SECTOR = {
    "atomic energy": "Defense / Strategic",
    "human rights": "Public Administrative Department",
    "petroleum": "Energy / PSU",
    ...
}
def classify_sector(authority: str) -> str:
    """Map department → sector category"""
```

### 5. **Procurement Type Classifier**
```python
def infer_procurement_type(category: str) -> str:
    """
    Goods: cables, equipment, furniture
    Services: printing, facility management, consulting
    Works: construction, civil works
    """
```

---

## Regex Patterns

### PDF Parsing

```python
# Estimated Bid Value
r"Estimated\s+Bid\s+Value.*?(\d[\d,\.]+)"

# EMD Amount
r"EMD Amount.*?(\d[\d,]+)"

# Item Category (full)
r"Item Category\s+([^\n]{5,300})"

# Consignee Address (after pin code)
r"(\d{6}),([^\n]{10,200})"

# Contact Email
r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

# Contact Phone
r"\+?[0-9][\d\s\-\(\)]{7,15}"

# Bid Opening Date
r"Bid\s+Opening.*?(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})"
```

---

## Timestamp Conversion

```python
from datetime import datetime

def datetime_to_mongo_timestamp(date_str: str) -> dict:
    """
    Convert "22-05-2026 00:00:00" → {"$numberLong": "1779408000000"}
    """
    dt = datetime.strptime(date_str, "%d-%m-%Y %H:%M:%S")
    ms = int(dt.timestamp() * 1000)
    return {"$numberLong": str(ms)}
```

---

## Implementation Plan

1. ✅ **Create new parser** `core/gem_to_tender_parser.py`
2. ✅ **Add helper functions** for city/state/sector/product mapping
3. ✅ **Update database schema** to add new fields
4. ✅ **Modify scraper** to call new parser after existing extraction
5. ✅ **Test with existing PDFs** to verify all fields populate correctly

---

## Questions / Clarifications

1. **Doc cost**: Where exactly in PDF? Most samples show EMD but not doc cost.
2. **Competition type**: Always NCB or sometimes ICB for large tenders?
3. **Procurement type inference**: Should we build ML classifier or simple keyword matching?
4. **State mapping**: Do you have a complete city→state list, or should I build one from existing data?
