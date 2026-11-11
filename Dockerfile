# syntax=docker/dockerfile:1
# Touchline Takes: one image for the website, the scheduler, or both.
#   docker build -t touchline-takes .
# Behind a registry mirror: --build-arg BASE_IMAGE=mirror.gcr.io/library/python:3.13-slim
ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TOUCHLINE_ENV=production \
    KERAS_BACKEND=jax \
    KERAS_HOME=/data/keras \
    DATABASE_PATH=/data/touchline_takes.db \
    CHECKPOINT_PATH=/data/checkpoints.db \
    CHROMA_DIR=/data/chroma \
    MODEL_PATH=/data/models/match_predictor.joblib \
    PHOTO_MODEL_DIR=/data/models/photo_tagger \
    RESULTS_DIR=/data/results \
    PORT=8000 \
    WEB_CONCURRENCY=2 \
    SCHEDULE_MINUTES=30

WORKDIR /app
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data

COPY requirements.txt .
# Optional build secret "ca": an extra CA bundle for builds behind a TLS-inspecting proxy.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install -r requirements.txt

COPY touchline_takes ./touchline_takes
COPY scripts ./scripts
COPY data ./data
COPY docker/entrypoint.sh /usr/local/bin/touchline-entrypoint
RUN chmod 0755 /usr/local/bin/touchline-entrypoint && python -m compileall -q touchline_takes

USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

ENTRYPOINT ["touchline-entrypoint"]
CMD ["all"]
