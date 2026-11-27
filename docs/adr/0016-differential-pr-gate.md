# ADR-0016: Differential PR gate, absolute release gate, auto-merged base-image bumps

- **Status:** Accepted
- **Date:** 2026-11-25
- **Refines:** [ADR-0006](0006-vulnerability-scanning-policy.md), [ADR-0014](0014-scanner-policy-parity.md)
- **Relies on:** [ADR-0005](0005-base-image-pinning-strategy.md), [ADR-0011](0011-base-image-provenance-verification.md), [ADR-0015](0015-build-once-gate-before-publish.md)

## Context

Trivy and Grype scan the full image on every pull request and fail on any fixable HIGH/CRITICAL finding (ADR-0006, ADR-0014). The image includes the digest-pinned Chainguard base (ADR-0005).

When upstream publishes a fix for a CVE in the base, the vulnerability database changes, not the repository. From that moment every open PR turns red: pip bumps, Actions bumps and application changes alike. None of them caused the finding and none of them can fix it. The only remediation is the Dependabot base-digest PR, and until someone merges it, all other work is blocked.

This conflates two different questions in one gate:

1. **Did this change make the image worse?** This is a property of the diff, and the right thing to block a PR on.
2. **Is the image vulnerable against today's vulnerability database?** This is a property of the outside world. It changes without any commit, so the same commit can pass on Monday and fail on Tuesday.

Blaming a PR for (2) makes CI non-deterministic and trains the maintainer to ignore or re-run red builds. That is the exact failure mode ADR-0006 exists to prevent.

## Decision

### 1. Pull-request gates are differential

On `pull_request`, the `build` job first scans the last published image, `ghcr.io/gastoniy/netcalc-api:latest`, with the same Trivy and Grype policy. The vulnerability IDs it reports are written to ignore lists (`.trivyignore.baseline`, `.grype.yaml`), which the blocking scans of the PR image then use.

A PR therefore fails only on fixable HIGH/CRITICAL findings **not already present in `:latest`**: the ones it introduced.

`:latest` is the right baseline because it only moves after every gate has passed (ADR-0015). It is the last known good image, not merely the last built one.

### 2. Release gates stay absolute

On `push` to `main`, both ignore lists are written **empty**, so the original policy applies unchanged. If a fixable finding exists, `build` fails before the only push, and nothing reaches GHCR (ADR-0015). Differential gating never relaxes what gets published.

### 3. Base-image digest bumps are auto-merged

`dependabot-automerge.yml` enables GitHub auto-merge on Dependabot PRs from the `docker` ecosystem only. This is acceptable without human review because the trust decision is already enforced cryptographically: `build` runs `cosign verify` against Chainguard's release identity before building on the new digest (ADR-0011). A digest that fails verification fails `build`, and auto-merge never fires.

`pip` and `github-actions` updates have no equivalent provenance gate and remain on manual review.

The merge is enabled with a dedicated GitHub App token, not `GITHUB_TOKEN`. Merges performed with `GITHUB_TOKEN` do not trigger workflow runs, so the release would silently never happen.

### 4. Drift is detected by a schedule, not by PRs

`vuln-drift.yml` scans `:latest` daily with the absolute policy. It opens or updates a `vuln-drift` issue while fixable findings exist and closes it when `:latest` is clean. It is not a required check: it reports, it never blocks.

### 5. Prerequisite: branch protection

Auto-merge is only safe when merges are genuinely blocked on CI. The `protect-main` ruleset requires `Detect image-relevant changes`, `Lint Codebase`, `Run Tests` and `Build, Scan, Smoke & Push`, all sourced from GitHub Actions, with an empty bypass list.

`Detect image-relevant changes` is required explicitly: if it fails, `build` is skipped, and a skipped job counts as passing.

## Consequences

**Accepted:**

- **`main` can be red while the base is vulnerable.** An unrelated PR merged before the base bump lands produces a failed `main` run and no release. This is the honest state: nothing vulnerable is published. Daily Dependabot runs with `cooldown: 0` plus auto-merge keep the window under about a day.
- **"Require branches to be up to date" is off.** Strict mode would stall every auto-merged PR as soon as `main` moves, and a merge queue is not available for user-owned repositories. Two PRs that are each green alone could combine into a failure. The absolute gate on `main` catches this before publication.
- **`:latest` is trusted as the baseline source.** Whoever can move that tag controls what the PR gate ignores. The impact is bounded because the release gate does not use the baseline. A stricter variant would resolve `:latest` to a digest and `cosign verify` it against this repository's identity before scanning it.
- **Ignore lists match by vulnerability ID, not by package.** A PR that introduces a *new* package affected by a CVE ID already present in the baseline would pass the PR gate. The release gate still catches it.
- **Baseline failure is fail-safe.** If a baseline scan cannot run (first release, registry outage), its ignore list is empty and the PR falls back to the absolute policy: stricter, never looser.

**Gained:**

- A PR's result depends on its diff, not on the date it was run.
- The remediation path for upstream base fixes is automatic and still provenance-verified.
- Pre-existing findings stay visible: in the PR log ("Pre-existing findings inherited from :latest"), in the Security tab, and as a tracked issue.

## Alternatives considered

- **Keep absolute gates everywhere and rebase PRs after merging the bump manually.** Rejected: it leaves the maintainer as a required manual step in an automated supply chain, and every new upstream fix blocks all work again.
- **Pin the Trivy/Grype vulnerability database.** Rejected: it makes builds deterministic by hiding new vulnerabilities, which defeats the scan.
- **Skip image scanning on PRs that do not touch the `Dockerfile`.** Rejected: dependency PRs change the image without touching the `Dockerfile`, and would go unscanned.
- **Suppress the specific base CVEs in a committed `.trivyignore`.** Rejected: suppressing a *fixable* finding to get green violates the runbook rule "never suppress a fixable finding".