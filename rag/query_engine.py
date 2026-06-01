# =========================================================
# rag/query_engine.py
# FIX: exit words checked before query, wider intent
#      patterns, /search shows full_item_name not chunk
# =========================================================
from __future__ import annotations
import re
from rag.vector_store import search, stats as vs_stats
from rag.llm import call_llm, _extract_item
from config.settings import RAG_TOP_K, RAG_LLM_PROVIDER
from utils.logger import get_logger

log = get_logger("query_engine")

# Exit words — checked BEFORE any query is made
EXIT_WORDS = {"quit", "exit", "q", "bye", "goodbye",
              "stop", "close", "end", "done", "ok bye",
              "/bye", "/quit", "/exit"}

# Broad listing intent → use higher top_k
_LIST_INTENT = re.compile(
    r"\b(all|every|list|show all|show me all|how many|total|"
    r"complete list|give me all|show me|display all|"
    r"what bids|which bids|bids do you have)\b",
    re.IGNORECASE,
)

# Focused lookup → use lower top_k
_FOCUSED_INTENT = re.compile(
    r"\b(bid number|bid no|GEM/\d{4}|specific|"
    r"one bid|find bid|this bid)\b",
    re.IGNORECASE,
)


def _smart_top_k(question: str, default_k: int) -> int:
    if _LIST_INTENT.search(question):
        return max(default_k, 15)
    if _FOCUSED_INTENT.search(question):
        return max(1, default_k // 2)
    return default_k


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
        log.info(f"Query: '{question}' | filters={filters} | k={k}")

        chunks = search(question, top_k=k, filters=filters)
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
        results = search(
            query,
            top_k=top_k or _smart_top_k(query, self.top_k),
            filters=filters,
        )
        # enrich with clean item name
        for r in results:
            r["full_item_name"] = _extract_item(
                r.get("chunk", ""),
                r.get("full_item_name", ""),
            )
        return results

    def stats(self) -> dict:
        return vs_stats()