# netcalc-api

A small, stateless subnet / CIDR calculator API. It exists as a clean,
well-tested target for a secure CI/CD supply-chain pipeline and a
Terraform + Ansible deployment — the app is deliberately simple so the
interesting work lives in *how it is built, shipped, and run*.

## Why this app

- **Minimal runtime deps** — core logic uses Python's stdlib `ipaddress`,
  so the only runtime requirements are FastAPI + uvicorn. A distroless
  image stays tiny and there's almost no attack surface for scanners.
- **Real logic worth testing** — CIDR maths gives the test stage genuine
  substance (edge cases: `/31`, `/32`, IPv6 `/64`, oversized splits).
- **Stateless** — no database, so the focus stays on the DevOps layer.
- **Ops-ready** — exposes liveness, readiness, and Prometheus metrics.

## Endpoints

| Method | Path                  | Purpose                                  |
|--------|-----------------------|------------------------------------------|
| GET    | `/`                   | Service name + running version           |
| GET    | `/healthz`            | Liveness probe                           |
| GET    | `/readyz`             | Readiness probe                          |
| GET    | `/metrics`            | Prometheus exposition                    |
| GET    | `/api/v1/subnet`      | Describe a network (`?cidr=`)            |
| GET    | `/api/v1/contains`    | Is an IP in a network (`?cidr=&ip=`)     |
| GET    | `/api/v1/split`       | Split into subnets (`?cidr=&new_prefix=`)|

Interactive docs at `/docs` once running.

## Run locally

```bash
pip install -r requirements.txt
python -m app                       # serves on :8000 (override with PORT)
curl "localhost:8000/api/v1/subnet?cidr=192.168.1.0/24"
```

`APP_VERSION` is read from the environment and surfaced at `/` and in the
OpenAPI schema — inject the git SHA at build time to answer "which build
is live?".

## Test & lint

```bash
pip install -r requirements-dev.txt
pytest          # 32 tests: pure unit + API integration
ruff check .    # style + security (flake8-bandit) lint
```

## Project layout

```
app/
  calculator.py   # pure, framework-free logic (directly unit-testable)
  models.py       # pydantic response models
  main.py         # thin FastAPI adapter: routes, health, metrics
  __main__.py     # `python -m app` entrypoint (distroless-friendly)
tests/
  test_calculator.py   # unit tests on the logic
  test_api.py          # integration tests via TestClient
```
