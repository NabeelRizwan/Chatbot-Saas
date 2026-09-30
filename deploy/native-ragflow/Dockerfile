FROM infiniflow/ragflow@sha256:e6b3f1a185c0a70abb3a72e1092415df8c5c6a4fae0089545554f2936c4b27ab
COPY saas_native_app.py /ragflow/api/apps/saas_native_app.py
COPY saas_native_core.py /ragflow/saas_native_core.py
COPY source-manifest.json LICENSE /stock-native/
ENV PYTHONPATH=/ragflow
RUN /ragflow/.venv/bin/python -c "from saas_native_core import source_integrity; source_integrity()"
# Use the official image's database/object-storage/embedding configuration.
# The SaaS alone calls its existing Gemini provider; this image supplies knowledge.
