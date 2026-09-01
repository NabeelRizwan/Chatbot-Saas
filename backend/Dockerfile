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

# Install Playwright and chromium binaries for URL crawling
RUN playwright install --with-deps chromium

# Copy backend codebase
COPY . .

# Expose port
EXPOSE 8000

# Start command
CMD ["python", "scripts/start_api.py"]
