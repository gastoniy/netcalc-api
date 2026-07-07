"""Integration tests hitting the API through the ASGI app (no network)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_reports_service_and_version():
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "netcalc-api"
    assert "version" in body


def test_liveness():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readiness():
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


def test_metrics_endpoint_returns_prometheus_format():
    # Make a request first so a counter exists to expose.
    client.get("/healthz")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_requests_total" in resp.text


def test_subnet_happy_path():
    resp = client.get("/api/v1/subnet", params={"cidr": "192.168.1.0/24"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["num_usable_hosts"] == 254
    assert body["broadcast_address"] == "192.168.1.255"


def test_subnet_bad_input_returns_400():
    resp = client.get("/api/v1/subnet", params={"cidr": "garbage"})
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_contains_true():
    resp = client.get(
        "/api/v1/contains", params={"cidr": "10.0.0.0/8", "ip": "10.1.2.3"}
    )
    assert resp.status_code == 200
    assert resp.json()["contained"] is True


def test_contains_version_mismatch_returns_400():
    resp = client.get(
        "/api/v1/contains", params={"cidr": "10.0.0.0/8", "ip": "2001:db8::1"}
    )
    assert resp.status_code == 400


def test_split_happy_path():
    resp = client.get(
        "/api/v1/split", params={"cidr": "192.168.0.0/24", "new_prefix": 26}
    )
    assert resp.status_code == 200
    assert resp.json()["subnet_count"] == 4


def test_split_oversized_returns_400():
    resp = client.get(
        "/api/v1/split", params={"cidr": "10.0.0.0/8", "new_prefix": 32}
    )
    assert resp.status_code == 400


def test_missing_required_param_returns_422():
    # FastAPI's own validation: missing query param is a 422.
    resp = client.get("/api/v1/subnet")
    assert resp.status_code == 422
