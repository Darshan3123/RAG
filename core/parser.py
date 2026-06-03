# =========================================================
# core/parser.py
# PDF extraction + field parsing + card-HTML extraction
# + unified tender-format output (matching active_tenders JSON)
# =========================================================
import re
import os
import sys
import uuid
import html
import json
import fitz
from datetime import datetime, timezone
from config.settings import TESSERACT_CMD
from utils.logger import get_logger

log = get_logger("parser")

if sys.platform == "win32":
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    except ImportError:
        pass


# =========================================================
# INDIA — CITY → STATE MAP
# =========================================================
CITY_TO_STATE: dict[str, str] = {
    # Andhra Pradesh
    "visakhapatnam": "Andhra Pradesh", "vijayawada": "Andhra Pradesh",
    "guntur": "Andhra Pradesh", "nellore": "Andhra Pradesh",
    "kurnool": "Andhra Pradesh", "tirupati": "Andhra Pradesh",
    "kakinada": "Andhra Pradesh", "rajahmundry": "Andhra Pradesh",
    "eluru": "Andhra Pradesh", "ongole": "Andhra Pradesh",
    "anantapur": "Andhra Pradesh", "kadapa": "Andhra Pradesh",
    "vizag": "Andhra Pradesh",
    # Arunachal Pradesh
    "itanagar": "Arunachal Pradesh", "naharlagun": "Arunachal Pradesh",
    "tawang": "Arunachal Pradesh",
    # Assam
    "guwahati": "Assam", "silchar": "Assam", "dibrugarh": "Assam",
    "jorhat": "Assam", "nagaon": "Assam", "tinsukia": "Assam",
    "dispur": "Assam",
    # Bihar
    "patna": "Bihar", "gaya": "Bihar", "muzaffarpur": "Bihar",
    "bhagalpur": "Bihar", "darbhanga": "Bihar", "purnia": "Bihar",
    "arrah": "Bihar", "begusarai": "Bihar", "bihar sharif": "Bihar",
    # Chhattisgarh
    "raipur": "Chhattisgarh", "bilaspur": "Chhattisgarh",
    "durg": "Chhattisgarh", "bhilai": "Chhattisgarh",
    "korba": "Chhattisgarh", "rajnandgaon": "Chhattisgarh",
    # Delhi
    "delhi": "Delhi", "new delhi": "Delhi", "dwarka": "Delhi",
    "rohini": "Delhi", "janakpuri": "Delhi", "saket": "Delhi",
    "noida": "Uttar Pradesh", "gurugram": "Haryana", "gurgaon": "Haryana",
    # Goa
    "panaji": "Goa", "vasco da gama": "Goa", "margao": "Goa",
    "mapusa": "Goa",
    # Gujarat
    "ahmedabad": "Gujarat", "surat": "Gujarat", "vadodara": "Gujarat",
    "rajkot": "Gujarat", "bhavnagar": "Gujarat", "jamnagar": "Gujarat",
    "gandhinagar": "Gujarat", "anand": "Gujarat", "nadiad": "Gujarat",
    "morbi": "Gujarat", "mehsana": "Gujarat", "mahesana": "Gujarat",
    "junagadh": "Gujarat", "surendranagar": "Gujarat",
    # Haryana
    "faridabad": "Haryana", "gurgaon": "Haryana", "gurugram": "Haryana",
    "panipat": "Haryana", "ambala": "Haryana", "yamunanagar": "Haryana",
    "rohtak": "Haryana", "hisar": "Haryana", "karnal": "Haryana",
    "sonipat": "Haryana", "panchkula": "Haryana",
    # Himachal Pradesh
    "shimla": "Himachal Pradesh", "manali": "Himachal Pradesh",
    "dharamshala": "Himachal Pradesh", "solan": "Himachal Pradesh",
    "mandi": "Himachal Pradesh", "kullu": "Himachal Pradesh",
    # Jammu and Kashmir / Ladakh
    "srinagar": "Jammu and Kashmir", "jammu": "Jammu and Kashmir",
    "anantnag": "Jammu and Kashmir", "baramulla": "Jammu and Kashmir",
    "leh": "Ladakh", "kargil": "Ladakh",
    # Jharkhand
    "ranchi": "Jharkhand", "jamshedpur": "Jharkhand",
    "dhanbad": "Jharkhand", "bokaro": "Jharkhand",
    "hazaribagh": "Jharkhand", "deoghar": "Jharkhand",
    # Karnataka
    "bengaluru": "Karnataka", "bangalore": "Karnataka",
    "mysuru": "Karnataka", "mysore": "Karnataka",
    "hubli": "Karnataka", "dharwad": "Karnataka",
    "mangaluru": "Karnataka", "mangalore": "Karnataka",
    "belagavi": "Karnataka", "belgaum": "Karnataka",
    "kalaburagi": "Karnataka", "gulbarga": "Karnataka",
    "ballari": "Karnataka", "bellary": "Karnataka",
    "tumkur": "Karnataka", "shivamogga": "Karnataka",
    "davanagere": "Karnataka", "bidar": "Karnataka",
    # Kerala
    "thiruvananthapuram": "Kerala", "trivandrum": "Kerala",
    "kochi": "Kerala", "cochin": "Kerala", "kozhikode": "Kerala",
    "calicut": "Kerala", "thrissur": "Kerala", "kollam": "Kerala",
    "palakkad": "Kerala", "alappuzha": "Kerala", "kannur": "Kerala",
    "ernakulam": "Kerala", "kottayam": "Kerala", "malappuram": "Kerala",
    # Madhya Pradesh
    "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh",
    "jabalpur": "Madhya Pradesh", "gwalior": "Madhya Pradesh",
    "ujjain": "Madhya Pradesh", "sagar": "Madhya Pradesh",
    "ratlam": "Madhya Pradesh", "satna": "Madhya Pradesh",
    "rewa": "Madhya Pradesh", "dewas": "Madhya Pradesh",
    # Maharashtra
    "mumbai": "Maharashtra", "pune": "Maharashtra",
    "nagpur": "Maharashtra", "nashik": "Maharashtra",
    "aurangabad": "Maharashtra", "solapur": "Maharashtra",
    "amravati": "Maharashtra", "kolhapur": "Maharashtra",
    "thane": "Maharashtra", "navi mumbai": "Maharashtra",
    "sangli": "Maharashtra", "jalgaon": "Maharashtra",
    "latur": "Maharashtra", "ahmednagar": "Maharashtra",
    "chandrapur": "Maharashtra", "nanded": "Maharashtra",
    "pallavaram": "Tamil Nadu",  # Chennai suburb
    # Manipur
    "imphal": "Manipur",
    # Meghalaya
    "shillong": "Meghalaya",
    # Mizoram
    "aizawl": "Mizoram",
    # Nagaland
    "kohima": "Nagaland", "dimapur": "Nagaland",
    # Odisha
    "bhubaneswar": "Odisha", "cuttack": "Odisha",
    "rourkela": "Odisha", "berhampur": "Odisha",
    "sambalpur": "Odisha", "puri": "Odisha", "balasore": "Odisha",
    # Punjab
    "ludhiana": "Punjab", "amritsar": "Punjab",
    "jalandhar": "Punjab", "patiala": "Punjab",
    "bathinda": "Punjab", "pathankot": "Punjab", "mohali": "Punjab",
    # Rajasthan
    "jaipur": "Rajasthan", "jodhpur": "Rajasthan",
    "udaipur": "Rajasthan", "ajmer": "Rajasthan",
    "kota": "Rajasthan", "bikaner": "Rajasthan",
    "alwar": "Rajasthan", "bharatpur": "Rajasthan",
    "sikar": "Rajasthan", "pali": "Rajasthan",
    # Sikkim
    "gangtok": "Sikkim",
    # Tamil Nadu
    "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "madurai": "Tamil Nadu", "tiruchirappalli": "Tamil Nadu",
    "salem": "Tamil Nadu", "tirunelveli": "Tamil Nadu",
    "vellore": "Tamil Nadu", "erode": "Tamil Nadu",
    "thanjavur": "Tamil Nadu", "tirupur": "Tamil Nadu",
    "kalpakkam": "Tamil Nadu", "dindigul": "Tamil Nadu",
    # Telangana
    "hyderabad": "Telangana", "warangal": "Telangana",
    "karimnagar": "Telangana", "nizamabad": "Telangana",
    "khammam": "Telangana", "secunderabad": "Telangana",
    # Tripura
    "agartala": "Tripura",
    # Uttar Pradesh
    "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",
    "agra": "Uttar Pradesh", "varanasi": "Uttar Pradesh",
    "allahabad": "Uttar Pradesh", "prayagraj": "Uttar Pradesh",
    "meerut": "Uttar Pradesh", "ghaziabad": "Uttar Pradesh",
    "noida": "Uttar Pradesh", "mathura": "Uttar Pradesh",
    "aligarh": "Uttar Pradesh", "bareilly": "Uttar Pradesh",
    "moradabad": "Uttar Pradesh", "gorakhpur": "Uttar Pradesh",
    "firozabad": "Uttar Pradesh", "saharanpur": "Uttar Pradesh",
    "jhansi": "Uttar Pradesh", "muzaffarnagar": "Uttar Pradesh",
    # Uttarakhand
    "dehradun": "Uttarakhand", "haridwar": "Uttarakhand",
    "rishikesh": "Uttarakhand", "nainital": "Uttarakhand",
    "haldwani": "Uttarakhand", "roorkee": "Uttarakhand",
    # West Bengal
    "kolkata": "West Bengal", "calcutta": "West Bengal",
    "howrah": "West Bengal", "durgapur": "West Bengal",
    "asansol": "West Bengal", "siliguri": "West Bengal",
    "darjeeling": "West Bengal", "kharagpur": "West Bengal",
    "bardhaman": "West Bengal",
    # Union Territories
    "chandigarh": "Chandigarh",
    "pondicherry": "Puducherry", "puducherry": "Puducherry",
    "port blair": "Andaman and Nicobar Islands",
    "daman": "Dadra and Nagar Haveli and Daman and Diu",
    "silvassa": "Dadra and Nagar Haveli and Daman and Diu",
}


# =========================================================
# SECTOR CLASSIFIER — maps department keywords → sector name
# =========================================================
_SECTOR_RULES: list[tuple[str, str]] = [
    (r"defence|defense|army|navy|air force|military|drdo|ordnance|armament|coast guard|bsf|crpf|cisf|itbp|ssb|paramilitary", "Defence and Security"),
    (r"atomic|nuclear|dae|igcar|barc|npcil|uranium", "Nuclear and Atomic Energy"),
    (r"space|isro|antrix|satellite", "Space and Satellite"),
    (r"petroleum|oil|gas|hpcl|bpcl|iocl|ongc|gail|fuel", "Energy - Oil and Gas"),
    (r"power|electricity|nhpc|ntpc|npcl|bescom|tneb|besst|msedcl|electric supply|energy commission", "Energy - Power"),
    (r"railway|rail|metro|rites|ircon|irctc|konkan|dmrc|nmrc", "Railways and Metro"),
    (r"road|highway|nhai|nhidcl|bridge|flyover|tunnel", "Roads and Infrastructure"),
    (r"port|shipping|maritime|inland waterway|dock|iwai", "Ports and Shipping"),
    (r"aviation|airport|aai|dgca|aircraft|airline|pawan hans", "Aviation"),
    (r"telecom|bsnl|mtnl|trai|dot|communication|broadband", "Telecom and Communication"),
    (r"health|hospital|medical|aiims|esic|cghs|pharmacy|nursing|dental|dispensary|drug|medicine", "Healthcare and Medical"),
    (r"education|school|college|university|iit|iim|nit|cbse|icse|navodaya|kendriya vidyalaya|ugc|aicte", "Education"),
    (r"agriculture|farming|horticulture|irrigation|water resource|dam|canal|rural development|atma", "Agriculture and Rural Development"),
    (r"forest|environment|pollution|ecology|wildlife|zoo", "Environment and Forestry"),
    (r"water supply|jal|sewage|sanitation|drainage", "Water Supply and Sanitation"),
    (r"urban|municipality|smart city|town planning|housing|slum|pwbd|cpwd|nhai", "Urban Development and Housing"),
    (r"finance|bank|rbi|sebi|nabard|sidbi|tax|gst|customs|excise|treasury", "Finance and Banking"),
    (r"police|law|judiciary|court|prison|correctional|ncrb", "Law and Justice"),
    (r"it|software|hardware|computer|digital|data|network|cyber|nic|meity|e-governance", "Information Technology"),
    (r"science|research|technology|laboratory|testing|calibration|csir|dst|dbt", "Science and Technology"),
    (r"social|welfare|women|child|disability|pension|relief|nhrc|human rights|ngo|niti", "Social Welfare"),
    (r"tourism|hospitality|hotel|culture|heritage|museum|monument|asi", "Tourism and Culture"),
    (r"sport|stadium|gym|playground|olympic|sai", "Sports"),
    (r"printing|publication|media|press|broadcast|information|pib|doordarshan|akashvani", "Media and Printing"),
    (r"food|grain|ration|pds|fci|nafed|supply|procurement|civil supply", "Food and Civil Supplies"),
    (r"coal|mine|mineral|steel|metal|iron|bhel|sail|nalco|nmdc|mstc", "Mining and Metals"),
    (r"textile|garment|khadi|handloom|handicraft", "Textiles and Handicrafts"),
    (r"chemical|fertilizer|insecticide|pesticide", "Chemicals and Fertilizers"),
    (r"msme|small enterprise|startup|entrepreneurship", "MSME and Entrepreneurship"),
    (r"revenue|land|record|cadastral|survey", "Revenue and Land Records"),
    (r"panchayat|gram|village|block|tehsil|zila|district", "Panchayati Raj"),
]

def classify_sector(authority: str) -> str:
    """Map department/authority name → sector string."""
    if not authority:
        return "Public Administrative Department"
    text = authority.lower()
    for pattern, sector in _SECTOR_RULES:
        if re.search(pattern, text):
            return sector
    return "Public Administrative Department"


# =========================================================
# PROCUREMENT TYPE — Services / Goods / Works
# =========================================================
_SERVICES_KW = re.compile(
    r"\b(service|hiring|maintenance|facility|management|"
    r"consulting|training|printing|cleaning|security guard|"
    r"annual|repair|AMC|supply\s+of\s+service|manpower|staffing|"
    r"housekeeping|catering|laundry|pest control|gardening|"
    r"transport|cab|taxi|ambulance|courier|event|photography|"
    r"surveying|audit|legal|testing service|inspection)\b",
    re.IGNORECASE,
)
_WORKS_KW = re.compile(
    r"\b(construction|civil|building|renovation|erection|"
    r"installation|plumbing|electrical work|flooring|painting|"
    r"waterproofing|paving|laying|dismantling|demolition|"
    r"work|works)\b",
    re.IGNORECASE,
)

def infer_procurement_type(item_category: str, bid_type: str = "") -> str:
    """Infer Services / Works / Goods from item category text."""
    text = f"{item_category} {bid_type}"
    if _SERVICES_KW.search(text):
        return "Services"
    if _WORKS_KW.search(text):
        return "Works"
    return "Goods"


# =========================================================
# PRODUCT NAME INFERENCE — clean short label for the item
# =========================================================
# Each rule: (keyword_regex, product_name)
_PRODUCT_RULES: list[tuple[str, str]] = [
    # More specific first, generic last
    (r"cable|wire|conductor|xlpe|pvc cable|optical fibre|coaxial", "Electrical Cable"),
    (r"printing|printed|publication|book|booklet|brochure|pamphlet|stationery|paper", "Printing Work"),
    (r"cab\s*(&|and)\s*taxi|car hiring|taxi hiring|vehicle hiring|bus hiring|ambulance", "Transportation Services"),
    (r"\btransport\b|\bshipping\b|\bcourier\b", "Transportation Services"),
    (r"facility management|housekeeping|cleaning|sanitation|janitorial", "Facility Management"),
    (r"security guard|watch.*ward|manpower|guard service", "Security Services"),
    (r"computer|laptop|desktop|server|tablet|pc|hardware", "Computer Hardware"),
    (r"software|application|it service|erp|crm|portal|website", "IT Services"),
    (r"furniture|chair|table|desk|cupboard|almirah|shelf", "Furniture"),
    (r"air condition|ac unit|hvac|refrigerator|cooling", "Air Conditioning Equipment"),
    (r"generator|ups|inverter|transformer|switchgear|panel", "Power Equipment"),
    (r"medical|surgical|hospital|pharmaceutical|drug|medicine|reagent", "Medical Supplies"),
    (r"uniform|garment|cloth|fabric|linen|textile|towel|bedsheet", "Textiles and Uniforms"),
    (r"construction|civil|building|road|bridge|renovation", "Civil Works"),
    (r"repair|maintenance|amc|annual maintenance", "Maintenance Services"),
    (r"food|canteen|catering|ration|grain|rice|wheat", "Food and Catering"),
    (r"fire|extinguisher|sprinkler|safety equipment", "Fire Safety Equipment"),
    (r"cctv|camera|surveillance|biometric|access control", "Security Equipment"),
    (r"pump|motor|valve|pipe|fitting|plumbing", "Pumps and Fittings"),
    (r"chemical|reagent|fertilizer|pesticide|insecticide", "Chemicals"),
    (r"training|consultancy|advisory|seminar|workshop", "Training and Consultancy"),
    (r"signage|sign board|display|banner|hoarding", "Signage"),
    (r"stationery|pen|pencil|notebook|register|file|envelope", "Stationery"),
    (r"tyre|tube|battery|spare part|auto part", "Automobile Parts"),
    (r"instrument|equipment|apparatus|device|machine", "Equipment"),
    (r"uniform|clothing|boot|shoe|footwear", "Uniform and Clothing"),
]

def infer_product_name(item_category: str) -> str:
    """Map item category text → short product name."""
    if not item_category:
        return ""
    text = item_category.lower()
    for pattern, name in _PRODUCT_RULES:
        if re.search(pattern, text):
            return name
    # Fallback: first meaningful word(s) from category
    words = re.sub(r"[^a-zA-Z\s]", " ", item_category).split()
    return " ".join(words[:3]).title() if words else item_category[:40]


# =========================================================
# CATEGORY / SUB_CATEGORY SPLIT
# Item Category in PDF looks like:
#   "Paper-Based Printing Services - Printing With Material; Book/Booklet; Offset"
# → category    = "Paper-Based Printing Services"
# → sub_category = "Printing With Material"
# → product_name = "Printing Work"
# =========================================================
def split_item_category(raw: str) -> tuple[str, str]:
    """
    Split 'Category - SubCat1; SubCat2' into (category, sub_category).
    Uses ' - ' as primary delimiter, '; ' or ',' as secondary.
    Returns (category, sub_category).
    """
    if not raw:
        return "", ""
    # Primary split on ' - '
    if " - " in raw:
        parts = raw.split(" - ", 1)
        cat = parts[0].strip()
        # sub_category: take first segment before ';' or ','
        sub = re.split(r"[;,]", parts[1])[0].strip()
        return cat, sub
    # Fallback: split on ';'
    parts = re.split(r"[;,]", raw)
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    return raw.strip(), ""


# =========================================================
# TIMESTAMP HELPERS
# =========================================================
def _date_str_to_ms(date_str: str) -> int:
    """
    Convert "DD-MM-YYYY HH:MM:SS" → epoch milliseconds (UTC).
    Returns 0 if parsing fails.
    """
    if not date_str:
        return 0
    for fmt in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            # treat as IST (UTC+5:30) → convert to UTC
            ms = int((dt.timestamp() - 19800) * 1000)
            return ms
        except ValueError:
            continue
    return 0

def _ms_obj(date_str: str) -> dict:
    """Return {"$numberLong": "1779408000000"} or empty dict."""
    ms = _date_str_to_ms(date_str)
    return {"$numberLong": str(ms)} if ms else {}

def _decimal_obj(value_str: str) -> dict:
    """Return {"$numberDecimal": "350000.0"} from string like '3,50,000'."""
    if not value_str:
        return {"$numberDecimal": "0"}
    # Remove commas, spaces
    clean = re.sub(r"[,\s]", "", str(value_str))
    try:
        return {"$numberDecimal": str(float(clean))}
    except ValueError:
        return {"$numberDecimal": "0"}

def _now_ms() -> dict:
    """Current UTC time as {"$numberLong": "..."}."""
    ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {"$numberLong": str(ms)}

def _gen_tender_id() -> str:
    """Generate a tender_id like TDxxxxxxx-NNNNNN."""
    uid = uuid.uuid4().hex[:7].upper()
    num = str(uuid.uuid4().int)[:6]
    return f"TD{uid}-{num}"

def _gen_random_number() -> str:
    """UUID v4 uppercase without hyphens."""
    return str(uuid.uuid4()).upper().replace("-", "")


# =========================================================
# PDF TEXT EXTRACTION
# =========================================================
def extract_pdf_text(pdf_path: str) -> str:
    full_text = ""
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            full_text += page.get_text()
        doc.close()
    except Exception as e:
        log.warning(f"PyMuPDF error: {e}")

    if len(full_text.strip()) < 100:
        log.info("Falling back to OCR...")
        try:
            from pdf2image import convert_from_path
            import pytesseract
            images = convert_from_path(pdf_path)
            for img in images:
                full_text += pytesseract.image_to_string(img)
        except Exception as e:
            log.warning(f"OCR error: {e}")

    return full_text


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _strip_html(raw: str) -> str:
    """Strip HTML tags + decode entities."""
    if not raw:
        return ""
    raw = re.sub(r"</?\s*(br|p|li|ul|ol|div|span)\b[^>]*>", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return clean_text(raw)


# =========================================================
# EXTENDED PDF FIELD PARSING
# Extracts ALL new fields needed for the tender format
# =========================================================
def _extract_dates(pdf_text: str) -> tuple[str, str]:
    start_date = ""
    end_date   = ""

    opening_match = re.search(
        r"(?:Bid\s+Opening\s+Date|Opening\s+Date|Bid\s+Opening)\s*(?:/|and)\s*Time\s+"
        r"(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE,
    )
    if opening_match:
        start_date = f"{opening_match.group(1)} {opening_match.group(2)}"

    ending_match = re.search(
        r"(?:Bid\s+End\s+Date|End\s+Date|Bid\s+End)\s*(?:/|and)\s*Time\s+"
        r"(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})",
        pdf_text, re.IGNORECASE,
    )
    if ending_match:
        end_date = f"{ending_match.group(1)} {ending_match.group(2)}"

    if not start_date or not end_date:
        all_dates = re.findall(
            r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})",
            pdf_text,
        )
        if all_dates:
            dates_list = []
            for day, month, year, hour, minute, second in all_dates:
                date_str = f"{day}-{month}-{year} {hour}:{minute}:{second}"
                try:
                    date_obj = datetime.strptime(date_str, "%d-%m-%Y %H:%M:%S")
                    dates_list.append((date_obj, date_str))
                except Exception:
                    pass
            if dates_list:
                dates_list.sort(key=lambda x: x[0])
                if not start_date:
                    start_date = dates_list[0][1]
                if not end_date:
                    end_date = dates_list[-1][1]

    return start_date, end_date


def _extract_consignee_block(pdf_text: str) -> dict:
    """
    Extract consignee details:
    - contact_person: name on first column of the consignee table
    - address: full address including pin
    - address_pin: 6-digit pincode
    - city: extracted from address
    - state: mapped from city
    - contact_email
    - contact_phone
    """
    result = {
        "contact_person": "",
        "address": "",
        "address_pin": "",
        "city": "",
        "state": "",
        "contact_email": "",
        "contact_phone": "",
    }

    # ── 1. Find any 6-digit pin followed by address text ──
    addr_match = re.search(r"(\d{6}),([^\n]{10,250})", pdf_text)
    if addr_match:
        pin  = addr_match.group(1)
        rest = clean_text(addr_match.group(2))
        result["address"]     = f"{pin},{rest}"
        result["address_pin"] = pin

    # ── 2. Try to find city by matching known cities in full address context ──
    # Widen context window around pin code to catch city nearby
    addr_context = ""
    if addr_match:
        start = max(0, addr_match.start() - 200)
        end   = min(len(pdf_text), addr_match.end() + 200)
        addr_context = pdf_text[start:end].lower()
    else:
        addr_context = pdf_text[:3000].lower()

    # Sort by length descending so "new delhi" matches before "delhi"
    for known_city in sorted(CITY_TO_STATE.keys(), key=len, reverse=True):
        if known_city in addr_context:
            result["city"]  = known_city.title()
            break

    # ── 2. State from city map ──
    city_key = result["city"].lower().strip()
    # If extracted city is not in map, try to find a known city in the full address
    if city_key not in CITY_TO_STATE and result["address"]:
        addr_lower = result["address"].lower()
        for known_city in CITY_TO_STATE:
            if known_city in addr_lower:
                result["city"]  = known_city.title()
                city_key        = known_city
                break
    result["state"] = CITY_TO_STATE.get(city_key, "")

    # ── 3. Consignee name — in the consignee table first data column ──
    # Pattern: "Consignees/Reporting Officer and Quantity\n...\n1\n<Name>"
    person_match = re.search(
        r"Consignee[s]?.*?Reporting.*?Officer.*?\n.*?\n\s*1\s*\n([A-Z][a-zA-Z\s\.]{3,60})\n",
        pdf_text, re.IGNORECASE | re.DOTALL,
    )
    if person_match:
        result["contact_person"] = clean_text(person_match.group(1))
    else:
        # Alternative: look for name immediately after table header
        alt = re.search(
            r"(?:S\.No\.|S\.N\.|No\.)[^\n]*\n[^\n]*\n[^\n]*\n\s*1\s*([A-Z][a-zA-Z\s\.]{3,60})\n",
            pdf_text, re.IGNORECASE,
        )
        if alt:
            result["contact_person"] = clean_text(alt.group(1))

    # ── 4. Email ──
    email_match = re.search(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        pdf_text,
    )
    if email_match:
        result["contact_email"] = email_match.group().lower()

    # ── 5. Phone — 10-digit mobile or STD format ──
    phone_matches = re.findall(
        r"(?:Ph\.?|Tel\.?|Mobile\.?|Mob\.?|Contact\.?)[\s:\-]*(\+?[\d][\d\s\-]{8,14}\d)",
        pdf_text, re.IGNORECASE,
    )
    if phone_matches:
        # Clean first match
        ph = re.sub(r"[\s\-]", "", phone_matches[0])
        result["contact_phone"] = ph[:15]

    return result


def parse_bid_data(pdf_text: str) -> dict:
    """
    Original parser — kept for backward compatibility.
    Returns basic fields used by the scraper merge step.
    """
    d = {}

    m = re.search(r"GEM/\d{4}/B/\d+", pdf_text)
    d["bid_no"] = m.group() if m else ""

    m = re.search(
        r"(?:Total Quantity|कुल मा\S*)\s*[:\-]?\s*([\d,]+)",
        pdf_text[:5000], re.IGNORECASE,
    )
    d["quantity"] = clean_text(m.group(1)) if m else ""

    item_candidates = []
    m = re.search(
        r"(?:व\S+\s+\S+\s*/Item Category|Item Category)\s+([^\n]{5,300})",
        pdf_text[:8000], re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)

    m = re.search(
        r"Item Title\s*[:\-]?\s*([^\n]{5,300})",
        pdf_text[:8000], re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)

    m = re.search(r"व\S+\s+\S+\s+([^\n/]{5,300})/", pdf_text[:8000])
    if m:
        val = m.group(1).strip()
        if "which regular" not in val.lower():
            item_candidates.append(val)

    d["full_item_name"] = clean_text(item_candidates[0]) if item_candidates else ""

    m = re.search(
        r"(?:Department Name|विभाग का नाम|Department\s+(?:का|of))\s*[:\-]?\s*([^\n]{5,200})",
        pdf_text[:6000], re.IGNORECASE,
    )
    d["department"] = clean_text(m.group(1)) if m else ""

    start_date, end_date = _extract_dates(pdf_text)
    d["start_date"] = start_date
    d["end_date"]   = end_date

    m = re.search(r"Estimated\s+Bid\s+Value\s+(\d[\d,\.]+)", pdf_text, re.IGNORECASE)
    d["estimated_value"] = clean_text(m.group(1)) if m else ""

    m = re.search(
        r"Type of Bid\s+([\w][\w\s]+?)(?=\s{2,}|\s*(?:तकनीक|Primary|GEM/|\d{2}-\d{2}))",
        pdf_text, re.IGNORECASE,
    )
    d["bid_packet_type"] = clean_text(m.group(1)) if m else ""

    return d


def parse_bid_extended(pdf_text: str, pdf_path: str = "") -> dict:
    """
    Full extended parse — returns ALL fields needed for the
    unified tender format. Called from scraper after
    parse_bid_data() is already done; results are merged on top.
    """
    base = parse_bid_data(pdf_text)
    ext  = {}

    # ── Item Category → category, sub_category, product_name ──
    raw_cat = base.get("full_item_name", "")
    # Also try a direct regex from PDF for accuracy
    m = re.search(
        r"(?:व\S+\s+\S+\s*/Item Category|Item Category)\s+([^\n]{5,300})",
        pdf_text[:8000], re.IGNORECASE,
    )
    if m and "which regular" not in m.group(1).lower():
        raw_cat = clean_text(m.group(1))

    category, sub_category = split_item_category(raw_cat)
    ext["category"]     = category
    ext["sub_category"] = sub_category
    ext["product_name"] = infer_product_name(raw_cat)

    # ── Procurement type ──
    ext["procurement_type"] = infer_procurement_type(raw_cat, base.get("bid_packet_type", ""))

    # ── Authority from PDF (more reliable than card) ──
    # Try multiple label variants GeM uses
    authority_patterns = [
        r"(?:Department Name|विभाग का नाम)\s*[:\-]?\s*\n?([^\n]{3,200})",
        r"(?:Organisation Name|संगठन का नाम)\s*[:\-]?\s*\n?([^\n]{3,200})",
        r"(?:Office Name|काया?लय का नाम)\s*[:\-]?\s*\n?([^\n]{3,200})",
        r"(?:Ministry|Ministry.*?State Name|मं.*?रा.*?नाम)\s*[:\-]?\s*\n?([^\n]{3,200})",
    ]
    ext["authority"] = ""
    for pat in authority_patterns:
        for m in re.finditer(pat, pdf_text[:6000], re.IGNORECASE):
            val = clean_text(m.group(1))
            # Strip any leading slash or label fragment
            val = re.sub(r"^[/\\:\-\s]+", "", val).strip()
            # Skip placeholder values and skip values that are just label echoes
            low = val.lower()
            skip = {"na", "n/a", "not available", "nil", "organisation name",
                    "department name", "office name", "ministry"}
            if val and low not in skip and len(val) > 2:
                ext["authority"] = val
                break
        if ext["authority"]:
            break

    # ── Sector ──
    ext["sector"] = classify_sector(ext["authority"])

    # ── EMD (earnest_amount) ──
    # Try single-schedule pattern first, then multi-schedule
    emd_match = re.search(
        r"EMD Amount.*?(\d[\d,]+)",
        pdf_text, re.IGNORECASE,
    )
    ext["earnest_amount"] = clean_text(emd_match.group(1)) if emd_match else ""

    # ── Doc cost — try "Document Fee" / "Tender Fee" / "Bid Document Fee" ──
    doc_fee_match = re.search(
        r"(?:Document\s+Fee|Tender\s+Fee|Bid\s+Document\s+Fee|"
        r"Tender\s+Document\s+Cost|Document\s+Cost)\s*[:\-]?\s*(?:Rs\.?\s*)?(\d[\d,\.]+)",
        pdf_text, re.IGNORECASE,
    )
    ext["doc_cost"] = clean_text(doc_fee_match.group(1)) if doc_fee_match else ""

    # ── Open date (bid opening date) — already in base as start_date ──
    ext["open_date"] = base.get("start_date", "")

    # ── Search text — from item category, full string ──
    ext["search_text"] = clean_text(raw_cat)

    # ── Work description — assembled from known fields ──
    # Will be enriched in scraper.py where we have card_data too
    ext["work_desc_base"] = raw_cat  # scraper will build full work_desc

    # ── is_corrigendum — True if a RA number is present ──
    ra_match = re.search(r"GEM/\d{4}/R/\d+", pdf_text)
    ext["is_corrigendum"] = bool(ra_match)

    # ── Consignee block ──
    consignee = _extract_consignee_block(pdf_text)
    ext.update(consignee)

    # ── document_path — local PDF path ──
    ext["document_path"] = pdf_path or ""

    # ── tender_status — computed from end_date vs now ──
    # Will be set dynamically in scraper; default OPEN
    ext["tender_status"] = "OPEN"

    return {**base, **ext}


# =========================================================
# TENDER FORMAT ASSEMBLER
# Takes the merged scraper bid dict and returns a record
# shaped exactly like active_tenders-mittal-ind.json.
# Called from pipeline/scraper.py after all merging is done.
# =========================================================
def assemble_tender_record(bid: dict, page_url: str = "") -> dict:
    """
    Convert the internal scraper 'bid' dict into the unified
    tender format that matches active_tenders-mittal-ind.json.
    All date fields become {"$numberLong": "..."} objects.
    All money fields become {"$numberDecimal": "..."} objects.
    """
    end_date   = bid.get("end_date", "")
    start_date = bid.get("start_date", "")
    open_date  = bid.get("open_date", "") or start_date

    # ── tender_status: dynamic — OPEN if end_date is in the future ──
    status = "OPEN"
    try:
        if end_date:
            end_dt = datetime.strptime(end_date.strip()[:19], "%d-%m-%Y %H:%M:%S")
            if end_dt < datetime.now():
                status = "CLOSED"
    except Exception:
        pass

    # ── tender_type: Open Tender unless bid_type says Limited/Single ──
    bid_type_raw = bid.get("bid_type", "")
    if "limited" in bid_type_raw.lower():
        tender_type = "Limited Tender"
    elif "single" in bid_type_raw.lower():
        tender_type = "Single Tender"
    else:
        tender_type = "Open Tender"

    # ── work_desc — rich template ──
    authority    = bid.get("authority", bid.get("department", ""))
    full_item    = bid.get("full_item_name", "")
    product_name = bid.get("product_name", "")
    city         = bid.get("city", "")
    state        = bid.get("state", "")
    due_date_str = end_date[:10].replace("-", "-") if end_date else ""
    # Convert DD-MM-YYYY to YYYY-MM-DD for the display string
    try:
        due_display = datetime.strptime(due_date_str, "%d-%m-%Y").strftime("%Y-%m-%d")
    except Exception:
        due_display = due_date_str

    location_str = ", ".join(filter(None, [city, state]))
    work_desc = (
        f"{authority} has published Bids Are invited for {full_item}. "
        f"Last date of submission for this tender is {due_display}. "
        f"This is a {product_name} tender in {location_str}"
    ).strip()

    # ── tender_summary ──
    tender_summary = f"Bids Are invited for {full_item}" if full_item else ""

    # ── s3_document_path ──
    doc_url = bid.get("document_url", "")
    random_num = bid.get("random_number", _gen_random_number())
    s3_path = []
    if doc_url:
        s3_path = [{
            "download_id":           f"TD{random_num[:8]}-{random_num[8:14]}",
            "file_name":             "Tender Document",
            "tender_download_path":  doc_url,
        }]

    return {
        "tender_id":            bid.get("tender_id", _gen_tender_id()),
        "tender_no":            bid.get("bid_no", ""),
        "tender_reference_id":  bid.get("bid_no", ""),
        "tender_status":        status,
        "tender_type":          tender_type,
        "tender_value":         _decimal_obj(bid.get("estimated_value", "")),
        "tender_summary":       tender_summary,
        "work_desc":            work_desc,
        "authority":            authority,
        "category":             bid.get("category", ""),
        "sub_category":         bid.get("sub_category", ""),
        "product_name":         bid.get("product_name", ""),
        "sector":               bid.get("sector", ""),
        "procurement_type":     bid.get("procurement_type", ""),
        "bidding_type":         "Tender",
        "competition_type":     "NCB",
        "ownership":            "Government Departments",
        "platforms":            ["GEM"],
        "procurement_source":   page_url or "https://gem.gov.in/",
        "procurement_source_name": "Gem",
        "city":                 bid.get("city", ""),
        "state":                bid.get("state", ""),
        "country":              "India",
        "address":              bid.get("address", ""),
        "address_pin":          bid.get("address_pin", ""),
        "contact_person":       bid.get("contact_person", ""),
        "contact_email":        bid.get("contact_email", ""),
        "contact_phone":        bid.get("contact_phone", ""),
        "search_text":          bid.get("search_text", ""),
        "earnest_amount":       _decimal_obj(bid.get("earnest_amount", "")),
        "doc_cost":             _decimal_obj(bid.get("doc_cost", "")),
        "pub_date":             _ms_obj(start_date),
        "enter_date":           _ms_obj(start_date),
        "due_date":             _ms_obj(end_date),
        "org_subm_date":        _ms_obj(end_date),
        "open_date":            _ms_obj(open_date),
        "is_corrigendum":       bid.get("is_corrigendum", False),
        "tentative_date":       False,
        "attachment":           "Tender Document",
        "document_path":        bid.get("document_path", ""),
        "s3_document_path":     s3_path,
        "random_number":        random_num,
        "created_at":           _now_ms(),
        "updated_at":           _now_ms(),
    }


# =========================================================
# CARD HTML — RA NUMBER
# =========================================================
def get_ra_from_card(card) -> str:
    try:
        text = card.inner_text()
        m = re.search(r"GEM/\d{4}/R/\d+", text)
        return m.group() if m else ""
    except Exception as e:
        log.debug(f"RA card scrape: {e}")
    return ""


# =========================================================
# CARD HTML — PRODUCT TYPE
# =========================================================
def get_product_type_from_card(card, bid_type_name: str) -> str:
    from config.settings import PRODUCT_TYPE_MAP
    try:
        text = card.inner_text()
        m = re.search(
            r"(?:Type\s*[:\-]\s*)(Product|Service|Works|Goods)",
            text, re.IGNORECASE,
        )
        if m:
            return m.group(1).title()
        for kw in ["Service", "Product", "Works", "Goods"]:
            if re.search(rf"\b{kw}\b", text, re.IGNORECASE):
                return kw.title()
    except Exception as e:
        log.debug(f"Product type card: {e}")
    return PRODUCT_TYPE_MAP.get(bid_type_name, bid_type_name)


# =========================================================
# CARD HTML — DATES
# =========================================================
def get_dates_from_card(card) -> tuple[str, str]:
    start_date = ""
    end_date = ""
    try:
        text = card.inner_text()

        start_m = re.search(
            r"Start\s+Date\s*[:\-]?\s*(\d{2}-\d{2}-\d{4})\s+(\d{1,2}:\d{2})\s*(AM|PM)?",
            text, re.IGNORECASE,
        )
        if start_m:
            date_part = start_m.group(1)
            time_part = _to_24h(start_m.group(2), start_m.group(3) or "")
            start_date = f"{date_part} {time_part}"

        end_m = re.search(
            r"End\s+Date\s*[:\-]?\s*(\d{2}-\d{2}-\d{4})\s+(\d{1,2}:\d{2})\s*(AM|PM)?",
            text, re.IGNORECASE,
        )
        if end_m:
            date_part = end_m.group(1)
            time_part = _to_24h(end_m.group(2), end_m.group(3) or "")
            end_date = f"{date_part} {time_part}"

    except Exception as e:
        log.debug(f"Card date scrape error: {e}")

    return start_date, end_date


def _to_24h(time_str: str, ampm: str) -> str:
    try:
        parts = time_str.strip().split(":")
        hour = int(parts[0])
        mins = int(parts[1]) if len(parts) > 1 else 0
        ampm = ampm.strip().upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{mins:02d}:00"
    except Exception:
        return f"{time_str}:00"


# =========================================================
# CARD HTML — FULL ITEM NAME from POPOVER
# =========================================================
_POPOVER_ATTRS = ("data-content", "data-original-title", "title")


def _read_popover_attr(node) -> str:
    for attr in _POPOVER_ATTRS:
        try:
            val = node.get_attribute(attr)
            if val and val.strip():
                return _strip_html(val)
        except Exception:
            continue
    return ""


def get_full_item_name_from_card(card) -> str:
    try:
        items_node = card.locator(
            "xpath=.//*[contains(translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),"
            " 'items:')]"
        ).first
        if items_node and items_node.count() > 0:
            txt = _read_popover_attr(items_node)
            if txt:
                txt = re.sub(r"^\s*items?\s*:\s*", "", txt, flags=re.IGNORECASE)
                return txt

        for attr in _POPOVER_ATTRS:
            cand = card.locator(f"[{attr}]").first
            if cand and cand.count() > 0:
                val = cand.get_attribute(attr) or ""
                if val and len(val.strip()) > 15:
                    return _strip_html(val)
    except Exception as e:
        log.debug(f"Popover lookup failed: {e}")

    try:
        text = card.inner_text()
        m = re.search(r"Items?\s*:\s*(.+?)(?:\n|Quantity\s*:)", text, re.IGNORECASE | re.DOTALL)
        if m:
            return clean_text(m.group(1)).rstrip(".")
    except Exception:
        pass
    return ""


# =========================================================
# CARD HTML — QUANTITY
# =========================================================
def get_quantity_from_card(card) -> str:
    try:
        text = card.inner_text()
        m = re.search(r"Quantity\s*[:\-]?\s*([\d][\d,]*)", text, re.IGNORECASE)
        if m:
            return m.group(1).replace(",", "").strip()
    except Exception as e:
        log.debug(f"Quantity card scrape: {e}")
    return ""


# =========================================================
# CARD HTML — DEPARTMENT
# =========================================================
def get_department_from_card(card) -> str:
    try:
        text = card.inner_text()
        m = re.search(
            r"Department\s+Name(?:\s+And\s+Address)?\s*[:\-]?\s*\n?([^\n]{3,200})",
            text, re.IGNORECASE,
        )
        if m:
            return clean_text(m.group(1)).rstrip(",")
    except Exception as e:
        log.debug(f"Department card scrape: {e}")
    return ""


# =========================================================
# CARD HTML — BID NUMBER
# =========================================================
def get_bid_no_from_card(card) -> str:
    try:
        text = card.inner_text()
        m = re.search(r"GEM/\d{4}/B/\d+", text)
        return m.group() if m else ""
    except Exception:
        return ""


# =========================================================
# ONE-SHOT CARD DETAILS  (used by scraper)
# =========================================================
def get_card_details(card, bid_type_name: str) -> dict:
    start_date, end_date = get_dates_from_card(card)
    return {
        "bid_no":         get_bid_no_from_card(card),
        "ra_no":          get_ra_from_card(card),
        "product_type":   get_product_type_from_card(card, bid_type_name),
        "full_item_name": get_full_item_name_from_card(card),
        "quantity":       get_quantity_from_card(card),
        "department":     get_department_from_card(card),
        "start_date":     start_date,
        "end_date":       end_date,
    }
