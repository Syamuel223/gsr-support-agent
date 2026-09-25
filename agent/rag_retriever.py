"""
Thin wrapper around the Chroma index built by rag/embed_and_index.py.
Specialist nodes call retrieve() to ground policy answers in the actual
knowledge base instead of the LLM's own (possibly wrong/outdated) beliefs
about GSR's policies.
"""

import os
import threading
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

CHROMA_DIR = Path(__file__).parent.parent / "rag" / "chroma_db"
COLLECTION_NAME = "gsr_knowledge_base"
RAG_CACHE_SIZE = int(os.environ.get("GSR_RAG_CACHE_SIZE", 256))

_client = None
_collection = None
_init_lock = threading.Lock()


def _get_collection():
    """
    Thread-safe lazy singleton. Phase 7 routes agent invocations through a
    real thread pool (asyncio.to_thread), so multiple requests can call
    this concurrently -- without the lock, two threads could both see
    _collection as None and race to initialize the Chroma client
    simultaneously, which is exactly what caused the
    "Could not connect to tenant default_tenant" errors under load
    testing. Double-checked locking: check without the lock first (cheap,
    the common case after warmup), only acquire the lock on the slow path.
    """
    global _client, _collection
    if _collection is not None:
        return _collection

    with _init_lock:
        if _collection is None:  # re-check: another thread may have won the race
            _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            embed_fn = embedding_functions.DefaultEmbeddingFunction()
            _collection = _client.get_collection(COLLECTION_NAME, embedding_function=embed_fn)
    return _collection


@lru_cache(maxsize=RAG_CACHE_SIZE)
def _retrieve_cached(query: str, n_results: int, category: str | None) -> tuple[tuple, ...]:
    """
    The actual Chroma query, cached. Policy/FAQ questions repeat a lot
    across different customers/sessions ("what's your return policy"),
    and the knowledge base only changes when someone re-runs
    embed_and_index.py -- so caching here is safe and meaningfully cuts
    embedding + vector-search latency under concurrent load, unlike
    caching a final chat response (which is customer-specific and would
    leak one customer's order data to another).

    Returns an immutable tuple-of-tuples rather than the list-of-dicts
    shape retrieve() exposes, so a caller mutating the result they got
    back can never corrupt what's cached for the next caller.
    """
    collection = _get_collection()
    where = {"category": category} if category else None
    results = collection.query(query_texts=[query], n_results=n_results, where=where)

    if not results["documents"] or not results["documents"][0]:
        return tuple()

    rows = []
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        rows.append((doc, meta["source_file"], meta["section_title"], dist))
    return tuple(rows)


def retrieve(query: str, n_results: int = 3, category: str = None) -> list[dict]:
    """
    Retrieve the top-n most relevant knowledge base chunks for a query.
    Optionally filter by category ("policies" or "faqs"). Cached (see
    _retrieve_cached) -- always returns a fresh list of fresh dicts so
    callers can freely mutate what they get back.
    """
    cached_rows = _retrieve_cached(query, n_results, category)
    return [
        {"text": text, "source_file": source_file, "section_title": section_title, "distance": distance}
        for text, source_file, section_title, distance in cached_rows
    ]


def format_chunks_for_prompt(chunks: list[dict]) -> str:
    """Format retrieved chunks into a block suitable for injecting into an LLM prompt."""
    if not chunks:
        return "(no relevant policy information found)"
    parts = []
    for c in chunks:
        parts.append(f"[Source: {c['source_file']} - {c['section_title']}]\n{c['text']}")
    return "\n\n---\n\n".join(parts)