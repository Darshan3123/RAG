# =========================================================
# rag/llm.py
# LLM provider — Ollama / OpenAI / retrieval-only fallback.
#
# IMPROVEMENT (this revision):
#   - Stronger system prompt: zero-hallucination, explicit
#     N/A handling, summary line only when ≥1 bid is shown.
#   - Score display now shows the cross-encoder rerank score
#     (the most meaningful number for the user).
#   - `_extract_item` understands the long popover string and
#     gracefully truncates to 200 chars.
# =========================================================
from __future__ import annotations
import re
from config.settings import (
    RAG_LLM_PROVIDER,
    OPENAI_API_KEY, OPENAI_MODEL,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)
from utils.logger import get_logger

log = get_logger("llm")

MAX_BIDS_IN_PROMPT = 8

SYSTEM_PROMPT = """You are an assistant for the Indian Government e-Marketplace (GeM) bid database.

# Hard rules
1. Use ONLY the bids listed under RETRIEVED BID CONTEXT. Never invent values.
2. If a field is empty or missing, write `N/A`.
3. If RETRIEVED BID CONTEXT is empty, answer exactly:
   "No matching bids were found in the indexed data."
4. Filter the listed bids to only those that *truly* answer the
   USER QUESTION (e.g. if asked about pumps, do not include
   tungsten-ball bids even if they are in the context).

# Output format (one bid per block, blank line between blocks)
Bid No    : <bid_no>
Item      : <full_item_name>
Dept      : <department>
Type      : <bid_type> / <product_type>
End Date  : <end_date>
Est. Value: <estimated_value> INR
URL       : <document_url>

After the list, write ONE short summary sentence describing
how many bids matched and any common theme. Never add anything else.
"""


def _extract_item(chunk_text: str, metadata_item: str) -> str:
    if metadata_item and len(metadata_item.strip()) > 3:
        cleaned = metadata_item.strip()
        if "which regular" not in cleaned.lower():
            return cleaned[:200]

    patterns = [
        r"Item\s*Category\s*[:\-]?\s*([A-Z][^\n]{3,200}?)(?:\s{2,}|\n|Bid)",
        r"Item\s*Title\s*[:\-]?\s*([A-Z][^\n]{3,200}?)(?:\s{2,}|\n|Bid)",
        r"व\S+\s+\S+\s*/Item Category\s+([^\n]{3,200})",
    ]
    for pat in patterns:
        m = re.search(pat, chunk_text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and "which regular" not in val.lower():
                return val[:200]

    return "N/A"


def _format_links_for_prompt(raw_links) -> str:
    if not raw_links:
        return "N/A"
    try:
        import json
        links = json.loads(raw_links) if isinstance(raw_links, str) else raw_links
        if not links or not isinstance(links, list):
            return "N/A"
        formatted = []
        for l in links[:5]:
            text = l.get("text", "Link")
            url = l.get("url", "")
            src = l.get("source", "bid").upper()
            if url:
                formatted.append(f"{text} ({url}) [{src}]")
        return ", ".join(formatted) if formatted else "N/A"
    except Exception:
        return "N/A"


def build_prompt(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return (
            "RETRIEVED BID CONTEXT:\n(empty)\n\n"
            f"USER QUESTION:\n{question}"
        )

    capped = chunks[:MAX_BIDS_IN_PROMPT]
    parts = []

    for c in capped:
        item = _extract_item(c.get("chunk", ""), c.get("full_item_name", ""))
        links_str = _format_links_for_prompt(c.get("pdf_hyperlinks"))
        block = (
            f"Bid No    : {c.get('bid_no', 'N/A')}\n"
            f"Item      : {item}\n"
            f"Quantity  : {c.get('quantity') or 'N/A'}\n"
            f"Dept      : {c.get('department') or 'N/A'}\n"
            f"Type      : {c.get('bid_type', 'N/A')} / {c.get('product_type', 'N/A')}\n"
            f"Start Date: {c.get('start_date') or 'N/A'}\n"
            f"End Date  : {c.get('end_date') or 'N/A'}\n"
            f"Est. Value: {c.get('estimated_value') or 'N/A'}\n"
            f"URL       : {c.get('document_url', 'N/A')}\n"
            f"Doc Links : {links_str}"
        )
        parts.append(f"--- BID ---\n{block}")

    context = "\n\n".join(parts)
    return (
        f"RETRIEVED BID CONTEXT:\n{context}\n\n"
        f"USER QUESTION:\n{question}"
    )


def call_llm(question: str, chunks: list[dict]) -> str:
    prompt = build_prompt(question, chunks)
    provider = (RAG_LLM_PROVIDER or "").lower().strip()

    if provider == "openai":
        return _call_openai(prompt)
    if provider == "ollama":
        return _call_ollama(prompt)
    return _format_retrieval_only(question, chunks)


def _call_openai(prompt: str) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.0,
            max_tokens=2048,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"OpenAI error: {e}")
        return _parse_prompt_as_table(prompt)


def _call_ollama(prompt: str) -> str:
    try:
        import requests
        payload = {
            "model":  OLLAMA_MODEL,
            "system": SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 1024,
                "num_ctx":     4096,
            },
        }
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        log.error(f"Ollama error: {e}")
        return _parse_prompt_as_table(prompt)


def _parse_prompt_as_table(prompt: str) -> str:
    blocks = re.findall(
        r"--- BID ---\n(.*?)(?=--- BID ---|USER QUESTION:)",
        prompt, re.DOTALL,
    )
    if not blocks:
        return "Could not parse bid data."
    lines = ["Retrieved bids:\n"]
    for b in blocks:
        lines.append(b.strip())
        lines.append("")
    return "\n".join(lines)


def _format_retrieval_only(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant bids found."

    lines = [f"Results for: '{question}'\n", "─" * 70]
    for i, c in enumerate(chunks, 1):
        item = _extract_item(c.get("chunk", ""), c.get("full_item_name", ""))
        score = c.get("score", 0)
        sem   = c.get("semantic_score", 0)
        bm    = c.get("bm25_score", 0)
        ce    = c.get("rerank_score", 0)
        lines.append(
            f"\n{i}. Bid No    : {c.get('bid_no', 'N/A')}\n"
            f"   Item      : {item}\n"
            f"   Quantity  : {c.get('quantity') or 'N/A'}\n"
            f"   Dept      : {c.get('department') or 'N/A'}\n"
            f"   Type      : {c.get('bid_type', 'N/A')}\n"
            f"   End Date  : {c.get('end_date') or 'N/A'}\n"
            f"   Est. Value: {c.get('estimated_value') or 'N/A'} INR\n"
            f"   URL       : {c.get('document_url', 'N/A')}\n"
            f"   Doc Links : {_format_links_for_prompt(c.get('pdf_hyperlinks'))}\n"
            f"   ──────────────────────────────────────\n"
            f"   Score        : {score:.2%}   "
            f"(rerank {ce:.2%} | dense {sem:.2%} | bm25 {bm:.2%})"
        )
    lines.append("\n" + "─" * 70)
    return "\n".join(lines)