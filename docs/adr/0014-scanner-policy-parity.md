# ADR-0014: One Scan Policy Across Both Scanners — Block on Fixable, Surface Everything

**Status:** Accepted
**Date:** 2026-07-14

**Extends:** ADR-0006 (Trivy as a fail-closed gate, not a passive report)

## Context

The pipeline runs two vulnerability scanners at two different points:

- **Trivy**, in `build`, against the locally-built image, *before* anything is pushed.
- **Grype**, in `release`, against the CycloneDX SBOM of the *pushed digest*.

Two scanners is deliberate — they use different vulnerability databases and different
matching logic, so each catches things the other misses, and the SBOM scan additionally
proves the SBOM we attest is itself scannable rather than a rubber stamp.

What was *not* deliberate was that the two enforced **different policies on the same
image**. Trivy ran with `ignore-unfixed: true`; Grype ran with a bare `--fail-on high`
and no equivalent filter. This was latent until the Chainguard base picked up three
unpatchable HIGH CVEs in CPython (CVE-2026-11940, CVE-2026-15308, CVE-2026-11972, all
in `python-3.14-3.14.6-r2`). Trivy passed the build. Grype then failed the release on
the very same image.

The failure was not a false positive, and it was not fixable:

- The pinned base digest was already the current `:latest`, and `3.14.6-r2` was the
  newest package Chainguard shipped. There was no digest to bump to.
- So the pipeline was red with **no available remediation path** — exactly the state
  ADR-0006 reasoned about when it chose `ignore-unfixed`, and exactly the state that
  teaches a team to start ignoring red builds.

ADR-0006 had in fact already decided this policy. It simply hadn't been applied to
the second scanner. The gap was a defect, not an open question.

There is, however, a real hazard in "just add `only-fixed`": Grype's output was
`table` — console text in a job log nobody reads after the run is green. Filtering
unfixable findings out of the *gate* would also have filtered them out of the only
place they were visible. "We don't block on it" would silently have become "we don't
know about it", which is the passive-report failure mode ADR-0006 was written to
reject, arriving through the back door.

## Decision

State the policy once, and enforce it identically in both scanners:

> **Block on what can be fixed. Surface everything else.**

Concretely:

- Both scanners gate on **HIGH/CRITICAL that have a fix available**: Trivy keeps
  `ignore-unfixed: true`; Grype gains `only-fixed: true`. A finding with a fix is a
  build-breaking defect, because there is something to *do* about it.
- Unfixable findings **never gate, and always report**. Grype runs a *second* time
  with `fail-build: false` and `output-format: sarif`, and that SARIF is uploaded to
  the GitHub Security tab. This step is `if: always()`, so the report survives a
  failing gate.
- The two SARIF uploads carry distinct `category:` values (`trivy`, `grype`) so code
  scanning keeps them as separate result sets instead of one overwriting the other.
- The `release` job gets `security-events: write`, without which the upload 403s.

## Consequences

- The two scanners can no longer disagree about whether the same image ships. A red
  build now means the same thing regardless of which tool raised it: *a fix exists and
  has not been applied.*
- Known-vulnerable-but-unpatchable content still ships. This is accepted, and it is the
  same trade ADR-0006 made — but it is now **on the record in the Security tab** rather
  than implicit in a scanner flag. Someone auditing the image can see the three CPython
  CVEs, see that they are unfixed, and see that we shipped anyway.
- Remediation becomes automatic rather than manual: when Chainguard publishes a patched
  CPython, the finding flips from unfixed to fixed, Dependabot opens the base-digest PR
  (ADR-0005), and the gate starts enforcing it. The policy converts "upstream has no fix"
  from a permanent build failure into a tracked, self-clearing item.
- Two Grype invocations cost an extra ~20s per release. Cheap relative to a gate the team
  learns to ignore.
- The pipeline now depends on GitHub code scanning as the visibility surface for accepted
  risk. If that upload silently breaks, the "surface everything" half of the policy is
  lost while the "block on fixable" half keeps working — a failure mode worth watching,
  since it is quiet by construction.

## Alternatives Considered

- **Leave Grype blocking on all HIGH, including unfixed** — rejected: the pipeline would
  have stayed red indefinitely with nothing to fix. The predictable outcome is that the
  gate gets bypassed or removed under delivery pressure, which is strictly worse than a
  gate calibrated to be actionable.
- **Add `only-fixed` and nothing else** — rejected. It unblocks CI with a one-line diff,
  but the three CVEs would then appear in no report at all. Cheap, and precisely the kind
  of invisible-risk shortcut this project exists to argue against.
- **Explicitly allowlist the three CVE IDs in a `.grype.yaml`** — genuinely attractive: it
  is the most auditable option, since a reviewer sees exactly which vulnerabilities were
  accepted and why. Rejected for now on maintenance grounds — every future unfixable base
  CVE would red the pipeline until a human triaged and appended it, and the base is
  rebuilt daily. Worth revisiting if the volume of accepted findings ever gets large
  enough that "unfixed" stops being a useful category on its own.
- **Drop one of the two scanners** — rejected: their disagreement here was a *policy* bug,
  not evidence that the second scanner is redundant. Two databases genuinely catch
  different things, and the SBOM scan is what keeps the attested SBOM honest.
