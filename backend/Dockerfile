# Backend container for the Signals (AI Stock Screener + Paper Trading) app.
# Used by the Render blueprint (render.yaml) and any other Docker-based host
# (Fly.io, Railway, Hetzner). The persistent state (SQLite + CSV cache) is
# expected to be mounted at /data and pointed to via DB_URL / STOCK_DATA_DIR
# / INDEX_DATA_DIR / INDEX_INTRADAY_DATA_DIR env vars.
FROM python:3.12-slim

# curl_cffi (yfinance) needs libcurl + ssl runtime libs. Keeping the layer
# slim by purging apt lists after install.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      libssl3 \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud platforms inject $PORT (Render, Fly, Railway). Default to 8000 so
# `docker run -p 8000:8000` works locally without extra env wiring.
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Single-instance only: APScheduler runs in-process. Do not auto-scale this
# service horizontally without first migrating jobs to an external scheduler.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
