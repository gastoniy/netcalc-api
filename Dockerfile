FROM cgr.dev/chainguard/python:latest-dev@sha256:0416c4863f2d0fb0e2e58d125e03b73cf4876cb02efc7927fd4a248a04f78c24 AS builder

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

FROM cgr.dev/chainguard/python:latest@sha256:ce9aaca1f826f7f963cd031e98f8c19f993b1843096d395ea919b646e72cb8de AS final

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