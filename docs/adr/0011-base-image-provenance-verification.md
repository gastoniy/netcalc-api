# ADR-0011: Verify the Base Image's Own Provenance Before Building

**Status:** Accepted
**Date:** 2026-07-12

## Context

This pipeline verifies its own output (ADR-0009), but that only answers "is
what I shipped legitimate" — it says nothing about whether the base image it
was built *from* was legitimate in the first place. Chainguard signs and
attests their own published images (verifiable via the same Cosign/Fulcio/
Rekor mechanism this project already uses for its own artifacts), which this
project was not otherwise making use of.

## Decision

Add an early CI step, before the `docker build`, that verifies the pinned
Chainguard base image digest's signature against Chainguard's known signing
identity:

```bash
cosign verify \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
  --certificate-identity=https://github.com/chainguard-images/images/.github/workflows/release.yaml@refs/heads/main \
  cgr.dev/chainguard/python@sha256:<pinned-digest>
```

## Consequences

- Closes a gap the rest of the pipeline doesn't otherwise cover: everything
  else verifies this project's own build output, but nothing previously
  checked that the starting point was itself genuine before building on top
  of it.
- Cheap to add (one Cosign call) given the tooling is already present in the
  pipeline for the project's own signing/verification steps.
- Distinct from, and does not replace, ADR-0008/0009's verification of this
  project's own shipped image — the two checks answer different questions
  ("is my base legitimate" vs. "is my output legitimate") and both are
  necessary for a complete chain of trust.

## Alternatives Considered

- Trusting the base image implicitly because it comes from a reputable
  vendor — rejected: this project's whole premise is verifying claims
  cryptographically rather than trusting reputation alone; skipping
  verification here would be inconsistent with that premise.
