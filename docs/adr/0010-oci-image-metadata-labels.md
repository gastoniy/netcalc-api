# ADR-0010: Adopt Standard OCI Image Labels

**Status:** Accepted
**Date:** 2026-07-12

## Context

An unlabeled image sitting in a registry is anonymous — nothing answers "which
commit produced this," "what does this do," or "where's the source" without
cross-referencing external build logs. `org.opencontainers.image.*` is the
standardized annotation namespace that registries, scanners, and SBOM tooling
already know to read, as opposed to inventing ad hoc label keys no external
tool would recognize.

## Decision

Add `LABEL` instructions using the standard OCI keys: `title`, `description`,
`revision` (set to the `APP_VERSION` build arg, i.e. the git SHA, injected via
`--build-arg APP_VERSION=$(git rev-parse --short HEAD)`), `source` (repo URL),
and `licenses`.

## Consequences

- `docker inspect` on a running container answers "which commit is this"
  directly, without needing to cross-reference CI logs or trust a
  potentially-moved tag.
- These labels live in the same image config that the Cosign signature and
  SLSA provenance attestation reference — provenance *proves* the build-commit
  claim cryptographically; the label makes the same fact readable by a plain
  `docker inspect` with no verification tooling required. They serve different
  consumers, not duplicate purposes.
- Requires `ARG APP_VERSION` to be declared before the `LABEL` instruction in
  the same build stage for interpolation to resolve.

## Alternatives Considered

- No labels — rejected: leaves the image undocumented at the artifact level,
  inconsistent with the rest of this project's provenance work.
- Custom, non-OCI label keys — rejected: not recognized by external tooling.
