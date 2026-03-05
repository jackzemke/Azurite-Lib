# ---- Build stage: compile llama-cpp-python with CUDA ----
FROM nvidia/cuda:12.1.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3.10-venv python3-pip \
    build-essential cmake ninja-build git \
    unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

WORKDIR /build

# Create libcuda stub for build-time linking.
# The real libcuda.so.1 is provided by the NVIDIA driver at runtime,
# but the linker needs it at compile time. The devel image only ships
# an unversioned stub, so we create the .so.1 symlink the linker expects.
RUN ln -s /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/cuda/lib64/stubs/libcuda.so.1
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64/stubs:${LD_LIBRARY_PATH}

# Use a venv so every pip install shares one site-packages.
# This prevents the third install from re-downloading torch (CPU)
# or re-building llama-cpp-python, since pip can see they're already
# installed and satisfy the version constraints.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

# Each pip install is a separate layer for better Docker caching.
# If requirements.txt changes, torch and llama-cpp-python layers are
# still cached (~25 min saved on rebuild).

# 1. PyTorch with CUDA from official index
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cu121

# 2. llama-cpp-python compiled against CUDA
RUN CMAKE_ARGS="-DGGML_CUDA=on" \
    pip install --no-cache-dir llama-cpp-python

# 3. Everything else (torch and llama-cpp-python already satisfied, skipped)
RUN pip install --no-cache-dir -r requirements.txt


# ---- Runtime stage ----
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3-pip \
    tesseract-ocr tesseract-ocr-eng \
    curl \
    unixodbc \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

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
