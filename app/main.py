"""netcalc-api: a small subnet-calculator service.

This is intentionally a thin HTTP adapter over app.calculator. The web
layer handles request parsing, error mapping, health, and metrics; all
the real logic lives in the (independently testable) calculator module.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException, Query, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

from app import calculator
from app.models import (
    ContainsResult,
    Health,
    NetworkInfo,
    ServiceInfo,
    SplitResult,
)

# Injected at build/deploy time (e.g. the git SHA or release tag). Surfacing
# the running version over HTTP and as a metric label is how you answer
# "which build is actually live right now?" without SSHing into a box.
APP_VERSION = os.getenv("APP_VERSION", "dev")

app = FastAPI(
    title="netcalc-api",
    version=APP_VERSION,
    summary="A small subnet / CIDR calculator API.",
)

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    """Record request count and latency for every request.

    Critical detail: we label by the *route template* (e.g. /api/v1/subnet),
    never the raw URL. Labelling by raw path would make every distinct query
    string a new time series and blow up Prometheus cardinality. Unmatched
    paths collapse into a single "unmatched" bucket for the same reason.
    """
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")

    REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
    REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
    return response


@app.get("/", response_model=ServiceInfo, tags=["meta"])
def root() -> ServiceInfo:
    return ServiceInfo(service="netcalc-api", version=APP_VERSION)


# --- Health -----------------------------------------------------------------
# Liveness vs readiness are deliberately separate. Liveness answers "is the
# process wedged and in need of a restart?"; readiness answers "should this
# instance receive traffic right now?". For a stateless service with no
# downstream deps they look similar, but keeping them distinct is the correct
# shape and lets readiness grow a real dependency check later.


@app.get("/healthz", response_model=Health, tags=["health"])
def liveness() -> Health:
    return Health(status="ok")


@app.get("/readyz", response_model=Health, tags=["health"])
def readiness() -> Health:
    return Health(status="ready")


@app.get("/metrics", tags=["health"])
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- API --------------------------------------------------------------------


@app.get("/api/v1/subnet", response_model=NetworkInfo, tags=["calc"])
def subnet(cidr: str = Query(examples=["192.168.1.0/24"])) -> NetworkInfo:
    try:
        return NetworkInfo(**calculator.describe_network(cidr))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/contains", response_model=ContainsResult, tags=["calc"])
def contains(
    cidr: str = Query(examples=["10.0.0.0/8"]),
    ip: str = Query(examples=["10.1.2.3"]),
) -> ContainsResult:
    try:
        return ContainsResult(**calculator.network_contains(cidr, ip))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/split", response_model=SplitResult, tags=["calc"])
def split(
    cidr: str = Query(examples=["192.168.0.0/24"]),
    new_prefix: int = Query(examples=[26]),
) -> SplitResult:
    try:
        return SplitResult(**calculator.split_network(cidr, new_prefix))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
