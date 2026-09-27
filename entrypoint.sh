#!/bin/sh
set -e

# On first run (or if the data volume is empty), generate the synthetic
# dataset and build the DuckDB warehouse + RAG index. On subsequent runs
# against a persisted volume, this is a no-op -- fast restarts, no
# redundant rebuilding.

if [ ! -f "data/gsr.duckdb" ]; then
    echo "No existing warehouse found -- generating synthetic data and loading it..."
    python data/generate_synthetic_data.py
    python data/load_data.py
fi

if [ ! -d "rag/chroma_db" ]; then
    echo "No existing RAG index found -- building it from knowledge_base/..."
    python rag/embed_and_index.py
fi

echo "Starting API..."
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
