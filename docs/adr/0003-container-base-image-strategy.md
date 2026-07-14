# ADR-0003: Container Base Image Strategy — Chainguard Distroless as Primary

**Status:** Accepted
**Date:** 2026-07-12

## Context

Three multi-stage build strategies were built and evaluated:

1. **Hardened Debian slim** — `python:3.12-slim` final stage, non-root user
   created manually via `useradd`. Retains a shell and package manager.
2. **Google distroless** — `python:3.12-slim` builder + `gcr.io/distroless/`
   `python3-debian12:nonroot final`. True distroless (no shell), but the base
   ships Python 3.11, not 3.12 — a builder/final version mismatch that breaks
   compiled-wheel imports (e.g. `pydantic-core`) silently at container start,
   not at build time.
3. **Chainguard distroless** — `cgr.dev/chainguard/python:latest-dev` builder +
   `:latest` final. True distroless, non-root by default (no special tag
   suffix needed), and the dev/non-dev image pair is guaranteed
   version-matched by Chainguard, avoiding the version-mismatch trap in (2).
   Chainguard images additionally ship their own SBOM and Sigstore-signed
   provenance from Chainguard's own build pipeline.

## Decision

Adopt the Chainguard-based Dockerfile as the primary, shipped image. Retain the
hardened-slim and Google-distroless Dockerfiles in the repository as documented
alternatives, each with a short rationale, rather than deleting the exploration.

## Consequences

- Avoids the Python-minor-version mismatch that silently breaks compiled
  wheels — the single most dangerous failure mode found across the three
  variants, since it fails at runtime, not build time.
- True distroless (no shell) is verified operationally, not assumed: `docker`
  `exec -it <container> sh` must fail — this is the actual proof, not the
  Dockerfile's stated intent.
- Chainguard's own base-image signature and SBOM cover only their layers, not
  this project's application layer — this project's own SBOM/scan/sign/attest
  pipeline (ADR-0006 through ADR-0009) remains fully required regardless (see
  ADR-0011 for the one genuinely new step this unlocks).
- Chainguard's free tier restricts version-pinned tags to paid subscribers,
  which motivated the digest-pinning approach in ADR-0005.
- Maintaining three Dockerfiles has documentation cost — each must state which
  one is authoritative to avoid reading as indecision.

## Alternatives Considered

Hardened-slim and Google-distroless, detailed above — both retained as
documented alternatives, not deleted, since the comparison itself is a
legitimate part of this project's demonstrated depth.
