# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Non-root runtime user.
RUN groupadd --system broker \
    && useradd --system --gid broker --home-dir /app --no-create-home --shell /usr/sbin/nologin broker

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code and example config (secrets are NOT baked in - injected at runtime).
COPY broker ./broker
COPY policy.yaml tasks.yaml ./

USER broker

EXPOSE 8787 8788

ENTRYPOINT ["python", "-m", "broker"]
