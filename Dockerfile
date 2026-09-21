# syntax=docker/dockerfile:1.7
FROM denoland/deno:bin-2.9.4 AS deno

FROM python:3.12-slim-bookworm AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY retrostream ./retrostream
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim-bookworm AS runtime
ARG RETROSTREAM_UID=10001
ARG RETROSTREAM_GID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RETROSTREAM_BIND=0.0.0.0 \
    RETROSTREAM_WEB_PORT=8780 \
    RETROSTREAM_STREAMING_PORT=8781 \
    RETROSTREAM_DATA_DIR=/data \
    RETROSTREAM_CACHE_DIR=/cache \
    RETROSTREAM_FFMPEG=/usr/bin/ffmpeg \
    RETROSTREAM_JS_RUNTIME=deno \
    DENO_DIR=/cache/deno

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates ffmpeg sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${RETROSTREAM_GID}" retrostream \
    && useradd --uid "${RETROSTREAM_UID}" --gid retrostream --home-dir /nonexistent \
       --no-create-home --shell /usr/sbin/nologin retrostream \
    && install -d -o retrostream -g retrostream -m 0750 /data /cache /cache/deno

COPY --from=deno /deno /usr/local/bin/deno
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels retrostream \
    && rm -rf /wheels
COPY --chmod=0555 docker/entrypoint.sh /usr/local/bin/retrostream-entrypoint

WORKDIR /app
USER retrostream:retrostream
EXPOSE 8780 8781
VOLUME ["/data", "/cache"]
ENTRYPOINT ["/usr/local/bin/retrostream-entrypoint"]
CMD ["retrostream"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import os,urllib.request; p=os.environ.get('RETROSTREAM_WEB_PORT','8780'); urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=3).read()"]
