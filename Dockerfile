# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 HOME=/home/syllaro \
    HF_HOME=/cache/huggingface TORCH_HOME=/cache/torch
WORKDIR /app
RUN useradd --create-home --uid 1000 syllaro \
    && mkdir /data /cache && chown syllaro:syllaro /data /cache
USER syllaro
ENTRYPOINT ["syllaro", "--config", "/config/config.json"]
CMD ["status"]

FROM base AS core
USER root
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --no-compile --no-deps .
USER syllaro

FROM base AS pascal
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements/pascal-py313.hashes.txt /app/requirements.lock.txt
RUN pip install --no-cache-dir --no-compile --require-hashes -r /app/requirements.lock.txt && pip check
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --no-compile --no-deps .
USER syllaro
