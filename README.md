# netcalc-api

A small, stateless subnet / CIDR calculator API — and a **secure software supply chain**
built around it.

The app is deliberately trivial. It is a *vehicle*: a clean, well-tested target that makes
the real subject matter legible. The interesting work is in **how it is built, scanned,
signed, and proven** — the container, the pipeline, and the reasoning recorded in
[15 ADRs](docs/adr/).

The guarantee the pipeline exists to make:

> **The image published to GHCR is bit-for-bit the image that passed every gate — and you
> can prove it cryptographically, without trusting me.**

---

## Contents

- [What this demonstrates](#what-this-demonstrates)
- [Verify the published image yourself](#verify-the-published-image-yourself)
- [The container](#the-container)
- [The pipeline](#the-pipeline)
- [Dependencies: hash-pinned locks](#dependencies-hash-pinned-locks)
- [One rule, three layers](#one-rule-three-layers)
- [The app](#the-app)
- [Local development](#local-development)
- [Decisions (ADRs)](#decisions-adrs)
- [Runbook](#runbook)
- [Traps hit along the way](#traps-hit-along-the-way)
- [What I'd change for production](#what-id-change-for-production)

---

## What this demonstrates

| Practice | Where | ADR |
|---|---|---|
| Distroless runtime — no shell, no package manager, non-root | `Dockerfile` | [0003](docs/adr/0003-container-base-image-strategy.md), [0004](docs/adr/0004-dependency-transfer-strategy.md) |
| Base images pinned by **digest**, auto-refreshed | `Dockerfile`, `dependabot.yml` | [0005](docs/adr/0005-base-image-pinning-strategy.md) |
| Base image's **own provenance verified before building on it** | `ci.yml` → `build` | [0011](docs/adr/0011-base-image-provenance-verification.md) |
| Dependencies **hash-pinned**, installed with `--require-hashes` | `requirements*.txt` | [0012](docs/adr/0012-hash-pinned-python-dependencies.md) |
| Every GitHub Action pinned to a **commit SHA** | `ci.yml` | [0013](docs/adr/0013-sha-pin-github-actions.md) |
| Two scanners, **one policy**: block on fixable, surface everything | `ci.yml` → `build` | [0006](docs/adr/0006-vulnerability-scanning-policy.md), [0014](docs/adr/0014-scanner-policy-parity.md) |
| CycloneDX **SBOM**, attested to the image | `ci.yml` → `release` | [0007](docs/adr/0007-sbom-format-and-generation.md) |
| **Keyless signing** — Sigstore + GitHub OIDC, no long-lived keys | `ci.yml` → `release` | [0008](docs/adr/0008-keyless-image-signing.md) |
| **SLSA provenance** + enforced verification gate | `ci.yml` → `release` | [0009](docs/adr/0009-slsa-provenance-and-verification-gate.md) |
| **Build once** — the signed image *is* the tested image | `ci.yml` | [0015](docs/adr/0015-build-once-gate-before-publish.md) |

---

## Verify the published image yourself

This is the point of the project, so it comes first. None of it requires trusting this
repository: the signature is checked against Sigstore's public transparency log and
GitHub's OIDC identity.

```bash
IMAGE=ghcr.io/gastoniy/netcalc-api
DIGEST=$(docker buildx imagetools inspect $IMAGE:latest --format '{{.Manifest.Digest}}')

IDENTITY="https://github.com/gastoniy/netcalc-api/.github/workflows/ci.yml@refs/heads/main"
ISSUER="https://token.actions.githubusercontent.com"

# 1. Was this image built by THIS workflow, in THIS repo, on main?
cosign verify \
  --certificate-identity="$IDENTITY" \
  --certificate-oidc-issuer="$ISSUER" \
  "$IMAGE@$DIGEST"

# 2. What is actually inside it? (signed CycloneDX SBOM)
cosign verify-attestation --type cyclonedx \
  --certificate-identity="$IDENTITY" \
  --certificate-oidc-issuer="$ISSUER" \
  "$IMAGE@$DIGEST" > /dev/null && echo "SBOM attestation OK"

# 3. How was it built? (SLSA provenance)
gh attestation verify oci://$IMAGE@$DIGEST --repo gastoniy/netcalc-api
```

There are **no long-lived signing keys** — not in the repo, not in GitHub Secrets, not on
my laptop. Signing uses a short-lived certificate bound to the workflow's OIDC identity
(ADR-0008). That certificate identity is the security boundary: a signature produced by
any *other* workflow, repo, or branch fails these checks.

> The image ships with three **known, unfixable** HIGH CVEs in the base image's CPython.
> That is deliberate, recorded, and visible in the Security tab rather than suppressed —
> see the [runbook](#a-cve-has-no-fix).

---

## The container

`Dockerfile` — two stages, both **digest-pinned** Chainguard images:

```dockerfile
FROM cgr.dev/chainguard/python:latest-dev@sha256:…   AS builder   # has pip
FROM cgr.dev/chainguard/python:latest@sha256:…       AS final     # distroless
```

**What the runtime image does not contain:** a shell, a package manager, pip, setuptools,
wheel, or a root user. The tools a compromised dependency would reach for simply are not
present.

Decisions worth calling out:

- **No pip in the final image (ADR-0004).** The builder makes a venv with `--without-pip`,
  installs with `--target`, and only the **`site-packages` directory** is copied forward.
  The obvious alternative — copying the whole venv — drags pip *and* a dangling interpreter
  symlink into the runtime.
- **`PYTHONPATH`, not `PATH`.** The base's entrypoint is the absolute `/usr/bin/python`, so
  `PATH` is never consulted. `PYTHONPATH` is what makes imports resolve. Get this wrong and
  the image builds perfectly and dies on start.
- **`--require-hashes` at install time.** A substituted or tampered wheel fails the *build*,
  not production (ADR-0012).
- **`python -m app` as the entrypoint**, not the `uvicorn` console script — there is no shell
  and nothing on `PATH` to invoke.
- **The Python minor version must match the base (3.14).** Building `pydantic-core` against a
  different minor produces an ABI mismatch that surfaces **at container start, not at build**.
- **OCI labels** carry source, revision and licence (ADR-0010). `APP_VERSION` is injected at
  build time and served at `/`, so a running container can always answer *"which build am I?"*

Two alternative bases are kept as documented comparisons rather than deleted —
`dockerfile.google` (Google distroless) and `dockerfile.debian-slim` (hardened slim).
ADR-0003 records why Chainguard won.

Check the hardening claims yourself:

```bash
docker run -d --name smoke -p 8000:8000 ghcr.io/gastoniy/netcalc-api:latest
docker inspect --format '{{.Config.User}}' ghcr.io/gastoniy/netcalc-api:latest  # 65532
docker exec smoke sh    # MUST FAIL — there is no shell. That is the point.
docker rm -f smoke
```

---

## The pipeline

`.github/workflows/ci.yml`. **The ordering is the design.**

```
lint ──► test ──► build ─────────────────────────────────► release  (main only)
ruff     pytest   ONE docker build, then EVERY gate:        sign (keyless)
                    1. verify base image provenance         attest SBOM
                    2. Trivy       ─┐                       SLSA provenance
                    3. SBOM (Syft)  │ all fail closed       verify signature    ─┐ fail
                    4. Grype       ─┤                       verify attestation  ─┘ closed
                    5. smoke test  ─┘
                  ─────────────────────────────────────
                  only now: push THAT image ──► digest ───► (job output)
```

**Three properties hold structurally, not by convention:**

**1. The signed image is the tested image.** There is exactly *one* `docker build`. `build`
scans and boots that local image, then `docker tag` + `docker push` ships **that exact image
ID** and emits its digest as a job output. `release` never builds — it signs the digest it is
handed and contains no reference to the Dockerfile (ADR-0015).

> This was a real defect, not a hypothetical. The pipeline used to build **twice** — once to
> test, once to push — and relied on a GitHub Actions cache hit to make the two "the same".
> A cache hit is a performance optimisation, not an integrity guarantee. On a cache miss it
> would have signed, SBOM-attested and SLSA-provenanced an artifact that had never been
> scanned or booted.

**2. A failing gate leaves the registry untouched.** Every gate runs *before* the only push,
so a red Trivy, Grype or smoke test means **nothing** reaches GHCR — no image, no `latest`
movement, nothing to clean up.

> Grype used to run *after* the push. A failing Grype therefore left a vulnerable, unsigned
> image in GHCR with `latest` already pointing at it, while the pipeline went red: fail-closed
> in the pipeline, fail-**open** in the registry. A gate downstream of publication is not a
> gate.

**3. A pull request cannot publish.** The push steps are `main`-only, and no other push exists
in the workflow.

Supporting details:

- **The base image's provenance is verified before we build on it** — `cosign verify` against
  Chainguard's OIDC identity, reading the digest straight out of the Dockerfile so the two
  cannot drift (ADR-0011). Trusting a base image because its *name* looks right is the
  supply-chain equivalent of not checking at all.
- **The smoke test is a real gate**, not a formality: it boots the container, asserts correct
  subnet maths over HTTP, asserts the running app reports the git SHA it was built from,
  asserts uid 65532, and asserts **no shell exists** in the image.
- **Privilege is split.** `build` can push but cannot sign (no `id-token`); `release` can sign
  but cannot build. Compromising either job alone does not yield *publish **and** bless
  arbitrary bytes*.
- **Scanner output reaches the Security tab** as SARIF, under separate `trivy` and `grype`
  categories.

---

## Dependencies: hash-pinned locks

`requirements*.txt` is the **single source of truth** (ADR-0012). There is no Pipfile — it was
deleted, because a second dependency manifest that nothing reads is a lie waiting to be
believed.

```
requirements.in     ← humans edit this (direct deps, == pinned)
      │  pip-compile --generate-hashes
      ▼
requirements.txt    ← generated: full transitive graph, every package sha256-pinned
```

```bash
pip install pip-tools
pip-compile --strip-extras --generate-hashes --output-file=requirements.txt requirements.in
pip-compile --strip-extras --generate-hashes --output-file=requirements-dev.txt requirements-dev.in
```

Because the locks carry hashes, pip runs in hash-checking mode for **everything** (one hash
anywhere ⇒ hashes required everywhere), so CI's dev install is hash-verified for free and the
Dockerfile installs with `--require-hashes`.

**Never hand-edit a `.txt`** — it is generated, and the next compile silently overwrites you.

---

## One rule, three layers

Most of what "supply-chain security" means here is one principle applied consistently:

> **Reference dependencies by content, never by name.**

| Layer | Named (mutable) ❌ | Content-addressed ✅ | ADR |
|---|---|---|---|
| Base images | `python:latest` | `@sha256:…` digest | [0005](docs/adr/0005-base-image-pinning-strategy.md) |
| Python wheels | `fastapi` | `==0.139.0` + `--hash=sha256:…` | [0012](docs/adr/0012-hash-pinned-python-dependencies.md) |
| GitHub Actions | `actions/checkout@v4` | `@9c091bb…` commit SHA | [0013](docs/adr/0013-sha-pin-github-actions.md) |

A tag is a *pointer*. Its owner — or whoever compromises them — can move it, and every build
that references it silently runs new code. This matters most for CI actions, which execute
with the workflow's `id-token: write` permission: an action running at that moment could sign
an arbitrary image with **this project's own identity**.

Pins nobody refreshes rot into a different security problem, so all three layers are watched by
Dependabot (`docker`, `pip`, `github-actions`) — turning silent drift into a reviewable PR.

---

## The app

Two layers, deliberately separated (ADR-0001, ADR-0002):

- **`app/calculator.py`** — pure, framework-free logic. Plain input → output functions,
  unit-testable with no HTTP client or fixtures.
- **`app/main.py`** — a thin FastAPI adapter: routing, error mapping, health, metrics.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Service name + running version (`APP_VERSION`) |
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe |
| GET | `/metrics` | Prometheus exposition |
| GET | `/api/v1/subnet` | Describe a network (`?cidr=`) |
| GET | `/api/v1/contains` | Is an IP in a network (`?cidr=&ip=`) |
| GET | `/api/v1/split` | Split into subnets (`?cidr=&new_prefix=`) |

Interactive docs at `/docs`.

Two invariants the tests exist to defend:

- **Host addresses are never enumerated.** Counts and first/last usable hosts are computed
  arithmetically, so an IPv6 `/64` (2⁶⁴ addresses) answers instantly instead of OOM-ing the
  container. `test_ipv6_64_does_not_enumerate` is the regression guard.
- **Pathological splits are refused, not attempted** (`MAX_SUBNETS = 1024`).

Liveness and readiness are kept separate even though they look identical for a stateless
service — readiness is where a real dependency check belongs later.

Prometheus metrics are labelled by **route template, never raw path** — labelling by URL would
make every query string a new time series and blow up cardinality.

---

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt

python -m app                     # serves on :8000 (override with PORT)
curl "localhost:8000/api/v1/subnet?cidr=192.168.1.0/24"

python -m pytest                  # 32 tests: pure unit + API integration
ruff check .                      # style + flake8-bandit security lint
```

> `python -m pytest`, **not** bare `pytest` — the `-m` form puts the repo root on `sys.path`
> so `import app` resolves.

Build and exercise the container exactly as CI does:

```bash
docker build -t netcalc-api:ci --build-arg APP_VERSION=$(git rev-parse --short HEAD) .
docker run -d --name smoke -p 8000:8000 netcalc-api:ci
curl -sf localhost:8000/healthz && curl -sf localhost:8000/readyz
docker exec smoke sh              # MUST FAIL
docker rm -f smoke
```

---

## Decisions (ADRs)

Every significant decision is recorded in [`docs/adr/`](docs/adr/) with its context, the
alternatives rejected, and the **consequences accepted**. A reversed decision gets a *new* ADR
superseding the old one — the history is never rewritten.

| # | Decision |
|---|---|
| [0001](docs/adr/0001-vehicle-application-choice.md) | A purpose-built subnet calculator as the pipeline's vehicle app |
| [0002](docs/adr/0002-two-tier-test-architecture.md) | Two-tier tests: pure logic vs. API integration |
| [0003](docs/adr/0003-container-base-image-strategy.md) | Chainguard distroless as the primary base |
| [0004](docs/adr/0004-dependency-transfer-strategy.md) | Transfer `site-packages`, not a portable venv |
| [0005](docs/adr/0005-base-image-pinning-strategy.md) | Digest-pin base images, with automated refresh |
| [0006](docs/adr/0006-vulnerability-scanning-policy.md) | Trivy as a fail-closed gate, not a passive report |
| [0007](docs/adr/0007-sbom-format-and-generation.md) | CycloneDX SBOMs via Syft |
| [0008](docs/adr/0008-keyless-image-signing.md) | Keyless signing via Cosign + GitHub OIDC |
| [0009](docs/adr/0009-slsa-provenance-and-verification-gate.md) | SLSA provenance + an enforced verification gate |
| [0010](docs/adr/0010-oci-image-metadata-labels.md) | Standard OCI image labels |
| [0011](docs/adr/0011-base-image-provenance-verification.md) | Verify the base image's provenance before building |
| [0012](docs/adr/0012-hash-pinned-python-dependencies.md) | Hash-pinned deps as the single source of truth |
| [0013](docs/adr/0013-sha-pin-github-actions.md) | SHA-pin GitHub Actions |
| [0014](docs/adr/0014-scanner-policy-parity.md) | One scan policy: block on fixable, surface everything |
| [0015](docs/adr/0015-build-once-gate-before-publish.md) | Build once; gate before publish; sign what was tested |

Hard-won operational findings live in [`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Runbook

### The build failed on a CVE

1. **Is it fixable?** That is the only question. The gates block on HIGH/CRITICAL **that have
   a fix available**. So if the build is red, a fix exists — apply it.
2. **Where is it?** The Security tab (categories `trivy` / `grype`) names the package.
   - *A Python dependency* → bump it in `requirements.in`, re-run `pip-compile`, commit the
     regenerated lock.
   - *An OS package in the base* → the base digest is stale. Merge Dependabot's bump, or
     re-resolve the digest by hand.
3. **Never suppress a fixable finding to get green.** That inverts the entire point.

### A CVE has no fix

The current state: the Chainguard base ships three unfixable HIGH CVEs in CPython. Blocking on
them would freeze the pipeline indefinitely with **no remediation path available** — which
teaches a team to start ignoring red builds, the exact failure mode ADR-0006 exists to prevent.

So the policy is **block on what can be fixed, surface everything else** (ADR-0014). A
non-blocking Grype pass reports the unfixable findings to the Security tab, so they are *on the
record*: accepted, visible, and self-clearing the moment upstream patches and Dependabot bumps
the digest.

### GHCR looks like a mess after a release

One release publishes **one image**, plus signing artifacts and two orphaned index manifests.
The signature, SBOM attestation and SLSA provenance are all **untagged referrers** — so a
blanket *"delete all untagged versions"* destroys precisely what the pipeline produces, and
`cosign verify` starts failing. Full inventory and how to classify any entry:
[`docs/troubleshooting.md`](docs/troubleshooting.md).

### A verification step hangs for 15 minutes

It is not hung. `cosign verify-attestation` prints the entire SBOM to stdout as one
multi-megabyte line and GitHub's log ingestion chokes on it; verification itself is offline and
takes seconds. The `> /dev/null` on that step is load-bearing.
[`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Traps hit along the way

Each of these cost real time, and each is now defended by a comment, a test, or an ADR:

- **A `pydantic-core` ABI mismatch fails at container *start*, not at build.** The venv's Python
  minor must match the base's (3.14).
- **`metadata-action`'s `labels:` silently clobbers the Dockerfile's `LABEL`s** (last-writer-wins
  on identical OCI keys). CI passes `tags:` only.
- **Chainguard's free tier publishes no version tags** — only `latest`/`latest-dev`. Digest
  pinning is not merely better practice here; it is the *only* way to pin (ADR-0005).
- **`cosign verify-attestation` "hanging"** turned out to be log throughput, not Sigstore. Debug
  logging made it *slower* — which is what proved it.
- **A gate that runs after the push fails open in the registry**, however red the pipeline goes.
- **`curl | sh` to install a scanner** — inside a pipeline whose whole thesis is "never execute
  unverified code" — was in the original design. It is now a SHA-pinned action.

---

## What I'd change for production

Being explicit about a demo's limits is more useful than pretending it has none:

- **`/readyz` returns a static `"ready"`.** Honest for a stateless service, but in production
  readiness must actually check whatever's absence should pull this instance out of the load
  balancer.
- **Constrain the runtime**: read-only root filesystem, dropped capabilities, enforced
  memory/CPU limits. The *image* is hardened; the runtime isn't yet.
- **Enforce verification at deploy time, not just build time.** A signature nobody checks before
  running the image is decoration. An admission controller (Kyverno / Sigstore policy-controller)
  or a `cosign verify` gate in the deploy job is where this actually pays off — and is exactly
  what the planned Terraform + Ansible deployment will consume.
- **Multi-arch builds** (`linux/arm64`); currently amd64 only.
- **Branch protection with required status checks.** Fail-closed CI is advisory until merges are
  genuinely blocked on it.
- **A rollback story.** Every build is addressable by immutable digest and `sha-<commit>` tag, so
  rollback is *possible* — it is not yet *automated*.
- **Attest the test results**, not just the SBOM. "These tests passed against this digest" is a
  stronger claim than "an SBOM exists".

---

*Image: [`ghcr.io/gastoniy/netcalc-api`](https://github.com/gastoniy/netcalc-api/pkgs/container/netcalc-api)*
