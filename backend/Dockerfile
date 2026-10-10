FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies (needed for psycopg2, tiktoken, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt requirements-production-constraints.txt ./
ARG PIP_DEFAULT_TIMEOUT=120
ENV PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1
RUN pip install --no-cache-dir -r requirements.txt -c requirements-production-constraints.txt && pip check

# Verified tokenizer data is fetched during the build. Retrieval's strict
# whole-passage budget reads this cache offline; requests never download assets.
ENV TIKTOKEN_CACHE_DIR=/app/.tokenizer-cache
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

# The same optional image can serve the API or dedicated chat workers.
ARG INSTALL_CHAT_EXECUTION=false
COPY requirements-chat-execution.txt ./
RUN case "$INSTALL_CHAT_EXECUTION" in \
      true) pip install --no-cache-dir -r requirements-chat-execution.txt && pip check ;; \
      false) : ;; \
      *) echo "INSTALL_CHAT_EXECUTION must be true or false" >&2; exit 1 ;; \
    esac

# Playwright browser binaries are NOT installed here. The active production
# crawler is Firecrawl (services/firecrawl_service.py, an external HTTP API).
# Playwright/crawl4ai (services/crawl4ai_service.py) remain in the repository
# for legacy tests only and are not imported by document_processing_service.py.
# Installing "playwright install --with-deps chromium" here only bloated the
# production image/build time. If Crawl4AI is ever reactivated in production,
# restore this step.

# Copy backend codebase
COPY . .

RUN python -c "from services.structural_chunking import count_tokens; assert count_tokens('deployment readiness') > 0"
RUN python -c "from pathlib import Path; assert all(Path(p).is_file() for p in ('services/combined_rag/LICENSE-APACHE-2.0', 'services/combined_rag/vendor/LANGCHAIN_LICENSE', 'services/combined_rag/PROVENANCE.md'))"
RUN python -c "from pathlib import Path; assert all(Path(p).is_file() for p in ('third_party/ragflow/LICENSE', 'third_party/ragflow/NOTICE', 'third_party/ragflow/HKUDS_GRAPH_LICENSE', 'third_party/ragflow/MICROSOFT_GRAPHRAG_LICENSE', 'third_party/ragflow_port_manifest.json'))"

# Expose port
EXPOSE 8000

# Start command
CMD ["python", "scripts/start_api.py"]
