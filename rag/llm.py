# =========================================================
# rag/llm.py
# LLM provider — with hybrid score display
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

SYSTEM_PROMPT = """You are a GeM (Government e-Marketplace) bid assistant.
Answer ONLY using the structured bid data in RETRIEVED BID CONTEXT.

Output each bid in this EXACT format, no variation:

Bid No    : <value>
Item      : <value>
Dept      : <value>
Type      : <value>
End Date  : <value>
Est. Value: <value> INR
URL       : <value>

- Separate bids with a blank line.
- If a field value is blank, write N/A.
- Do NOT add commentary between bids.
- After the list, write one short summary sentence.
- Never hallucinate values not in the context.
"""


def _extract_item(chunk_text: str, metadata_item: str) -> str:
    if metadata_item and len(metadata_item) > 3:
        if "which regular" not in metadata_item:
            return metadata_item.strip()

    patterns = [
        r"Item\s*Category\s*[:\-]?\s*([A-Z][^\n]{3,60}?)(?:\s{2,}|\n|Bid)",
        r"Item\s*Title\s*[:\-]?\s*([A-Z][^\n]{3,60}?)(?:\s{2,}|\n|Bid)",
        r"व\S+\s+\S+\s*/Item Category\s+([^\n]{3,60})",
    ]
    for pat in patterns:
        m = re.search(pat, chunk_text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and "which regular" not in val:
                return val

    return "N/A"


def build_prompt(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return (
            "RETRIEVED BID CONTEXT:\nNo relevant bids found.\n\n"
            f"USER QUESTION:\n{question}"
        )

    capped = chunks[:MAX_BIDS_IN_PROMPT]
    parts  = []

    for c in capped:
        item = _extract_item(
            c.get("chunk", ""),
            c.get("full_item_name", ""),
        )
        block = (
            f"Bid No    : {c.get('bid_no', 'N/A')}\n"
            f"Item      : {item}\n"
            f"Dept      : {c.get('department', 'N/A')}\n"
            f"Type      : {c.get('bid_type', 'N/A')} / {c.get('product_type', 'N/A')}\n"
            f"End Date  : {c.get('end_date', 'N/A')}\n"
            f"Est. Value: {c.get('estimated_value', 'N/A')}\n"
            f"URL       : {c.get('document_url', 'N/A')}"
        )
        parts.append(f"--- BID ---\n{block}")

    context = "\n\n".join(parts)
    return (
        f"RETRIEVED BID CONTEXT:\n{context}\n\n"
        f"USER QUESTION:\n{question}"
    )


def call_llm(question: str, chunks: list[dict]) -> str:
    prompt   = build_prompt(question, chunks)
    provider = RAG_LLM_PROVIDER.lower().strip()

    if provider == "openai":
        return _call_openai(prompt)
    elif provider == "ollama":
        return _call_ollama(prompt)
    else:
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
        return _format_retrieval_only("", [])


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
            timeout=90,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        log.error(f"Ollama error: {e}")
        return _parse_prompt_as_table(prompt)


def _parse_prompt_as_table(prompt: str) -> str:
    blocks = re.findall(
        r"--- BID ---\n(.*?)(?=--- BID ---|USER QUESTION:)",
        prompt,
        re.DOTALL,
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
        item = _extract_item(
            c.get("chunk", ""),
            c.get("full_item_name", ""),
        )
        # FIX: show hybrid score breakdown
        score = c.get("score", 0)
        sem = c.get("semantic_score", 0)
        kw = c.get("keyword_score", 0)
        
        lines.append(
            f"\n{i}. Bid No    : {c.get('bid_no', 'N/A')}\n"
            f"   Item      : {item}\n"
            f"   Dept      : {c.get('department', 'N/A')}\n"
            f"   Type      : {c.get('bid_type', 'N/A')}\n"
            f"   End Date  : {c.get('end_date', 'N/A')}\n"
            f"   Est. Value: {c.get('estimated_value', 'N/A')} INR\n"
            f"   URL       : {c.get('document_url', 'N/A')}\n"
            f"   ──────────────────────────────────────\n"
            f"   Overall Score : {score:.2%}\n"
            f"     • Semantic (60%)  : {sem:.2%}\n"
            f"     • Keyword  (40%)  : {kw:.2%}"
        )
    lines.append("\n" + "─" * 70)
    return "\n".join(lines)