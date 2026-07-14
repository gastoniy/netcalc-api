# ADR-0001: Use a Purpose-Built Subnet Calculator as the Pipeline's Vehicle Application

**Status:** Accepted
**Date:** 2026-07-12

## Context

The secure CI/CD supply-chain pipeline needs a real application to build, scan,
sign, and deploy. Reusing an existing project was considered, but the pipeline
tooling (Trivy, Syft, Grype, Cosign) is the thing actually being demonstrated —
the application itself should not introduce noise: heavy dependencies inflate
scan surface irrelevantly, statefulness adds infrastructure the project doesn't
need, and thin logic gives the test suite nothing substantial to exercise.

## Decision

Build `netcalc-api`, a small stateless FastAPI service that performs CIDR/subnet
calculations using Python's standard-library `ipaddress` module. Business logic
(`app/calculator.py`) is kept fully decoupled from the web framework — pure
functions with no FastAPI imports.

## Consequences

- Minimal runtime dependencies (FastAPI, uvicorn, prometheus-client only) keeps
  the container's scan surface small and close to zero-CVE achievable.
- Real CIDR arithmetic (RFC 3021 point-to-point subnets, IPv6 `/64` scale,
  oversized-split rejection) gives the test suite genuine edge cases instead of
  trivial assertions.
- No database or external state means the Terraform/Ansible deployment stays
  focused on infrastructure concerns, not data persistence.
- Decoupling logic from the web layer enables a two-tier test architecture
  (see ADR-0002) without any HTTP mocking.

## Alternatives Considered

- Reusing an existing personal project (e.g. prior security tooling) — rejected
  because those projects carry dependencies and history unrelated to the
  supply-chain story this project is meant to tell.
