FROM rust:slim AS monolith-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev perl && \
    rm -rf /var/lib/apt/lists/* && \
    OPENSSL_NO_VENDOR=1 cargo install monolith

FROM python:3.12-slim
WORKDIR /app
COPY --from=monolith-builder /usr/local/cargo/bin/monolith /usr/local/bin/monolith
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libssl3 git tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY frontend/ /frontend/
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /frontend
USER appuser
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
