FROM cgr.dev/chainguard/python:latest-dev@sha256:2857a8b6d2592dcf04ea0e082c637fb83e4b4d89949aa88b51b7c4f6e76d8bc8 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN python -m venv --without-pip /build/venv

ENV PATH="/build/venv/bin:$PATH"

COPY --chown=nonroot:nonroot requirements.txt .

# --require-hashes: every wheel must match a sha256 recorded in the lock, so a
RUN pip install --no-cache-dir --require-hashes \
    --target=/build/venv/lib/python3.14/site-packages \
    -r requirements.txt

FROM cgr.dev/chainguard/python:latest@sha256:69437de912cc3b5d36a2480b8fb0c3f658f151d8bc1978d19a6412be3a4983d5 AS final

# Overridable at build time (default is dev):
# --build-arg APP_VERSION=$(git rev-parse --short HEAD)
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.title="netcalc-api" \
      org.opencontainers.image.description="Subnet/CIDR calculator API" \
      org.opencontainers.image.revision="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/gastoniy/netcalc-api" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /application

COPY --from=builder --chown=nonroot:nonroot /build/venv /application/venv/
COPY --chown=nonroot:nonroot /app /application/app

ENV PATH="/application/venv/bin:$PATH"

ENV PYTHONPATH="/application/venv/lib/python3.14/site-packages:/application"

EXPOSE 8000

CMD ["-m", "app"]