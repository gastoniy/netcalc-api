# ADR-0005: Digest-Pin Base Images, With Automated Refresh

**Status:** Accepted
**Date:** 2026-07-12

## Context

Floating tags (`latest`, `latest-dev`, `python:3.12-slim`) are mutable — the
content behind a tag can change between builds without any change to the
Dockerfile. This directly undermines the project's supply-chain integrity goal:
signing and generating SLSA provenance for an image built from an
unpinned, silently-changeable base is a weaker claim than it appears to be.
This is sharpened further by Chainguard's free tier, which restricts
version-specific tags (`:3.14`, `:3.14-dev`) to paid subscribers — only
`:latest`/`:latest-dev` are available without a subscription, and those are
rebuilt daily.

## Decision

Pin both `FROM` lines to a specific image **digest** (`@sha256:...`), not a
tag. Digest pulls remain available on Chainguard's free tier without
authentication, even though named version tags do not. Pair this with an
automated dependency-update tool (Renovate or Dependabot, both of which
natively understand Docker digest references) to open a reviewable PR whenever
the digest behind the tracked tag moves, rather than either freezing forever
or drifting silently.

## Consequences

- Guarantees the exact same base image bytes across every build until a
  digest-update PR is deliberately reviewed and merged — a floating tag cannot
  do this.
- Directly protects against the hardcoded Python-version-in-path fragility
  from ADR-0004: an unpinned `latest` bump changing the Python minor version
  would silently break the `site-packages` copy path; digest pinning makes
  that change an explicit, reviewed diff instead of a runtime surprise.
- Requires an ongoing process (the bot + review cadence) rather than a
  one-time setup — an unmaintained pinned digest eventually falls behind on
  security patches, which is the opposite of Chainguard's core value
  proposition.
- SLSA provenance and Cosign signatures generated against a pinned digest are
  a stronger, more meaningful claim than the same tooling run against a
  moving tag.

## Alternatives Considered

- Floating `latest`/`latest-dev` (no pinning) — rejected: no reproducibility
  guarantee, and undermines the provenance/attestation work done elsewhere in
  this pipeline.
- Chainguard's paid version-pinned tags — not adopted; free-tier digest pinning
  achieves equivalent reproducibility without a subscription.
