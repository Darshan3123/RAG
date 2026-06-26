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
from shared.config.settings import TESSERACT_CMD
from shared.utils.logger import get_logger

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
    # Additional cities / districts commonly seen in GeM bids
    "hoshiarpur": "Punjab", "pathankot": "Punjab", "rupnagar": "Punjab",
    "gurdaspur": "Punjab", "fazilka": "Punjab", "moga": "Punjab",
    "rajauri": "Jammu and Kashmir", "poonch": "Jammu and Kashmir",
    "kathua": "Jammu and Kashmir", "udhampur": "Jammu and Kashmir",
    "reasi": "Jammu and Kashmir", "doda": "Jammu and Kashmir",
    "kishtwar": "Jammu and Kashmir", "ramban": "Jammu and Kashmir",
    "kinnaur": "Himachal Pradesh", "lahaul": "Himachal Pradesh",
    "spiti": "Himachal Pradesh", "bilaspur": "Himachal Pradesh",
    "una": "Himachal Pradesh", "hamirpur": "Himachal Pradesh",
    "sultanpur": "Uttar Pradesh", "amethi": "Uttar Pradesh",
    "raebareli": "Uttar Pradesh", "unnao": "Uttar Pradesh",
    "hardoi": "Uttar Pradesh", "sitapur": "Uttar Pradesh",
    "lakhimpur": "Uttar Pradesh", "kheri": "Uttar Pradesh",
    "paradip": "Odisha", "paradeep": "Odisha", "kendrapara": "Odisha",
    "jagatsinghpur": "Odisha", "angul": "Odisha", "dhenkanal": "Odisha",
    "koraput": "Odisha", "rayagada": "Odisha", "ganjam": "Odisha",
    "khammam": "Telangana", "nalgonda": "Telangana", "suryapet": "Telangana",
    "mahbubnagar": "Telangana", "sangareddy": "Telangana",
    "nagarkurnool": "Telangana", "wanaparthy": "Telangana",
    "bokaro": "Jharkhand", "giridih": "Jharkhand", "chatra": "Jharkhand",
    "palamu": "Jharkhand", "latehar": "Jharkhand", "garhwa": "Jharkhand",
    "kiriburu": "Jharkhand", "noamundi": "Jharkhand",
    "durg": "Chhattisgarh", "raigarh": "Chhattisgarh",
    "jagdalpur": "Chhattisgarh", "ambikapur": "Chhattisgarh",
    "navsari": "Gujarat", "valsad": "Gujarat", "bharuch": "Gujarat",
    "narmada": "Gujarat", "dahod": "Gujarat", "panchmahal": "Gujarat",
    "bangalore": "Karnataka", "bengaluru": "Karnataka",
    "mysore": "Karnataka", "hubli": "Karnataka",
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
    (r"\bit\b|software|hardware|computer|digital|data|network|cyber|nic|meity|e-governance", "Information Technology"),
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

def classify_sector(authority: str, item_category: str = "") -> str:
    """
    Map department/authority name → sector string.
    Item category is checked first when it contains a strong sector signal,
    so a printing item from an education dept gets 'Media and Printing',
    not 'Education'.
    """
    # Item category takes priority for a subset of unambiguous item-level signals
    _ITEM_SECTOR_RULES: list[tuple[str, str]] = [
        (r"printing|publication|press|media|broadcast|diary|booklet|brochure", "Media and Printing"),
        (r"medical|surgical|pharmaceutical|drug|medicine|hospital|health|biometric.*attendance|attendance.*biometric|nirs|electrode|somasensor", "Healthcare and Medical"),
        (r"software|it service|it project|erp|portal|website|network.*switch|cyber|managed service|desktop.*computer|storage.*tb|nvr|hdd|ssd|biometric(?!.*attendance)|application.*development|system.*integration", "Information Technology"),
        (r"food|catering|ration|grain|rice|wheat|canteen|jam|fruit|pasta|dal|rajma", "Food and Civil Supplies"),
        (r"textile|garment|uniform|fabric|linen|ribbon|nylon.*mm|gloves|mitten", "Textiles and Handicrafts"),
        (r"construction|civil work|building|renovation|road|bridge|sand.*sieve|river.*sand|aggregate|cement|rcc", "Roads and Infrastructure"),
        (r"power|electrical|transformer|switchgear|generator|ups|xlpe.*cable|cable.*kv|motor.*wiring|bearing.*angular|bearing.*ball", "Energy - Power"),
        (r"petroleum|oil|gas|fuel|refinery|cascade.*wl|lpg|cng", "Energy - Oil and Gas"),
        (r"defence|military|weapon|armament|ordnance|ammunition|insulation.*slab|fat.*insulation|satellite.*pin", "Defence and Security"),
        (r"hsfg.*bolt|bolt.*nut|ss.*tube|stainless.*tube|aluminoferric|alumino.*ferric|silica.*gel|bearing\s+\d", "Mining and Metals"),
    ]
    if item_category:
        item_lower = item_category.lower()
        for pattern, sector in _ITEM_SECTOR_RULES:
            if re.search(pattern, item_lower):
                return sector

    # Fall back to authority-based classification
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

    Special cases:
    - Multi-item list ("Item No 1 ... , Item no 2 ..."): keep entire
      string as category, sub_category = first item name only.
    - Single-item with ' - ' delimiter: standard split.
    """
    if not raw:
        return "", ""

    # ── Multi-item numbered list detection ──
    # Matches "Item No 1 ...", "Item no 2 ...", etc.
    if re.search(r"\bItem\s+[Nn]o\.?\s*\d+\b", raw):
        # Extract just the first item label as sub_category
        first = re.search(
            r"\bItem\s+[Nn]o\.?\s*\d+\s+([^,\.]{3,120})",
            raw,
        )
        sub = clean_text(first.group(1)) if first else ""
        return raw.strip(), sub

    # ── Standard: primary split on ' - ' ──
    if " - " in raw:
        parts = raw.split(" - ", 1)
        cat = parts[0].strip()
        sub = re.split(r"[;,]", parts[1])[0].strip()
        return cat, sub

    # ── Fallback: split on ';' or ',' ──
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

    # ── Prefer the Consignee section when present, else first 8 KB ──
    consignee_hdr = re.search(
        r"Consignees?/Reporting\s+Officer",
        pdf_text, re.IGNORECASE,
    )
    if consignee_hdr:
        start_idx   = max(consignee_hdr.start() - 200, 0)
        search_text = pdf_text[start_idx: start_idx + 8000]
    else:
        search_text = pdf_text[:8000]

    # ── 1. Find a 6-digit PIN followed by address text,
    #        but skip any match that sits inside a bank / EMD line ──
    _BANK_CONTEXT_MARKERS = ("A/c No", "Account No", "IFSC", "Bank Name",
                             "EMD Amount", "NEFT", "RTGS", "Account Number")

    addr_match = None
    for m in re.finditer(r"(\d{6}),([^\n]{10,250})", search_text):
        # Examine ±80 chars around the match for bank markers
        ctx_start = max(0, m.start() - 80)
        ctx_end   = min(len(search_text), m.end() + 80)
        context   = search_text[ctx_start:ctx_end]
        if any(marker in context for marker in _BANK_CONTEXT_MARKERS):
            continue   # this looks like a bank/IFSC line, skip it
        addr_match = m
        break

    if addr_match:
        pin  = addr_match.group(1)
        rest = clean_text(addr_match.group(2))
        result["address"]     = f"{pin},{rest}"
        result["address_pin"] = pin

    # ── 1b. Extract city from "***...***CITYNAME" pattern (used when no named contact) ──
    # e.g. "***********\n***********BANGALORE\n1\nN/A"
    star_city_m = re.search(
        r"\*{5,}\s*\n\s*\*{5,}([A-Za-z][A-Za-z\s]{2,40})\s*\n",
        search_text, re.IGNORECASE,
    )
    if star_city_m:
        star_city = star_city_m.group(1).strip().title()
        if not result["city"]:
            star_lower = star_city.lower()
            if star_lower in CITY_TO_STATE:
                result["city"]  = star_city
                result["state"] = CITY_TO_STATE[star_lower]
            else:
                for known_city in sorted(CITY_TO_STATE.keys(), key=len, reverse=True):
                    if known_city in star_lower or star_lower in known_city:
                        result["city"]  = known_city.title()
                        result["state"] = CITY_TO_STATE[known_city]
                        break
                else:
                    result["city"] = star_city  # store as-is even if not in map

    # ── 2. Try to find city by matching known cities in address context ──
    if addr_match:
        start = max(0, addr_match.start() - 200)
        end   = min(len(search_text), addr_match.end() + 200)
        addr_context = search_text[start:end].lower()
    else:
        addr_context = search_text[:3000].lower()

    # Sort by length descending so "new delhi" matches before "delhi"
    for known_city in sorted(CITY_TO_STATE.keys(), key=len, reverse=True):
        if known_city in addr_context:
            result["city"] = known_city.title()
            break

    # ── 3. State from city map ──
    city_key = result["city"].lower().strip()
    # If not found yet, try a second pass over the address string only
    if city_key not in CITY_TO_STATE and result["address"]:
        addr_lower = result["address"].lower()
        for known_city in CITY_TO_STATE:
            if known_city in addr_lower:
                result["city"] = known_city.title()
                city_key       = known_city
                break
    result["state"] = CITY_TO_STATE.get(city_key, "")

    # ── 3b. If state still empty, try matching state names directly in address ──
    if not result["state"]:
        _ALL_STATES = [
            "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
            "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
            "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra",
            "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
            "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
            "Uttar Pradesh", "Uttarakhand", "West Bengal",
            "Jammu and Kashmir", "Ladakh", "Delhi", "Chandigarh", "Puducherry",
            "Andaman and Nicobar Islands",
            "Dadra and Nagar Haveli and Daman and Diu",
        ]
        addr_search = (result["address"] + " " + addr_context).lower()
        for state_name in _ALL_STATES:
            if state_name.lower() in addr_search:
                result["state"] = state_name
                # Also try to pick city from address words before the state name
                idx = addr_search.find(state_name.lower())
                before = addr_search[max(0, idx - 120):idx]
                for known_city in sorted(CITY_TO_STATE.keys(), key=len, reverse=True):
                    if known_city in before and CITY_TO_STATE[known_city] == state_name:
                        result["city"] = known_city.title()
                        break
                # If still no city, extract last meaningful word before state name
                if not result["city"]:
                    words = re.findall(r"[a-z]{4,}", before)
                    if words:
                        result["city"] = words[-1].title()
                break

    # ── 4. Consignee name — find the consignee section then extract name ──
    # PDF structure (after clean_text collapses newlines):
    #   "...S.N o. ... 1 Firstname Lastname 834006,Address..."
    # The name sits between the row number "1 " and the 6-digit PIN.
    # Also works on raw text where newlines are preserved.
    person_match = None

    # Strategy A: name between row-number "1" and the 6-digit PIN
    # Works on collapsed text: "... 1 Firstname Lastname 834006,..."
    # Also works on raw text:  "...\n1\nFirstname Lastname\n834006,..."
    if addr_match:
        pre_pin = search_text[max(0, addr_match.start() - 300): addr_match.start()]
        pm = (
            re.search(r"\b1\s*\n([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,4})\s*\n", pre_pin)
            or re.search(r"\b1\s+([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){0,3})\s+\d{6}", pre_pin)
        )
        if pm:
            name = clean_text(pm.group(1))
            # Skip placeholder values
            if name.upper() not in ("N/A", "NA", "NIL", "NOT AVAILABLE"):
                result["contact_person"] = name

    # Strategy B (raw text only): table row "\n 1\n<Name>\n"
    if not result["contact_person"]:
        consignee_section_m = re.search(
            r"Consignee[s]?[^\n]{0,80}Reporting[^\n]{0,80}Officer",
            search_text, re.IGNORECASE,
        )
        if consignee_section_m:
            window = search_text[consignee_section_m.end():consignee_section_m.end() + 500]
            pm = re.search(r"\n\s*1\s*\n([A-Z][a-zA-Z\s\.]{3,60})\n", window)
            if pm:
                name = clean_text(pm.group(1))
                if name.upper() not in ("N/A", "NA", "NIL"):
                    result["contact_person"] = name

    # Strategy C: S.No. table fallback (raw text)
    if not result["contact_person"]:
        sno_m = re.search(r"(?:S\.No\.|S\.N\.|No\.)[^\n]*\n", search_text, re.IGNORECASE)
        if sno_m:
            window = search_text[sno_m.end():sno_m.end() + 400]
            alt = re.search(r"(?:[^\n]*\n){0,3}\s*1\s*([A-Z][a-zA-Z\s\.]{3,60})\n", window)
            if alt:
                name = clean_text(alt.group(1))
                if name.upper() not in ("N/A", "NA", "NIL"):
                    result["contact_person"] = name

    # ── 5. Email ──
    email_match = re.search(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        search_text,
    )
    if email_match:
        result["contact_email"] = email_match.group().lower()

    # ── 6. Phone — 10-digit mobile or STD format ──
    phone_matches = re.findall(
        r"(?:Ph\.?|Tel\.?|Mobile\.?|Mob\.?|Contact\.?)[\s:\-]*(\+?[\d][\d\s\-]{8,14}\d)",
        search_text, re.IGNORECASE,
    )
    if phone_matches:
        ph = re.sub(r"[\s\-]", "", phone_matches[0])
        result["contact_phone"] = ph[:15]

    return result


# Phrases that signal the end of the true item name — anything after these
# belongs to relaxation/policy explanatory text, not the category itself.
_ITEM_TAIL_STOPS = [
    "mse relaxation for years of experience and turnover",
    "startup relaxation for years of experience and turnover",
    "mse relaxation",
    "startup relaxation",
    "local supplier",
    "make in india",
    "purchase preference",
    "class-i local",
    "class-ii local",
    "bid security",
    "technical specification",
    "as per the tech",
    "delivery period",
    "warranty period",
]


def _trim_item_tail(val: str) -> str:
    """
    Strip trailing policy/relaxation text that sometimes bleeds into
    the extracted item category string.
    """
    if not val:
        return val
    lower = val.lower()
    cut = len(val)
    for kw in _ITEM_TAIL_STOPS:
        idx = lower.find(kw)
        if idx != -1 and idx < cut:
            cut = idx
    return val[:cut].strip(" ,;-")


def _extract_item_category(pdf_text: str) -> str:
    """
    Extract the full item category text, which may span multiple lines.
    The section ends at the next major header (GeMARPTS, Searched, Bid Number, etc.)
    Collapses newlines into spaces and returns the full joined text.
    """
    # Primary: multi-line capture until the next section header
    m = re.search(
        r"(?:[^\n]*/)?Item\s+Category\s*\n"   # label on its own line
        r"(.*?)"                                # value (may span lines)
        r"(?=\nGeMARPTS|\nSearched\s+String|\n\x01|\nBid\s+Number|\nBid\s+No|\nDated:|\Z)",
        pdf_text[:10000], re.IGNORECASE | re.DOTALL,
    )
    if m:
        val = clean_text(m.group(1))
        val = _trim_item_tail(val)
        if val and "which regular" not in val.lower() and len(val) > 5:
            return val

    # Fallback: single-line value on same line as label (older PDF layout)
    m = re.search(
        r"(?:[^\n]*/)?Item\s+Category\s*[:\-]\s*([^\n]{5,300})",
        pdf_text[:8000], re.IGNORECASE,
    )
    if m:
        val = _trim_item_tail(m.group(1).strip())
        if "which regular" not in val.lower():
            return val

    # Last resort: Item Title
    m = re.search(
        r"Item Title\s*[:\-]?\s*([^\n]{5,300})",
        pdf_text[:8000], re.IGNORECASE,
    )
    if m:
        val = _trim_item_tail(m.group(1).strip())
        if "which regular" not in val.lower():
            return val

    return ""


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

    d["full_item_name"] = _extract_item_category(pdf_text)

    m = re.search(
        r"(?:[^\n]*/)?Department\s+Name\s*\n([^\n]{5,200})",
        pdf_text[:6000], re.IGNORECASE,
    ) or re.search(
        r"(?:Department Name|Department\s+(?:का|of))\s*[:\-]\s*([^\n]{5,200})",
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
    log.info("  [parser] Starting parse_bid_extended...")
    base = parse_bid_data(pdf_text)
    log.info("  [parser] Base parsing complete")
    ext  = {}

    # ── Item Category → category, sub_category, product_name ──
    log.info("  [parser] Extracting item category...")
    raw_cat = base.get("full_item_name", "")
    # Re-extract using the multi-line helper for accuracy
    extracted = _extract_item_category(pdf_text)
    if extracted:
        raw_cat = extracted

    category, sub_category = split_item_category(raw_cat)
    ext["category"]     = category
    ext["sub_category"] = sub_category
    ext["product_name"] = infer_product_name(raw_cat)
    log.info(f"  [parser] Category: {category[:50]}...")

    # ── Procurement type ──
    log.info("  [parser] Determining procurement type...")
    ext["procurement_type"] = infer_procurement_type(raw_cat, base.get("bid_packet_type", ""))

    # ── Authority from PDF (more reliable than card) ──
    log.info("  [parser] Extracting authority...")
    # GeM PDFs put the value on the NEXT line after the label, e.g.:
    #   "वभाग का नाम/Department Name\nSteel Authority Of India Limited"
    # Pattern: match the label line, then capture the very next non-empty line.
    _LABEL_NEXT_LINE = [
        r"(?:[^\n]*/)?Department\s+Name\s*\n([^\n]{3,200})",
        r"(?:[^\n]*/)?Organisation\s+Name\s*\n([^\n]{3,200})",
        r"(?:[^\n]*/)?Organization\s+Name\s*\n([^\n]{3,200})",
    ]
    _SKIP_AUTHORITY = {
        "na", "n/a", "not available", "nil",
        "organisation name", "organization name",
        "department name", "office name", "ministry",
    }
    ext["authority"] = ""
    for pat in _LABEL_NEXT_LINE:
        for m in re.finditer(pat, pdf_text[:6000], re.IGNORECASE):
            val = clean_text(m.group(1))
            val = re.sub(r"^[/\\:\-\s]+", "", val).strip()
            if val and val.lower() not in _SKIP_AUTHORITY and len(val) > 2:
                ext["authority"] = val
                break
        if ext["authority"]:
            break
    # Final fallback: inline same-line pattern (older PDF layout OR collapsed text)
    if not ext["authority"]:
        _INLINE_PATTERNS = [
            r"/Department\s+Name\s+([A-Z][^\n/]{3,150}?)(?:\s+[^\s/]{0,30}/|\s*$)",
            r"/Organisation\s+Name\s+([A-Z][^\n/]{3,150}?)(?:\s+[^\s/]{0,30}/|\s*$)",
            r"Department\s+Name\s*[:\-]\s*([^\n]{3,200})",
            r"Organisation\s+Name\s*[:\-]\s*([^\n]{3,200})",
        ]
        for pat in _INLINE_PATTERNS:
            m = re.search(pat, pdf_text[:6000], re.IGNORECASE)
            if m:
                val = clean_text(m.group(1))
                val = re.sub(r"^[/\\:\-\s]+", "", val).strip()
                if val and val.lower() not in _SKIP_AUTHORITY and len(val) > 2:
                    ext["authority"] = val
                    break
    log.info(f"  [parser] Authority: {ext['authority'][:50]}...")

    # ── Sector ──
    log.info("  [parser] Classifying sector...")
    ext["sector"] = classify_sector(ext["authority"], item_category=raw_cat)

    # ── EMD (earnest_amount) ──
    log.info("  [parser] Extracting EMD amount...")
    # Handles plain "EMD Amount 17500", Hindi prefix, and multiline layouts
    emd_match = re.search(
        r"(?:EMD\s*Amount|ईएमड[^\n]{0,15}Amount|Earnest\s+Money\s+Deposit)[^\d]{0,30}(\d[\d,]*)",
        pdf_text, re.IGNORECASE | re.DOTALL,
    )
    ext["earnest_amount"] = clean_text(emd_match.group(1)) if emd_match else ""

    # ── Doc cost — try "Document Fee" / "Tender Fee" / "Bid Document Fee" ──
    log.info("  [parser] Extracting document cost...")
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
    log.info("  [parser] Checking for corrigendum...")
    ra_match = re.search(r"GEM/\d{4}/R/\d+", pdf_text)
    ext["is_corrigendum"] = bool(ra_match)

    # ── Consignee block ──
    log.info("  [parser] Extracting consignee details...")
    consignee = _extract_consignee_block(pdf_text)
    ext.update(consignee)
    log.info(f"  [parser] Consignee city: {consignee.get('city', 'N/A')}, state: {consignee.get('state', 'N/A')}")

    # ── document_path — local PDF path ──
    ext["document_path"] = pdf_path or ""

    # ── Organization name and Office name — structured fields for filtering ──
    # GeM PDFs: in RAW text, value is on next line after label.
    # In STORED full_pdf_text (clean_text applied), newlines → spaces, so
    # value is inline: "...Hindi.../Organisation Name Bokaro Steel Plant Hindi..."
    _ORG_SKIP = {"na", "n/a", "nil", "not available", "organisation name", "organization name"}
    _OFF_SKIP  = {"na", "n/a", "nil", "not available", "office name"}

    # Try next-line pattern first (raw PDF text), then inline (collapsed text)
    org_m = (
        re.search(r"(?:[^\n]*/)?Organisation\s+Name\s*\n([^\n]{3,200})", pdf_text[:6000], re.IGNORECASE)
        or re.search(r"(?:[^\n]*/)?Organization\s+Name\s*\n([^\n]{3,200})", pdf_text[:6000], re.IGNORECASE)
        or re.search(r"/Organisation\s+Name\s+([A-Z][^\n/]{3,150}?)(?:\s+[^\s/]{0,30}/|\s*$)", pdf_text[:6000], re.IGNORECASE)
        or re.search(r"/Organization\s+Name\s+([A-Z][^\n/]{3,150}?)(?:\s+[^\s/]{0,30}/|\s*$)", pdf_text[:6000], re.IGNORECASE)
    )
    if org_m:
        val = clean_text(org_m.group(1))
        ext["organization_name"] = val if val.lower() not in _ORG_SKIP and len(val) > 2 else ""
    else:
        ext["organization_name"] = ext.get("authority", "")

    off_m = (
        re.search(r"(?:[^\n]*/)?Office\s+Name\s*\n([^\n]{3,200})", pdf_text[:6000], re.IGNORECASE)
        or re.search(r"/Office\s+Name\s+([A-Z0-9][^\n/]{2,150}?)(?:\s+[^\s/]{0,30}/|\s*$)", pdf_text[:6000], re.IGNORECASE)
    )
    if off_m:
        val = clean_text(off_m.group(1))
        ext["office_name"] = val if val.lower() not in _OFF_SKIP and len(val) > 1 else ""
    else:
        ext["office_name"] = ""

    # ── tender_status — computed from end_date vs now ──
    # Will be set dynamically in scraper; default OPEN
    ext["tender_status"] = "OPEN"

    log.info("  [parser] parse_bid_extended complete")
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

    # For multi-item bids, build a compact item description
    if full_item and re.search(r"\bItem\s+[Nn]o\.?\s*\d+\b", full_item):
        item_labels = re.findall(
            r"\bItem\s+[Nn]o\.?\s*\d+\s+(.*?)(?:\s+as\s+per\s+the\s+tech|\s*,\s*Item|\Z)",
            full_item,
        )
        count = len(re.findall(r"\bItem\s+[Nn]o\.?\s*\d+\b", full_item))
        if item_labels:
            item_desc = "; ".join(m.strip().rstrip(".") for m in item_labels)
            item_display = f"{count} items: {item_desc}"
        else:
            item_display = full_item[:300]
    else:
        item_display = full_item

    work_desc = (
        f"{authority} has published Bids Are invited for {item_display}. "
        f"Last date of submission for this tender is {due_display}. "
        f"This is a {product_name} tender in {location_str}"
    ).strip()

    # ── tender_summary ──
    # For multi-item bids, show a compact summary instead of the full raw list
    if full_item and re.search(r"\bItem\s+[Nn]o\.?\s*\d+\b", full_item):
        # Extract short labels before "as per the technical specification..."
        item_labels = re.findall(
            r"\bItem\s+[Nn]o\.?\s*\d+\s+(.*?)(?:\s+as\s+per\s+the\s+tech|\s*,\s*Item|\Z)",
            full_item,
        )
        count = len(re.findall(r"\bItem\s+[Nn]o\.?\s*\d+\b", full_item))
        if item_labels:
            shown = item_labels[:5]
            summary_items = "; ".join(m.strip().rstrip(".") for m in shown)
            tender_summary = f"Bids invited for {count} items: {summary_items}"
            if count > 5:
                tender_summary += f" (+{count-5} more)"
        else:
            tender_summary = f"Bids Are invited for {full_item[:200]}"
    else:
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
        text = card.inner_text(timeout=5_000)
        m = re.search(r"GEM/\d{4}/R/\d+", text)
        return m.group() if m else ""
    except Exception as e:
        log.debug(f"RA card scrape: {e}")
    return ""


# =========================================================
# CARD HTML — PRODUCT TYPE
# =========================================================
def get_product_type_from_card(card, bid_type_name: str) -> str:
    from shared.config.settings import PRODUCT_TYPE_MAP
    try:
        text = card.inner_text(timeout=5_000)
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
        text = card.inner_text(timeout=5_000)

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
    # ── Strategy 1: scan popover attributes on all descendant nodes ──
    # Avoid expensive XPath translate() — iterate over known attribute names
    # directly instead of querying the full subtree by text.
    try:
        for attr in _POPOVER_ATTRS:
            try:
                nodes = card.locator(f"[{attr}]")
                count = nodes.count()
                for idx in range(min(count, 10)):  # cap to avoid long loops
                    try:
                        val = nodes.nth(idx).get_attribute(attr, timeout=2_000) or ""
                        val = val.strip()
                        if len(val) > 15:
                            cleaned = _strip_html(val)
                            cleaned = re.sub(r"^\s*items?\s*:\s*", "", cleaned, flags=re.IGNORECASE)
                            return cleaned
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        log.debug(f"Popover attr scan failed: {e}")

    # ── Strategy 2: plain text parse from inner_text() ──
    try:
        text = card.inner_text(timeout=5_000)
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
        text = card.inner_text(timeout=5_000)
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
        text = card.inner_text(timeout=5_000)
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
        text = card.inner_text(timeout=5_000)
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



# =========================================================
# PDF INTELLIGENCE EXTRACTOR
# Parses granular fields from full_pdf_text that are NOT
# present in the top-level bid metadata:
#   - Bid timeline constraints
#   - Bidder eligibility & relaxation rules
#   - Reverse Auction (RA) rules
#   - Financial safeguards (EMD + ePBG)
#   - Itemised consignee/delivery schedule
#   - MII and MSE policy preferences
# =========================================================


def extract_pdf_intelligence(pdf_text: str, product_type: str = "Product") -> dict:
    """
    Routes to the appropriate parser based on the product type.
    """
    if "Product" in product_type:
        from scraper.core.parsers.product_parser import parse_product_intelligence
        return parse_product_intelligence(pdf_text)
    else:
        from scraper.core.parsers.service_parser import parse_service_intelligence
        return parse_service_intelligence(pdf_text)
