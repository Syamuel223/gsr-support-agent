"""
Embeds and indexes the GSR knowledge base (policy + FAQ markdown docs) into
a Chroma vector store, for retrieval by the RAG-based specialist agents.

Chunking strategy: split each doc on its "## " section headers, keeping
each header together with its own content. This matches how the docs were
actually written (one policy sub-topic per section) and produces clean,
self-contained chunks -- verified against the real docs in
knowledge_base/ (7-8 chunks per doc, each a coherent sub-topic) rather than
using a generic fixed-size text splitter that would cut mid-sentence.

Run:
    python rag/embed_and_index.py
"""

import argparse
import re
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

KB_DIR = Path(__file__).parent.parent / "knowledge_base"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "gsr_knowledge_base"


def chunk_markdown(text: str) -> list[str]:
    """Split a markdown doc into chunks on '## ' section boundaries."""
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    return [s.strip() for s in sections if s.strip() and len(s.strip()) > 20]


def load_documents() -> list[dict]:
    """
    Walk knowledge_base/, chunk every .md file, and return a flat list of
    {id, text, metadata} records ready to embed.
    """
    docs = []
    for path in sorted(KB_DIR.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        # doc-level title = first line (the '# ' H1)
        first_line = text.strip().split("\n")[0].lstrip("# ").strip()
        category = path.parent.name  # "policies" or "faqs"
        chunks = chunk_markdown(text)
        for i, chunk in enumerate(chunks):
            section_title = chunk.split("\n")[0].lstrip("# ").strip()
            docs.append({
                "id": f"{path.stem}_{i}",
                "text": chunk,
                "metadata": {
                    "source_file": path.name,
                    "doc_title": first_line,
                    "section_title": section_title,
                    "category": category,
                },
            })
    return docs


def build_index(reset: bool = True):
    docs = load_documents()
    if not docs:
        print(f"No markdown files found under {KB_DIR}/ -- nothing to index.")
        return

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    embed_fn = embedding_functions.DefaultEmbeddingFunction()

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass  # collection didn't exist yet

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME, embedding_function=embed_fn
    )

    collection.add(
        ids=[d["id"] for d in docs],
        documents=[d["text"] for d in docs],
        metadatas=[d["metadata"] for d in docs],
    )

    print(f"Indexed {len(docs)} chunks from {len(set(d['metadata']['source_file'] for d in docs))} documents")
    by_file = {}
    for d in docs:
        by_file.setdefault(d["metadata"]["source_file"], 0)
        by_file[d["metadata"]["source_file"]] += 1
    for f, count in sorted(by_file.items()):
        print(f"  {f}: {count} chunks")
    print(f"\nChroma index stored at: {CHROMA_DIR}")


def query(question: str, n_results: int = 3):
    """Quick manual test: retrieve the top-n chunks for a question."""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    embed_fn = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_collection(COLLECTION_NAME, embedding_function=embed_fn)
    results = collection.query(query_texts=[question], n_results=n_results)
    for i, (doc, meta, dist) in enumerate(zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    )):
        print(f"\n--- result {i+1} (distance={dist:.3f}, source={meta['source_file']}) ---")
        print(doc[:300])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, default=None,
                         help="Skip indexing and just test a retrieval query")
    args = parser.parse_args()

    if args.query:
        query(args.query)
    else:
        build_index()
