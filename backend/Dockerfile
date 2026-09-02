FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (needed for psycopg2, tiktoken, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browser binaries are NOT installed here. The active production
# crawler is Firecrawl (services/firecrawl_service.py, an external HTTP API).
# Playwright/crawl4ai (services/crawl4ai_service.py) remain in the repository
# for legacy tests only and are not imported by document_processing_service.py.
# Installing "playwright install --with-deps chromium" here only bloated the
# production image/build time. If Crawl4AI is ever reactivated in production,
# restore this step.

# Copy backend codebase
COPY . .

# Expose port
EXPOSE 8000

# Start command
CMD ["python", "scripts/start_api.py"]
