# ADR-0013: SHA-Pin GitHub Actions

**Status:** Accepted
**Date:** 2026-07-13

## Context

Every step in this pipeline was invoked by a mutable reference:
`actions/checkout@v4`, `aquasecurity/trivy-action@0.28.0`,
`sigstore/cosign-installer@v3`, and so on. A git tag is a pointer, not a
fingerprint — the owner of an action (or anyone who compromises their account)
can move `v4` to point at new code, and every workflow in the world that
references `@v4` executes it on the next run.

This matters more here than in an ordinary repo, because of *what these actions
are trusted with*. The release job hands them `id-token: write`, `packages: write`,
and `attestations: write`. An action that runs at that moment can sign an arbitrary
image with the project's own OIDC identity. A pipeline whose entire thesis is
"don't trust artifacts you haven't verified" was fetching its own build steps by
mutable tag — and, in one case, installing Grype by piping an unpinned remote
script from `raw.githubusercontent.com` straight into `sh`.

The tags were also badly stale (`attest-build-provenance@v1` against a current v4;
`checkout@v4` running on a Node 20 runtime that reached EOL in April 2026), which
is the predictable result of having no bot watching them.

## Decision

Pin **every** `uses:` to a full 40-character commit SHA, with the human-readable
version in a trailing comment:

```yaml
- uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
```

A commit SHA is content-addressed: it cannot be repointed. This is the same
mechanism as ADR-0005 (digest-pin base images) and ADR-0012 (hash-pin Python
wheels) — three layers of the build, one rule: *reference dependencies by
content, never by name*.

Replace the `curl | sh` Grype install with the SHA-pinned `anchore/scan-action`,
which is the same mechanism applied to the last remaining unpinned executable.

Add the **`github-actions` Dependabot ecosystem**. This is not optional: SHA pins
are only safe when something refreshes them. Dependabot understands SHA-pinned
actions, bumps the SHA, and updates the version comment alongside it — turning a
silent supply-chain risk into a reviewable PR.

## Consequences

- The set of code that runs with the project's signing identity is now fixed and
  auditable. `git log` on the workflow shows every change to it.
- The version comment is documentation, not a pin — it can lie if hand-edited.
  Trust the SHA; let Dependabot maintain the pair.
- Reviewing a Dependabot action bump now means reviewing an opaque SHA change. The
  version comment and the release notes are what make that diff legible; without the
  comment convention this would be materially worse than tag-pinning.
- Actions cannot be upgraded by "just moving to the new tag" — every bump is an
  explicit commit, which is the intent.

## Alternatives Considered

- **Tag-pinning to a full version (`@v7.0.0` rather than `@v7`)** — better than a
  floating major, but still mutable: a version tag can be force-pushed. It narrows
  the window without closing it.
- **Vendoring the actions into the repo** — maximal control, but a large maintenance
  burden and it forfeits Dependabot's security advisories. Disproportionate for this
  project.
- **Trusting only first-party `actions/*` and `docker/*`** — rejected as security
  theatre: the actions with the most dangerous permissions here (cosign-installer,
  attest-build-provenance, the scanners) are exactly the ones that most need pinning.
