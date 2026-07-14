# ADR-0008: Keyless Image Signing via Cosign + GitHub OIDC (Sigstore)

**Status:** Accepted
**Date:** 2026-07-12

## Context

A scanned, clean image provides no cryptographic guarantee that the artifact
sitting in the registry is actually the one the pipeline produced — a
compromised registry or an actor with push access could substitute a
different image at the same tag undetected. Traditional signing requires
generating, storing, and rotating a long-lived private key, which becomes an
operational burden and an attack target in itself.

## Decision

Sign the pushed image with Cosign using GitHub Actions' built-in OIDC
identity ("keyless" signing) rather than a managed long-lived key pair. Always
sign by content digest (`@sha256:...`), never by tag — Cosign's own tooling
resists signing a mutable tag reference for this reason.

## Consequences

- No long-lived private key exists anywhere in this pipeline to leak, rotate,
  or protect — the ephemeral keypair Cosign generates per-signing exists only
  in memory for the duration of the operation.
- The signing identity is cryptographically tied to the specific GitHub
  workflow/repo/ref that produced it (embedded in the Fulcio-issued
  certificate), not to a shared secret anyone with repo access could extract.
- Every signature is recorded in Rekor, a public append-only transparency log,
  enabling later audit of when and by which identity an artifact was signed.
- Requires `id-token: write` permission on the signing job — a deliberate,
  auditable permission grant, not an implicit one.
- Signing alone is not sufficient without a corresponding verification step
  that fails closed — see ADR-0009.

## Alternatives Considered

- Long-lived key pair stored as a CI secret — rejected: key-management burden
  and a single point of compromise this project's threat model doesn't need.
