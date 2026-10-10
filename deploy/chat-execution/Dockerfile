ARG BACKEND_IMAGE
FROM ${BACKEND_IMAGE}
COPY backend/requirements-chat-execution.txt /tmp/chat-requirements.txt
RUN pip install --no-cache-dir -r /tmp/chat-requirements.txt && pip check
CMD ["python", "-m", "workers.chat_worker"]
