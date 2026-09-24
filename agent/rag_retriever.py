"""
Thin wrapper around the Chroma index built by rag/embed_and_index.py.
Specialist nodes call retrieve() to ground policy answers in the actual
knowledge base instead of the LLM's own (possibly wrong/outdated) beliefs
about GSR's policies.
"""

from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

CHROMA_DIR = Path(__file__).parent.parent / "rag" / "chroma_db"
COLLECTION_NAME = "gsr_knowledge_base"

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        embed_fn = embedding_functions.DefaultEmbeddingFunction()
        _collection = _client.get_collection(COLLECTION_NAME, embedding_function=embed_fn)
    return _collection


def retrieve(query: str, n_results: int = 3, category: str = None) -> list[dict]:
    """
    Retrieve the top-n most relevant knowledge base chunks for a query.
    Optionally filter by category ("policies" or "faqs").
    """
    collection = _get_collection()
    where = {"category": category} if category else None
    results = collection.query(query_texts=[query], n_results=n_results, where=where)

    chunks = []
    if not results["documents"] or not results["documents"][0]:
        return chunks
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        chunks.append({
            "text": doc,
            "source_file": meta["source_file"],
            "section_title": meta["section_title"],
            "distance": dist,
        })
    return chunks


def format_chunks_for_prompt(chunks: list[dict]) -> str:
    """Format retrieved chunks into a block suitable for injecting into an LLM prompt."""
    if not chunks:
        return "(no relevant policy information found)"
    parts = []
    for c in chunks:
        parts.append(f"[Source: {c['source_file']} - {c['section_title']}]\n{c['text']}")
    return "\n\n---\n\n".join(parts)
