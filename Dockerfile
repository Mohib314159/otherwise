FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
# rasterio wheels bundle GDAL; no system packages needed beyond certificates
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-app.txt ./
RUN pip install --no-cache-dir -r requirements-app.txt

COPY src ./src
COPY web ./web
COPY showcase ./showcase
COPY scripts ./scripts

ENV APP_RUNS_DIR=/data/runs \
    APP_CACHE_DIR=/data/cache \
    APP_FETCH_WORKERS=12 \
    PORT=7860
RUN mkdir -p /data/runs /data/cache

EXPOSE 7860
CMD ["sh", "-c", "uvicorn src.app.server:app --host 0.0.0.0 --port ${PORT}"]
