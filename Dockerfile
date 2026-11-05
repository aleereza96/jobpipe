FROM node:22-bookworm-slim
ARG CODEX_VERSION=latest
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONUTF8=1 PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 JOBPIPE_DATA_DIR=/data \
    CODEX_HOME=/home/node/.codex PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv ca-certificates git tini tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && npm install --global "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt 'anthropic>=0.40,<1' \
    && mkdir -p /data /home/node/.codex \
    && printf 'cli_auth_credentials_store = "file"\n' > /home/node/.codex/config.toml \
    && chown -R node:node /data /home/node/.codex
COPY --chown=node:node server.py jobpipe.py sources.py ai_provider.py gmail_alerts.py cv_pdf.py cv_source.py cv_review.py search_rank.py dedup.py ./
COPY --chown=node:node web/ ./web/
COPY --chown=node:node defaults/ ./defaults/
USER node
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3)" || exit 1
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8787"]
