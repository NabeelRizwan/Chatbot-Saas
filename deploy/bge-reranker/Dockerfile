# Build context: deploy/bge-reranker.
# Explicit CPU deployment; this is separate from the existing embedding TEI.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
    TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
WORKDIR /app
COPY service/requirements.txt service/requirements.txt
RUN pip install torch==2.10.0+cpu --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r service/requirements.txt && pip check
COPY service/ /app/service/
RUN python -m service.prefetch && useradd --uid 10001 --create-home ranker
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 BGE_MODEL_DIR=/model \
    BGE_DEVICE=cpu BGE_THREADS=2 PORT=8080
USER ranker
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health',timeout=4)"
CMD ["python", "-m", "service.server"]
