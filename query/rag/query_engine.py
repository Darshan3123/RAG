# =========================================================
# rag/query_engine.py
# =========================================================
from __future__ import annotations
import re
from query.rag.vector_store import search, stats as vs_stats
from query.rag.llm import call_llm, _extract_item
from shared.config.settings import RAG_TOP_K, RAG_LLM_PROVIDER
from shared.utils.logger import get_logger

log = get_logger("query_engine")

EXIT_WORDS = {"quit", "exit", "q", "bye", "goodbye",
              "stop", "close", "end", "done", "ok bye",
              "/bye", "/quit", "/exit"}

_LIST_INTENT = re.compile(
    r"\b(all|every|list|show all|show me all|how many|total|"
    r"complete list|give me all|show me|display all|"
    r"what bids|which bids|bids do you have)\b",
    re.IGNORECASE,
)

_FOCUSED_INTENT = re.compile(
    r"\b(bid number|bid no|GEM/\d{4}|specific|"
    r"one bid|find bid|this bid)\b",
    re.IGNORECASE,
)

# ── Auto-filter lookup tables ─────────────────────────────────────────

_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand",
    "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan",
    "sikkim", "tamil nadu", "telangana", "tripura", "uttar pradesh",
    "uttarakhand", "west bengal", "delhi", "jammu and kashmir",
    "ladakh", "chandigarh", "puducherry",
}

_SECTORS = {
    "healthcare and medical":          "Healthcare and Medical",
    "defence and security":            "Defence and Security",
    "nuclear and atomic energy":       "Nuclear and Atomic Energy",
    "space and satellite":             "Space and Satellite",
    "energy - oil and gas":            "Energy - Oil and Gas",
    "energy - power":                  "Energy - Power",
    "information technology":          "Information Technology",
    "public administrative department":"Public Administrative Department",
    "law and justice":                 "Law and Justice",
    "education":                       "Education",
}

_STATUS_WORDS = {"open": "OPEN", "closed": "CLOSED", "active": "OPEN"}

# Procurement type: ONLY match explicit filter phrases, never generic descriptive words.
# "printing services tenders" should NOT trigger procurement_type=Services —
# "services" there describes the item, not the procurement category.
# Require explicit phrasing like "services tenders", "goods procurement", "works bids".
_PROC_PATTERNS = {
    r"\bservices?\s+(tender|bid|procurement|contract|only)\b":  "Services",
    r"\b(tender|bid|procurement|contract)\s+for\s+services?\b": "Services",
    r"\bgoods?\s+(tender|bid|procurement|only)\b":              "Goods",
    r"\b(tender|bid|procurement)\s+for\s+goods?\b":             "Goods",
    r"\bworks?\s+(tender|bid|procurement|contract|only)\b":     "Works",
    r"\b(tender|bid|procurement)\s+for\s+works?\b":             "Works",
    r"\bprocurement\s+type\s*[=:]\s*(services?|goods?|works?)\b": None,  # handled below
}

# ── State capitalisation map ──────────────────────────────────────────
_STATE_CANONICAL = {
    "tamil nadu":       "Tamil Nadu",
    "jammu and kashmir":"Jammu and Kashmir",
    "andhra pradesh":   "Andhra Pradesh",
    "arunachal pradesh":"Arunachal Pradesh",
    "himachal pradesh": "Himachal Pradesh",
    "madhya pradesh":   "Madhya Pradesh",
    "uttar pradesh":    "Uttar Pradesh",
    "west bengal":      "West Bengal",
}


def _auto_detect_filters(question: str, existing: dict | None) -> dict | None:
    """Extract state/sector/status/procurement from free-text and apply as filters."""
    q = question.lower()
    found: dict = {}

    for state in _STATES:
        if state in q:
            found["state"] = _STATE_CANONICAL.get(state, state.title())
            break

    for key, val in _SECTORS.items():
        if key in q:
            found["sector"] = val
            break

    for word, val in _STATUS_WORDS.items():
        if re.search(rf"\b{word}\b", q):
            found["status"] = val
            break

    # Procurement type — only trigger on explicit filter phrases, not descriptive words.
    # e.g. "services tenders" → Services, but "printing services" → no filter
    for pattern, val in _PROC_PATTERNS.items():
        m = re.search(pattern, q, re.IGNORECASE)
        if m:
            if val is None:
                # Extract from the match group for the "procurement type=X" pattern
                word = m.group(1).lower().rstrip("s")
                val = {"service": "Services", "good": "Goods", "work": "Works"}.get(word)
            if val:
                found["procurement_type"] = val
            break

    if not found:
        return existing

    merged = {**found}
    if existing:
        merged.update(existing)   # explicit filters override auto-detected

    return merged if merged != (existing or {}) else existing


def _smart_top_k(question: str, default_k: int) -> int:
    if _LIST_INTENT.search(question):
        return max(default_k, 15)
    if _FOCUSED_INTENT.search(question):
        return max(1, default_k // 2)
    return default_k


def _enrich_query(question: str, filters: dict | None) -> str:
    """Append filter values to query so dense + BM25 both see them."""
    if not filters:
        return question
    parts = [question.strip()]
    for k, v in filters.items():
        if v:
            parts.append(f"{k} {v}")
    return " ".join(parts)


def is_exit(text: str) -> bool:
    return text.strip().lower() in EXIT_WORDS


class QueryEngine:

    def __init__(self, top_k: int = RAG_TOP_K):
        self.top_k = top_k
        log.info(
            f"QueryEngine ready | "
            f"top_k={top_k} | "
            f"llm={RAG_LLM_PROVIDER or 'retrieval-only'}"
        )

    def ask(
        self,
        question: str,
        filters: dict | None = None,
        top_k: int | None = None,
    ) -> dict:
        k = top_k or _smart_top_k(question, self.top_k)

        # Auto-detect state/sector/status/procurement from question text
        filters = _auto_detect_filters(question, filters)

        enriched = _enrich_query(question, filters)
        if filters:
            log.info(f"Query: '{question}' → enriched: '{enriched}' | auto-filters={filters} | k={k}")
        else:
            log.info(f"Query: '{question}' | filters=None | k={k}")

        chunks = search(enriched, top_k=k, filters=filters)
        log.info(f"Retrieved {len(chunks)} unique bids")

        if not chunks:
            return {
                "question":    question,
                "answer":      "No relevant bids found for your query.",
                "sources":     [],
                "chunk_count": 0,
            }

        answer = call_llm(question, chunks)

        sources = [
            {
                "bid_no":          c.get("bid_no", ""),
                "bid_type":        c.get("bid_type", ""),
                "product_type":    c.get("product_type", ""),
                "full_item_name":  _extract_item(
                    c.get("chunk", ""),
                    c.get("full_item_name", ""),
                ),
                "department":      c.get("department", ""),
                "sector":          c.get("sector", ""),
                "state":           c.get("state", ""),
                "status":          c.get("status", ""),
                "end_date":        c.get("end_date", ""),
                "estimated_value": c.get("estimated_value", ""),
                "document_url":    c.get("document_url", ""),
                "relevance_score": c.get("score", 0),
            }
            for c in chunks
        ]

        return {
            "question":    question,
            "answer":      answer,
            "sources":     sources,
            "chunk_count": len(chunks),
        }

    def search_only(
        self,
        query: str,
        filters: dict | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        filters = _auto_detect_filters(query, filters)
        enriched = _enrich_query(query, filters)
        results = search(
            enriched,
            top_k=top_k or _smart_top_k(query, self.top_k),
            filters=filters,
        )
        for r in results:
            r["full_item_name"] = _extract_item(
                r.get("chunk", ""),
                r.get("full_item_name", ""),
            )
        return results

    def stats(self) -> dict:
        return vs_stats()

