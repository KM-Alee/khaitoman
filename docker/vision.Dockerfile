# syntax=docker/dockerfile:1.7
# Delineate Anything field-boundary inference env (T1.2: kept separate from the science env).
# GDAL comes from Debian trixie; its Python bindings are built to match it exactly.
ARG PYTHON_IMAGE=python:3.11-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.14
FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gdal-bin libgdal-dev g++ git ca-certificates libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
ENV VIRTUAL_ENV=/opt/vision \
    PATH=/opt/vision/bin:$PATH \
    UV_HTTP_TIMEOUT=300 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1
RUN uv venv /opt/vision

# CPU torch by default (the host GPU driver is not working). Build with
# --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128 for CUDA.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install torch torchvision --index-url ${TORCH_INDEX}

# Upstream pinned to the commit checked on 2026-10-10 (T2.4).
ARG DELINEATE_REPO=https://github.com/Lavreniuk/Delineate-Anything.git
ARG DELINEATE_COMMIT=4cfab87ecccbe8d1bda4167676f623e3728570d9
RUN git clone ${DELINEATE_REPO} /opt/delineate \
 && git -C /opt/delineate checkout ${DELINEATE_COMMIT}
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -r /opt/delineate/requirements.txt \
 && uv pip install setuptools wheel numpy \
 && uv pip install --no-build-isolation "gdal[numpy]==$(gdal-config --version)"

RUN python -c "import torch, ultralytics; from osgeo import gdal, gdal_array; print('vision imports passed', torch.__version__, ultralytics.__version__, gdal.__version__)"

ENV HOME=/tmp HF_HOME=/app/data/models/hf YOLO_CONFIG_DIR=/tmp/ultralytics
WORKDIR /opt/delineate
CMD ["python", "delineate.py", "--help"]
