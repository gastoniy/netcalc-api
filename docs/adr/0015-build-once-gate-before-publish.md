# ADR-0015: Build Once — Gate Before Publish, Sign the Artifact That Was Tested

**Status:** Accepted
**Date:** 2026-07-14

**Makes good on:** ADR-0006 / ADR-0014 (scan gates), ADR-0008 (signing), ADR-0009 (SLSA
provenance) — whose claims this change makes *true* rather than merely plausible.

**Partially supersedes ADR-0007.** That ADR chose CycloneDX, and chose to generate the SBOM
**"from the final pushed image"** — deliberately, so the SBOM would describe the artifact
that actually shipped rather than a build-time approximation. The *format* decision stands
unchanged. The *source* decision is reversed here: the SBOM is now generated from the local
**tested** image, before the push.

This is not a retreat from ADR-0007's reasoning — it is that reasoning taken further. ADR-0007
wanted the SBOM to describe the real shipped artifact, and scanning the pushed image was the
only way to guarantee that *while two separate builds existed*. Once the pushed image **is**
the tested image (below), the local image and the registry image are the same bytes, so both
sources are equivalent — and generating it locally is strictly better, because it lets the
Grype gate run **before** anything is published. ADR-0007's goal survives; its mechanism is no
longer the way to reach it.

## Context

Every integrity claim this pipeline makes — the cosign signature, the SBOM attestation, the
SLSA provenance — is an assertion about **the bytes in one specific image**. Two structural
defects meant those assertions were being made about bytes that had never passed the gates.

### 1. The signed image was not the tested image

`build` built the image with `load: true`, verified the base image's provenance, ran Trivy
as a fail-closed gate, smoke-tested the running container — and then threw the image away.
`release` then ran a *second, independent* `docker/build-push-action` on a different runner
and pushed **that**, then signed and attested it. The step was even named "Build & push
(cache-identical to the tested image)".

The two were only "the same image" because both passed `cache-from: type=gha`. **A cache hit
is a performance optimisation, not an integrity guarantee.** The GHA cache evicts (10 GB
limit), and cache scope differs between a PR run and the post-merge run on `main`. On a
miss, `release` genuinely rebuilt — and that never-scanned, never-smoke-tested artifact was
what got pushed, signed, SBOM-attested and given provenance.

This is precisely the artifact-substitution the pipeline exists to prevent, reachable by
accident rather than by an adversary. Hash-pinning the dependency locks (ADR-0012) narrowed
the blast radius — a rebuild now installs identical wheels — but did not close it. The
guarantee remained "we believe it's the same" rather than "it is the same by construction".

### 2. One gate ran *after* publication

Trivy and the smoke test gated before the push. **Grype did not** — it ran in `release`,
against an SBOM of the *already-pushed* image. So a failing Grype gate produced this state:

- the image is in GHCR, with `latest` and `sha-<40>` already pointing at it;
- it is unsigned, unattested, and has no provenance;
- the pipeline is red.

A gate that fails closed in the pipeline while failing **open in the registry** is not a
gate. Anyone pulling `latest` gets the vulnerable image, and nothing marks it as unblessed.
This directly contradicted ADR-0006 ("a fail-closed gate, not a passive report").

## Decision

**Build once. Run every gate against that one artifact. Publish only if all gates pass.
Sign exactly what was published.**

- `build` performs the **only** `docker build` in the pipeline, into the local daemon.
- **All** gates run against that local image, in order: base-image provenance → Trivy →
  SBOM → **Grype** → smoke test.
- Only after every gate passes does `build` log in and `docker tag` + `docker push` **that
  exact local image** — no rebuild — and export the resulting digest as a job output.
- `release` is reduced to **notarisation**: it neither builds nor scans. It takes the digest
  from `needs.build.outputs.digest`, downloads the SBOM artifact that Grype gated on, and
  signs / attests / provenances / verifies that digest. It contains no reference to the
  Dockerfile, and must never contain one again.
- A guard fails the job loudly if the digest hand-off is empty: signing an empty reference
  would be worse than not signing.

The GHA build cache remains, but is now **purely a speed optimisation**. Nothing about
correctness depends on a cache hit any more. That is the point.

## Consequences

- **Identity is structural, not probabilistic.** The bytes that were scanned, gated and
  booted are the bytes that were pushed — same runner, same daemon, same image ID. There is
  no second build that could diverge.
- **The registry is now the clean side of the gate.** A failing Trivy, Grype, or smoke test
  leaves GHCR completely untouched: no image, no tag movement, nothing to clean up. "Fail
  closed" now means what it says.
- **A PR structurally cannot publish.** The push steps are `main`-only; there is no other
  push in the workflow.
- **The attested SBOM is the SBOM that was gated.** It is generated from the local tested
  image and handed to `release` as an artifact, rather than re-derived from a registry
  re-pull. What we sign is what we scanned.
- **Accepted cost: `build` now holds `packages: write`.** The job that runs third-party
  scanners and boots the container also carries registry-write credentials. This is a
  deliberate trade of strict least-privilege for artifact integrity, and it is the main
  thing given up here. It is bounded: `build` does *not* hold `id-token: write`, so it
  cannot sign — only `release` can, and `release` builds nothing. Compromising either job
  alone does not yield "publish *and* bless arbitrary bytes".
- **New failure mode:** the digest now comes from parsing `docker push` output rather than
  `build-push-action`'s `outputs.digest`. The `Require a digest from build` guard in
  `release` is the safety net for that; do not remove it.
- The pipeline is also *faster* — it no longer builds the image twice.

## Alternatives Considered

- **Keep two builds, trust the cache** (the status quo) — rejected. This is the defect.
  "Probably the same bytes" is not a foundation for a signature.
- **Push by digest before the gates, tag only after they pass** — rejected: unscanned bytes
  reach the registry. They would be untagged and hard to discover, but they would be pullable
  by digest, and "the gate runs after publication" is exactly the property being eliminated.
- **Ship the image between jobs as an OCI tarball artifact** — this preserves strict
  least-privilege (`build` stays read-only; only `release` gets `packages: write`) and was
  genuinely tempting. Rejected on cost/benefit: an ~80MB artifact round-trip on every run,
  an extra tool (skopeo/crane) to push an OCI layout while preserving the manifest bytes,
  and a subtle digest-preservation footgun — all to buy a privilege boundary, not integrity.
  Worth revisiting if `build` ever grows steps that run genuinely untrusted code.
- **Merge `build` and `release` into a single job** — simplest of all, but then one job holds
  build, scan, push *and* signing identity simultaneously. Splitting notarisation out keeps
  the signing OIDC identity in a job that cannot build.
