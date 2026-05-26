# =========================================================
# rag/llm.py
# LLM provider wrapper — OpenAI or Ollama or retrieval-only
# Swap provider in config/settings.py: RAG_LLM_PROVIDER
# =========================================================
from __future__ import annotations
from config.settings import (
    RAG_LLM_PROVIDER,
    OPENAI_API_KEY, OPENAI_MODEL,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)
from utils.logger import get_logger

log = get_logger("llm")


# =========================================================
# SYSTEM PROMPT
# Instructs the LLM to answer ONLY from retrieved context
# =========================================================
SYSTEM_PROMPT = """You are a GeM (Government e-Marketplace) bid assistant.
You help procurement officers and vendors find and understand government tenders.

Answer ONLY using the bid context provided below.
If the answer is not in the context, say "I could not find that in the available bids."

Be concise. For bid listings, format as bullet points.
Always mention the Bid Number, Department, Item, End Date and Estimated Value when available.
"""


# =========================================================
# BUILD PROMPT
# Combines retrieved chunks + user question
# =========================================================
def build_prompt(question: str, chunks: list[dict]) -> str:
    if not chunks:
        context = "No relevant bids found."
    else:
        parts = []
        seen_bids = set()
        for i, c in enumerate(chunks, 1):
            bid_no = c.get("bid_no", "")
            if bid_no not in seen_bids:
                seen_bids.add(bid_no)
                parts.append(
                    f"--- Bid {i}: {bid_no} "
                    f"(score: {c.get('score', 0):.2f}) ---\n"
                    f"{c['chunk']}"
                )
        context = "\n\n".join(parts)

    return (
        f"RETRIEVED BID CONTEXT:\n"
        f"{context}\n\n"
        f"USER QUESTION:\n{question}"
    )


# =========================================================
# CALL LLM
# Returns answer string. Falls back gracefully on error.
# =========================================================
def call_llm(question: str, chunks: list[dict]) -> str:
    prompt = build_prompt(question, chunks)

    provider = RAG_LLM_PROVIDER.lower().strip()

    if provider == "openai":
        return _call_openai(prompt)
    elif provider == "ollama":
        return _call_ollama(prompt)
    else:
        # Retrieval-only mode — return formatted chunks, no LLM
        return _format_retrieval_only(question, chunks)


# =========================================================
# OPENAI
# =========================================================
def _call_openai(prompt: str) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system",  "content": SYSTEM_PROMPT},
                {"role": "user",    "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"OpenAI error: {e}")
        return f"[LLM error: {e}]"


# =========================================================
# OLLAMA  (local LLM — free, no API key)
# Install: https://ollama.com  then: ollama pull llama3
# =========================================================
def _call_ollama(prompt: str) -> str:
    try:
        import requests
        payload = {
            "model":  OLLAMA_MODEL,
            "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
            "stream": False,
            "options": {"temperature": 0.1},
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
        return f"[LLM error: {e}]"


# =========================================================
# RETRIEVAL-ONLY FALLBACK (no LLM)
# Returns a formatted summary of retrieved chunks
# =========================================================
def _format_retrieval_only(
    question: str,
    chunks: list[dict],
) -> str:
    if not chunks:
        return "No relevant bids found for your query."

    lines = [f"Top {len(chunks)} matching bids for: '{question}'\n"]
    seen  = set()
    rank  = 1

    for c in chunks:
        bid_no = c.get("bid_no", "N/A")
        if bid_no in seen:
            continue
        seen.add(bid_no)
        lines.append(
            f"{rank}. {bid_no}\n"
            f"   Type       : {c.get('bid_type','')}\n"
            f"   Department : {c.get('department','')}\n"
            f"   End Date   : {c.get('end_date','')}\n"
            f"   Est. Value : {c.get('estimated_value','')}\n"
            f"   URL        : {c.get('document_url','')}\n"
            f"   Relevance  : {c.get('score', 0):.2%}\n"
        )
        rank += 1

    return "\n".join(lines)
