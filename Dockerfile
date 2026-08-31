FROM cgr.dev/chainguard/python:latest-dev@sha256:f0f3f01288b7ae009d90828d2dbd2f3c949aa3b6e820081cb278880d758ffb44 AS builder

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

FROM cgr.dev/chainguard/python:latest@sha256:f487e51ca6ee4b20e07e1b4c9c44d3108ab305d2318b0f233f5b72529f52a6aa AS final

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