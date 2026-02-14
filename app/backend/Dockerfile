# ---- Build stage: compile llama-cpp-python with CUDA ----
FROM nvidia/cuda:12.1.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3.10-venv python3-pip \
    build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

WORKDIR /build

COPY requirements.txt .

# Install Python deps.
# 1. PyTorch with CUDA from official index
# 2. llama-cpp-python compiled with CUDA (needs nvcc from devel image)
# 3. Everything else from requirements.txt
RUN pip install --no-cache-dir --prefix=/install \
        torch --index-url https://download.pytorch.org/whl/cu121 && \
    CMAKE_ARGS="-DGGML_CUDA=on" \
    pip install --no-cache-dir --prefix=/install llama-cpp-python && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---- Runtime stage ----
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3-pip \
    tesseract-ocr tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Create data directories (overridden by volume mounts at runtime)
RUN mkdir -p /data/raw_docs /data/ocr /data/text /data/chunks \
    /data/embeddings /data/index/chroma /data/models /data/logs \
    && chown -R appuser:appuser /data

# Copy application code
COPY --chown=appuser:appuser . /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
