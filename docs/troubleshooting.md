# Troubleshooting

Pipeline failures that were hard to diagnose, written down so they only cost us once.
These are *findings*, not decisions — decisions live in `docs/adr/`.

---

## `Verify SBOM attestation` takes 5–15 minutes (and looks like a hang)

**Date:** 2026-07-14
**Affects:** `release` job, `Verify SBOM attestation (fail closed)` step

### Symptom

The step sits there producing no output for 5, 12, even 14 minutes. It is not obviously
failing — no error, no retry message, nothing. Eventually it goes green and the pipeline
completes successfully. The duration varies from run to run.

Because it stalls immediately after `cosign sign` / `cosign attest` / SLSA provenance, it
looks exactly like a Sigstore or registry problem.

### It is NOT (all of these were investigated and ruled out)

- **Not a Rekor / transparency-log race.** This was the most attractive theory — that
  verification runs seconds after the attestation is written and has to wait for the log
  to integrate the entry. It is wrong. The debug log says plainly:

  ```
  - Existence of the claims in the transparency log was verified offline
  ```

  Verification is **offline**. It checks the claims against the bundle. It never calls
  Rekor, so there is nothing to wait for.

- **Not GHCR throttling / silent backoff.**
- **Not a cosign v3 regression** (we had just bumped `cosign-installer` v3 → v4).
- **Not a misconfiguration.** The certificate identity, the `--type cyclonedx` predicate,
  and the job permissions are all correct — which is why it *passes*, just slowly.

### Actual cause

**`cosign verify-attestation` prints the full attestation payload to stdout, and that
payload is the entire CycloneDX SBOM of the image** — every apk package and every Python
package, base64-encoded as a **single multi-megabyte line**.

The time is spent in GitHub's log ingestion, not in cosign. Verification itself takes
seconds.

### The evidence that settles it

Turning on **debug logging made the step slower, not faster** (12m00s → 14m24s). A network
wait, a Rekor delay, or a registry backoff would be completely indifferent to how verbose
the run is. More log volume producing more wall-clock time is a log-throughput bottleneck
and nothing else.

### Fix

Redirect **stdout** to `/dev/null`:

```yaml
- name: Verify SBOM attestation (fail closed)
  run: |
    timeout 300 cosign verify-attestation \
      --type cyclonedx \
      --certificate-identity="$IDENTITY" \
      --certificate-oidc-issuer="$ISSUER" \
      "$IMAGE" > /dev/null
```

This is safe, and it is **not** the same as throwing away the verification result:

- cosign writes the human-readable `Verification for … / The following checks were
  performed` block to **stderr**, so it is still in the log.
- The **exit code** is what gates the pipeline. It is unaffected.
- The payload is redundant anyway — the same SBOM is uploaded as a build artifact by the
  `Upload SBOM artifact` step.

**Do not "tidy up" this redirect.** It is load-bearing. Removing it reintroduces a
15-minute step.

### Why `cosign verify` (the signature step) does not need the same treatment

Both commands print their payload to stdout, but `cosign verify` emits the *simple signing*
payload — the image digest plus a couple of annotations, a few hundred bytes. Only the
attestation carries the whole SBOM. Same for the base-image provenance check in `build`.

### Why this mattered more than "a slow step"

The verify steps run **after** the image is pushed. The `release` job has
`timeout-minutes: 20`; the step was clearing it with only a few minutes to spare. Had it
tipped over, the job would have been killed *after* the image was already published and
signed to GHCR but *before* the verification gate ran — a gate that fails **open** while
appearing to fail closed. The slowness was a correctness risk, not just an annoyance.

### How to diagnose something like this next time

1. **Get the debug log before theorising.** Re-run the job with *Enable debug logging*
   ticked (Re-run jobs → tick the box), or set an `ACTIONS_STEP_DEBUG` = `true` repository
   *variable*. A single line in the log (`verified offline`) killed a theory that hours of
   reasoning had made sound convincing.
2. **Check whether debug mode changes the timing.** If a step gets *slower* when you log
   more, the log is the bottleneck. That one comparison is diagnostic on its own.
3. **Suspect output volume whenever a step "hangs" with no error and then succeeds.**
   Commands that dump SBOMs, attestations, manifests, or scan reports to stdout are the
   usual suspects.

---

## "GHCR is a mess" — what a release actually publishes

**Date:** 2026-07-14
**Affects:** `ghcr.io/gastoniy/netcalc-api` package versions view

### Symptom

One merge to `main` produces **7 package versions**, most of them opaque `sha256:…`
entries with no tags, and the count of untagged versions grows steadily (47 after a
handful of releases). It looks like the pipeline is pushing several images. It isn't.

### What is actually there

**One release pushes exactly one image.** Everything else is signing metadata, which
Sigstore stores *in the registry itself* — there is no separate signature store.

| Entry | What it is | Delete? |
|---|---|---|
| `38bc0313…` — tags `latest` + `sha-<git-commit>` | **The image.** The only real image. | NO |
| tag `sha256-38bc0313…` | **Referrers index** — lists the 3 attachments below | NO |
| `2bb643bb…` | **Signature** (`predicateType: sigstore.dev/cosign/sign/v1`) | NO |
| `9330de69…` | **SBOM attestation** (`predicateType: cyclonedx.org/bom`) | NO |
| `b7e280b2…` | **SLSA provenance** (`predicateType: slsa.dev/provenance/v1`) | NO |
| `f433012b…` | orphaned index — 1 entry | **yes** |
| `f9f3bea6…` | orphaned index — 2 entries | **yes** |

(Digests are from the 2026-07-14 release; the *shape* is what matters, not the values.)

### Why the two orphans exist

GHCR does not serve the OCI **referrers API**, so attachments fall back to a tag:
everything attached to an image is listed in an index stored under the tag
`sha256-<image-digest>` (note the **dash** — `sha256-38bc…` is a *tag*, not a digest).

That index is immutable content, so **each attachment rewrites it**: a new index manifest
is pushed and the tag is repointed. The previous index keeps existing, just untagged.

We attach three things in sequence, so three indexes are created:

1. `cosign sign` → index with **1** entry → orphaned
2. `cosign attest` → index with **2** entries → orphaned
3. `attest-build-provenance` → index with **3** entries → keeps the tag

So **every release leaves 2 orphaned index manifests** plus 5 legitimate entries. That is
the whole "mess". It is expected, and it is not a bug in the pipeline.

### Two traps

- **Do NOT "delete all untagged versions".** The signature, the SBOM attestation and the
  provenance are all *untagged* — they are referrers. A blanket untagged purge destroys
  exactly the artifacts the pipeline exists to produce, and `cosign verify` starts failing.
  Conversely, the one entry that *is* tagged `sha256-…` is **not an image**.
- **`.sig` / `.att` tags do not exist here.** That is the *old* cosign convention. Cosign
  v3 (pinned in CI) publishes the new Sigstore **bundle** format via referrers, with
  `artifactType: application/vnd.dev.sigstore.bundle.v0.3+json`. Don't go looking for
  `sha256-<digest>.sig`.

Safe to prune: orphaned indexes (the ones whose entry-count is *less* than the current
tagged index), and any `unknown/unknown` platform entries left over from the pre-ADR-0015
design, when `docker/build-push-action` attached its own buildx provenance. Plain
`docker push` (ADR-0015) no longer creates those.

After any pruning, re-run `cosign verify` and `cosign verify-attestation` to prove nothing
load-bearing was cut.

### How to inspect it (no `gh` CLI needed — the package is public)

```bash
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:gastoniy/netcalc-api:pull&service=ghcr.io" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

ACCEPT='application/vnd.oci.image.manifest.v1+json,application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.v2+json,application/vnd.docker.distribution.manifest.list.v2+json'

# classify any version: is it an image, an index, or an attachment?
curl -s -H "Authorization: Bearer $TOKEN" -H "Accept: $ACCEPT" \
  "https://ghcr.io/v2/gastoniy/netcalc-api/manifests/sha256:<digest>" | jq \
  '{mediaType, artifactType, subject: .subject.digest,
    layers: [.layers[].mediaType], predicate: .annotations."dev.sigstore.bundle.predicateType",
    index_entries: (.manifests | length?)}'
```

Read it as:

- `subject` present → an **attachment**; `subject.digest` says which image it belongs to.
  The `dev.sigstore.bundle.predicateType` annotation says *what kind*.
- `mediaType: …index…` with no `subject` → a **referrers index**. Compare its entry count
  with the currently-tagged one: fewer entries ⇒ superseded orphan.
- Real Docker/OCI manifest with rootfs layers → **the image**.

Or, from the image's side: `cosign tree ghcr.io/gastoniy/netcalc-api@sha256:<digest>`.

### Reducing the churn (not done, deliberately)

Setting `push-to-registry: false` on `actions/attest-build-provenance` would remove one
bundle and one index rewrite per run. Rejected: provenance would then live only in
GitHub's attestations API, so anyone pulling the image from GHCR without GitHub access
could not verify it — a real loss for a supply-chain project. The churn is the cheaper
cost.
