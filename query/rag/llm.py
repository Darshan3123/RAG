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
from shared.config.settings import (
    RAG_LLM_PROVIDER,
    OPENAI_API_KEY, OPENAI_MODEL,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)
from shared.utils.logger import get_logger

log = get_logger("llm")

MAX_BIDS_IN_PROMPT = 8

SYSTEM_PROMPT = """You are an intelligent, conversational assistant for the Indian Government e-Marketplace (GeM) bid database.

# Instructions:
1. Act like a helpful AI (like ChatGPT). Speak naturally and conversationally.
2. The user will ask a question, and you will be provided with a list of retrieved bids in the RETRIEVED BID CONTEXT.
3. Your goal is to summarize the matching bids naturally in a readable, well-formatted response. You can use bullet points, bold text, and neat spacing to make the data easy to read.
4. ALWAYS include the 'Bid No' and 'URL' so the user knows where to find the bid.
5. If the user asks a specific question (e.g., "what is the most expensive one?"), answer that question directly using the context.
6. ONLY use the information provided in the context. Do not invent or hallucinate data. If the context is empty, politely inform the user that no matching bids were found.
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


def _extract_required_docs(chunk_text: str) -> str:
    """Extract required documents list from raw text if present."""
    if not chunk_text:
        return "N/A"
    pat = r"Document required from seller\s*(.*?)(?:\*In case|क्या आप|Do you want|$)"
    m = re.search(pat, chunk_text, re.IGNORECASE | re.DOTALL)
    if m:
        val = m.group(1).strip()
        val = re.sub(r"\s+", " ", val)
        if len(val) > 2 and len(val) < 1000:
            return val
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
        raw_text = c.get("chunk", "")
        item = _extract_item(raw_text, c.get("full_item_name", ""))
        req_docs = _extract_required_docs(raw_text)
        chunk_text = raw_text.replace('\n', ' ')[:1000]
        
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
            f"Req. Docs : {req_docs}\n"
            f"Text Snippet: {chunk_text}"
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
            timeout=300,
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
            f"   ──────────────────────────────────────\n"
            f"   Score        : {score:.2%}   "
            f"(rerank {ce:.2%} | dense {sem:.2%} | bm25 {bm:.2%})"
        )
    lines.append("\n" + "─" * 70)
    return "\n".join(lines)

def call_llm_direct(prompt: str, system: str) -> str:
    provider = (RAG_LLM_PROVIDER or "").lower().strip()
    if provider == "openai":
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.0,
                max_tokens=50,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return ""
    elif provider == "ollama":
        try:
            import requests
            payload = {
                "model":  OLLAMA_MODEL,
                "system": system,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": 50,
                },
            }
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception:
            return ""
    return ""
