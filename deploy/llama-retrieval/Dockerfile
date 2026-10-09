FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
    NLTK_DATA=/app/models/nltk_data TIKTOKEN_CACHE_DIR=/app/models/tiktoken \
    LLAMA_MODEL_ROOT=/app LLAMA_DATA_DIR=/data/retrieval
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.10.0+cpu
RUN pip install --no-cache-dir -r requirements.txt && pip check
COPY model-artifacts.json download_models.py ./
RUN python download_models.py
COPY retrieval_engine ./retrieval_engine
COPY service.py start.py OPEN_SOURCE_NOTICES.txt FLASHtext-LICENSE.txt ./
COPY third_party ./third_party
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8000
CMD ["python", "start.py"]
