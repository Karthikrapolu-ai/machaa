FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin machaa

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && mkdir -p /data/browser-profile /data/artifacts /data/home \
    && chown -R machaa:machaa /data /ms-playwright /app

COPY machaa ./machaa

USER machaa

ENV HOME=/data/home \
    XDG_CONFIG_HOME=/data/home/.config \
    XDG_CACHE_HOME=/data/home/.cache \
    MACHAA_DATA_DIR=/data \
    MACHAA_BROWSER_PROFILE=/data/browser-profile \
    MACHAA_HOST=0.0.0.0 \
    MACHAA_PORT=8787 \
    MACHAA_HEADLESS=true \
    MACHAA_CHROMIUM_NO_SANDBOX=true

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health')"

CMD ["python", "-m", "machaa"]
