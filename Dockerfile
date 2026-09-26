# GSR Support Agent -- core API (text chat only)
# Voice (Whisper + pyttsx3) is intentionally excluded here -- see
# requirements-core.txt and README's Deployment section for why.

FROM python:3.12-slim

WORKDIR /app

# System deps: only what duckdb/chromadb genuinely need to build/run --
# kept minimal since this image is meant to fit a free-tier host.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

COPY agent/ agent/
COPY api/ api/
COPY mcp_server/ mcp_server/
COPY rag/ rag/
COPY knowledge_base/ knowledge_base/
COPY data/load_data.py data/generate_synthetic_data.py data/

# data/raw (source CSVs), data/*.duckdb (the built warehouse), and
# rag/chroma_db (the built vector index) are NOT copied in -- they're
# either generated at container startup (see entrypoint.sh) or mounted
# as a volume in docker-compose.yml, so the same image works whether
# you're building fresh or attaching to already-built data.
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
