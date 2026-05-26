# =========================================================
# rag/query_engine.py
# Public interface for the RAG pipeline
#
# Usage:
#   from rag.query_engine import QueryEngine
#   engine = QueryEngine()
#   result = engine.ask("Show me IT equipment bids above 10 lakh")
#   result = engine.ask("Service bids in Health department",
#                       filters={"product_type": "Service"})
# =========================================================
from __future__ import annotations
from rag.vector_store import search, stats as vs_stats
from rag.llm import call_llm
from config.settings import RAG_TOP_K, RAG_LLM_PROVIDER
from utils.logger import get_logger

log = get_logger("query_engine")


class QueryEngine:
    """
    Single entry point for all RAG queries.

    Steps:
      1. Embed the user's query
      2. Retrieve top-K relevant chunks from ChromaDB
      3. De-duplicate chunks by bid_no
      4. Pass chunks + question to LLM (or format directly)
      5. Return structured result dict
    """

    def __init__(self, top_k: int = RAG_TOP_K):
        self.top_k = top_k
        log.info(
            f"QueryEngine ready | "
            f"top_k={top_k} | "
            f"llm={RAG_LLM_PROVIDER or 'retrieval-only'}"
        )

    # -------------------------------------------------------
    # MAIN QUERY METHOD
    # -------------------------------------------------------
    def ask(
        self,
        question: str,
        filters: dict | None = None,
        top_k: int | None = None,
    ) -> dict:
        """
        Ask a natural-language question about GeM bids.

        Args:
            question : natural language query
            filters  : optional ChromaDB metadata filters
                       e.g. {"product_type": "Service"}
                            {"bid_type": "Global Tender"}
            top_k    : override default top_k for this query

        Returns dict:
            {
              question    : str,
              answer      : str,
              sources     : list[dict],   # unique bids cited
              chunk_count : int,
            }
        """
        k = top_k or self.top_k
        log.info(f"Query: '{question}' | filters={filters} | k={k}")

        # 1. Retrieve
        chunks = search(question, top_k=k, filters=filters)
        log.info(f"Retrieved {len(chunks)} chunks")

        if not chunks:
            return {
                "question":    question,
                "answer":      "No relevant bids found for your query.",
                "sources":     [],
                "chunk_count": 0,
            }

        # 2. Generate answer
        answer = call_llm(question, chunks)

        # 3. De-duplicate sources (one entry per unique bid)
        seen_bids = set()
        sources   = []
        for c in chunks:
            bid_no = c.get("bid_no", "")
            if bid_no not in seen_bids:
                seen_bids.add(bid_no)
                sources.append({
                    "bid_no":          bid_no,
                    "bid_type":        c.get("bid_type", ""),
                    "product_type":    c.get("product_type", ""),
                    "department":      c.get("department", ""),
                    "end_date":        c.get("end_date", ""),
                    "estimated_value": c.get("estimated_value", ""),
                    "document_url":    c.get("document_url", ""),
                    "relevance_score": c.get("score", 0),
                })

        return {
            "question":    question,
            "answer":      answer,
            "sources":     sources,
            "chunk_count": len(chunks),
        }

    # -------------------------------------------------------
    # CONVENIENCE: SEARCH ONLY (no LLM)
    # -------------------------------------------------------
    def search_only(
        self,
        query: str,
        filters: dict | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        """Returns raw retrieval results without LLM answer."""
        return search(query, top_k=top_k or self.top_k, filters=filters)

    # -------------------------------------------------------
    # STATS
    # -------------------------------------------------------
    def stats(self) -> dict:
        return vs_stats()


# =========================================================
# INTERACTIVE CLI  (run: python -m rag.query_engine)
# =========================================================
if __name__ == "__main__":
    import json
    engine = QueryEngine()

    print("\n" + "=" * 60)
    print("  GeM Bid RAG Search — Interactive Mode")
    print("  Type your question. 'quit' to exit.")
    print("  Prefix with 'f:' to add a filter.")
    print("  Example: f:product_type=Service laptop bids")
    print("=" * 60 + "\n")

    while True:
        try:
            raw = input("Question > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not raw or raw.lower() in ("quit", "exit", "q"):
            break

        # parse optional inline filter  f:key=value
        filters = None
        question = raw
        if raw.startswith("f:"):
            parts = raw.split(" ", 1)
            if len(parts) == 2:
                kv      = parts[0][2:].split("=", 1)
                question = parts[1]
                if len(kv) == 2:
                    filters = {kv[0]: kv[1]}

        result = engine.ask(question, filters=filters)

        print("\n" + "-" * 60)
        print("ANSWER:\n")
        print(result["answer"])
        print("\nSOURCES:")
        for s in result["sources"]:
            print(
                f"  • {s['bid_no']} | "
                f"{s['department'][:40]} | "
                f"Score: {s['relevance_score']:.2%}"
            )
        print("-" * 60 + "\n")
