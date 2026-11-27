# netcalc-api

A small, stateless subnet / CIDR calculator API — and a **secure software supply chain**
built around it.

The app is deliberately trivial. It is a *vehicle*: a clean, well-tested target that makes
the real subject matter legible. The interesting work is in **how it is built, scanned,
signed, and proven** — the container, the pipeline, and the reasoning recorded in
[16 ADRs](docs/adr/).

The guarantee the pipeline exists to make:

> **The image published to GHCR is bit-for-bit the image that passed every gate — and you
> can prove it cryptographically, without trusting me.**

---

## Contents

- [What this demonstrates](#what-this-demonstrates)
- [Verify the published image yourself](#verify-the-published-image-yourself)
- [The container](#the-container)
- [The pipeline](#the-pipeline)
- [Keeping it current: Dependabot, auto-merge, drift](#keeping-it-current-dependabot-auto-merge-drift)
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
| Every GitHub Action pinned to a **commit SHA** | `.github/workflows/` | [0013](docs/adr/0013-sha-pin-github-actions.md) |
| Two scanners, **one policy**: block on fixable, surface everything | `ci.yml` → `build` | [0006](docs/adr/0006-vulnerability-scanning-policy.md), [0014](docs/adr/0014-scanner-policy-parity.md) |
| CycloneDX **SBOM**, attested to the image | `ci.yml` → `release` | [0007](docs/adr/0007-sbom-format-and-generation.md) |
| **Keyless signing** — Sigstore + GitHub OIDC, no long-lived keys | `ci.yml` → `release` | [0008](docs/adr/0008-keyless-image-signing.md) |
| **SLSA provenance** + enforced verification gate | `ci.yml` → `release` | [0009](docs/adr/0009-slsa-provenance-and-verification-gate.md) |
| **Build once** — the signed image *is* the tested image | `ci.yml` | [0015](docs/adr/0015-build-once-gate-before-publish.md) |
| **Differential PR gate, absolute release gate** — a PR is judged on its diff, `main` on everything | `ci.yml` → `build` | [0016](docs/adr/0016-differential-pr-gate.md) |
| Base-image bumps **auto-merged**, behind branch protection + provenance check | `dependabot-automerge.yml`, `rulesets/main.json` | [0016](docs/adr/0016-differential-pr-gate.md) |
| **Daily drift scan** of the published image | `vuln-drift.yml` | [0016](docs/adr/0016-differential-pr-gate.md) |
| CI tests on **the same Python the image ships**, enforced | `.python-version`, `ci.yml` → `build` | — |

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

> The image can ship with **known findings that have no fix yet**, typically in the base
> image's CPython or glibc. That is deliberate: they are visible in the Security tab rather
> than suppressed, and clear themselves when upstream patches — see the
> [runbook](#a-cve-has-no-fix).

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

- **No pip in the final image (ADR-0004).** The builder installs dependencies with
  `--target` into a plain `site-packages` directory, and **only that directory** is copied
  forward. The obvious alternative — copying a whole venv — drags pip *and* an interpreter
  symlink into the runtime.
- **`PYTHONPATH`, not `PATH`.** The base's entrypoint is the absolute `/usr/bin/python`, so
  `PATH` is never consulted. `PYTHONPATH` is what makes imports resolve. Get this wrong and
  the image builds perfectly and dies on start.
- **`--require-hashes` at install time.** A substituted or tampered wheel fails the *build*,
  not production (ADR-0012).
- **`python -m app` as the entrypoint**, not the `uvicorn` console script — there is no shell
  and nothing on `PATH` to invoke.
- **One Python version, declared once.** `.python-version` is the single source of truth:
  `setup-python` reads it for lint and tests, and `build` asserts that the image's own
  interpreter has the same minor. Chainguard's `latest` moves Python minors without notice;
  without this check, CI tested on 3.14 while 3.15 shipped, and nothing went red.
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
changes ─┐
lint ──► test ──► build ────────────────────────────────────────► release  (main only)
ruff     pytest   ONE docker build, then EVERY gate:               sign (keyless)
                    1. verify base image provenance                attest SBOM
                    2. assert image Python == .python-version      SLSA provenance
                    3. [PR only] baseline scan of :latest          verify signature    ─┐ fail
                    4. Trivy gate   ─┐                             verify attestation  ─┘ closed
                    5. SBOM (Syft)   │ all fail closed
                    6. Grype gate   ─┤   (+ non-blocking full
                    7. smoke test   ─┘    reports → Security tab)
                  ──────────────────────────────────────────
                  only now: push THAT image ──► digest ──────────► (job output)
```

`changes` decides whether the image is affected at all: a docs-only PR skips `build`
entirely, and a skipped required check counts as passing.

**Four properties hold structurally, not by convention:**

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

**4. A PR is judged on its diff; a release is judged on everything (ADR-0016).**

| Event | Scanner policy | What fails the build |
|---|---|---|
| `pull_request` | **Differential** | Fixable HIGH/CRITICAL findings **not already present** in the published `:latest` |
| `push` to `main` | **Absolute** | **Any** fixable HIGH/CRITICAL finding — and then nothing is published |

On a PR, `build` first scans `ghcr.io/gastoniy/netcalc-api:latest` and turns its findings
into ignore lists for the real scans. `:latest` is the right baseline because it only moves
after every gate has passed: it is *last known good*, not *last built*. If the baseline scan
cannot run, the lists stay empty and the PR falls back to the absolute policy — stricter,
never looser.

> Before this, every PR was scanned with the absolute policy. The day upstream published a
> fix for a CVE in the base image, **every open PR went red** — pip bumps, Actions bumps,
> application changes — none of which caused it or could fix it. The same commit could pass
> on Monday and fail on Tuesday. A gate whose result depends on the date teaches people to
> re-run red builds until they stop reading them.

Supporting details:

- **The base image's provenance is verified before we build on it** — `cosign verify` against
  Chainguard's OIDC identity, reading the digest straight out of the Dockerfile so the two
  cannot drift (ADR-0011). Trusting a base image because its *name* looks right is the
  supply-chain equivalent of not checking at all.
- **The smoke test is a real gate**, not a formality: it boots the container, asserts correct
  subnet maths over HTTP, asserts the running app reports the git SHA it was built from,
  asserts uid 65532, and asserts **no shell exists** in the image.
- **Gates and reports are separate steps.** Each scanner has a blocking gate (table output,
  HIGH/CRITICAL fixable only) and a non-blocking full report (SARIF, every severity, no ignore
  list) for the Security tab under the `trivy` and `grype` categories.
- **Privilege is split.** `build` can push but cannot sign (no `id-token`); `release` can sign
  but cannot build. Compromising either job alone does not yield *publish **and** bless
  arbitrary bytes*.
- **Merges are genuinely blocked on CI.** The `protect-main` ruleset
  ([`.github/rulesets/main.json`](.github/rulesets/main.json)) requires a PR and all four
  checks — `changes`, `lint`, `test`, `build` — sourced from GitHub Actions only (so a commit
  status faked via the API does not count), with an **empty bypass list**. `changes` is
  required explicitly: if it failed, `build` would be skipped, and skipped counts as passing.

---

## Keeping it current: Dependabot, auto-merge, drift

Pinning everything by content means nothing updates on its own. Three pieces keep the pins
fresh without turning the maintainer into a bottleneck:

| Ecosystem | Schedule | Merge |
|---|---|---|
| `docker` (Chainguard base) | daily, no cooldown | **auto-merge** once all required checks pass |
| `pip` | weekly, grouped | manual review |
| `github-actions` | weekly, grouped | manual review |

**Why only the base image is auto-merged.** Its trust decision is already enforced
cryptographically: `build` runs `cosign verify` against Chainguard's release identity before
building on the new digest (ADR-0011), and the Python-version assertion fails a bump that
changes the interpreter minor. A digest that fails either never merges. `pip` and Actions
updates have no equivalent provenance gate, so a human reads them.

**Why auto-merge uses a GitHub App, not `GITHUB_TOKEN`.** Events caused by `GITHUB_TOKEN` do
not start new workflow runs — GitHub's guard against recursive workflows. An auto-merge
enabled with it merges into `main`, the resulting `push` triggers nothing, `release` never
runs, and the fixed image is never published. It fails silently: the PR shows as merged. A
dedicated App (`contents` + `pull-requests` on this repository only, one-hour tokens) merges
as its own identity, so the `push` run happens. It is **not** on the ruleset's bypass list:
it can only *request* a merge that CI then has to allow.

**Drift.** With a differential PR gate, pull requests no longer reveal that the *published*
image has become vulnerable. `vuln-drift.yml` scans `:latest` daily with the absolute policy
and opens (or comments on) a `vuln-drift` issue while fixable HIGH/CRITICAL findings exist,
then closes it automatically once `:latest` scans clean. It reports; it never blocks.

How an upstream fix reaches production, end to end:

```
upstream fixes a CVE in the base ─► vuln-drift opens an issue
                                 ─► Dependabot opens the digest-bump PR
                                 ─► CI: provenance ✓  Python minor ✓  gates ✓
                                 ─► auto-merge (App identity) ─► push to main
                                 ─► absolute gate ✓ ─► push ─► sign + attest
```

No human step, and every step still fail-closed.

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

Compile under the **same Python the image ships** (`.python-version`). A container avoids
needing that version installed locally:

```bash
PY=$(cat .python-version)
docker run --rm -v "$PWD":/w -w /w python:$PY sh -c '
  pip install -q pip-tools &&
  pip-compile --strip-extras --generate-hashes -o requirements.txt requirements.in &&
  pip-compile --strip-extras --generate-hashes -o requirements-dev.txt requirements-dev.in'
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
| Python wheels | `fastapi` | `==X.Y.Z` + `--hash=sha256:…` | [0012](docs/adr/0012-hash-pinned-python-dependencies.md) |
| GitHub Actions | `actions/checkout@v4` | `@3d3c42e…` commit SHA | [0013](docs/adr/0013-sha-pin-github-actions.md) |

A tag is a *pointer*. Its owner — or whoever compromises them — can move it, and every build
that references it silently runs new code. This matters most for CI actions, which execute
with the workflow's `id-token: write` permission: an action running at that moment could sign
an arbitrary image with **this project's own identity**.

Pins nobody refreshes rot into a different security problem — see
[Keeping it current](#keeping-it-current-dependabot-auto-merge-drift).

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

Use the Python version in `.python-version` (pyenv, uv and `setup-python` all read it).

```bash
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt

python -m app                     # serves on :8000 (override with PORT)
curl "localhost:8000/api/v1/subnet?cidr=192.168.1.0/24"

python -m pytest                  # pure unit + API integration tests
ruff check .                      # style + flake8-bandit security lint
```

> `python -m pytest`, **not** bare `pytest` — the `-m` form puts the repo root on `sys.path`
> so `import app` resolves.

Build and exercise the container exactly as CI does:

```bash
docker build -t netcalc-api:ci --build-arg APP_VERSION=$(git rev-parse --short HEAD) .
docker run -d --name smoke -p 8000:8000 netcalc-api:ci
curl -sf localhost:8000/healthz && curl -sf localhost:8000/readyz
docker run --rm --entrypoint /usr/bin/python netcalc-api:ci --version   # must match .python-version
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
| [0016](docs/adr/0016-differential-pr-gate.md) | Differential PR gate, absolute release gate, auto-merged base-image bumps |

Hard-won operational findings live in [`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Runbook

### The build failed on a CVE

1. **On a PR or on `main`?**
   - *PR* → the gate is differential, so **this PR introduced the finding**. The Trivy gate's
     table in the log names the package.
   - *`main`* → the gate is absolute. Either the change introduced it, or the base went stale
     between the PR and the merge. Nothing was published either way.
2. **Is it fixable?** The gates only block on HIGH/CRITICAL **that have a fix available**. So
   if the build is red, a fix exists — apply it.
   - *A Python dependency* → bump it in `requirements.in`, re-run `pip-compile`, commit the
     regenerated lock.
   - *An OS package in the base* → the base digest is stale. Merge Dependabot's bump (normally
     already auto-merging), or re-resolve the digest by hand.
3. **Never suppress a fixable finding to get green.** That inverts the entire point.

### A `vuln-drift` issue was opened

The published image has a fixable HIGH/CRITICAL that appeared *after* it was published.
Expected path: Dependabot's base-bump PR is already open or about to be, and auto-merges when
green. If it is stuck, look at why its checks failed — usually the Python-version assertion
(next entry). The issue closes itself on the first clean `vuln-drift` run after the release;
to confirm sooner, run it by hand (`gh workflow run vuln-drift.yml`).

### A base-image bump failed "Assert image Python matches .python-version"

Chainguard's `latest` moved to a new Python minor. This is a migration, not a bump, and is
deliberately not auto-merged:

1. Set `.python-version` to the new minor.
2. Regenerate both locks under it ([command above](#dependencies-hash-pinned-locks)). If a
   compiled package has no wheel for the new minor at its pinned version, bump it in
   `requirements.in`.
3. Update `target-version` in `pyproject.toml` (ruff).
4. Push to the Dependabot branch (or a fresh one) — lint, tests and the image now agree.

### A CVE has no fix

Blocking on findings with no fix would freeze the pipeline indefinitely with **no remediation
path available** — which teaches a team to start ignoring red builds, the exact failure mode
ADR-0006 exists to prevent.

So the policy is **block on what can be fixed, surface everything else** (ADR-0014). The
non-blocking full reports send every finding to the Security tab, so unfixable ones are *on
the record*: accepted, visible, and self-clearing the moment upstream patches and Dependabot
bumps the digest.

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

Each of these cost real time, and each is now defended by a comment, a check, or an ADR:

- **A `pydantic-core` ABI mismatch fails at container *start*, not at build.** The builder's
  Python minor must match the base's — now enforced via `.python-version`.
- **Chainguard's `latest` changes Python minor silently.** CI kept testing on 3.14 while the
  image shipped 3.15; every gate stayed green and only the Security tab's package names gave
  it away. Now a CI assertion, not a README sentence.
- **`docker run image:latest` does not pull.** It runs whatever is cached locally — mine said
  3.14 while the registry's `latest` was 3.15. Check by digest, or `docker pull` first.
- **`trivy-action` with `format: sarif` ignores `severity`** (log: *"Building SARIF report with
  all severities"*), so `exit-code: 1` gated on fixable MEDIUM/LOW too — the gate was stricter
  than its documented policy for months, invisibly. Gate with `table`, report with `sarif`.
- **`if: always()` on a report step that needs an earlier step's output** runs it against a
  file that was never produced: a failed Trivy skipped the SBOM, Grype scanned nothing, and the
  SARIF upload died on empty JSON. Report steps now depend on the step that feeds them.
- **A merge made with `GITHUB_TOKEN` triggers no workflows** — auto-merge "works" and the
  release silently never runs. Hence the GitHub App.
- **Workflows triggered by Dependabot cannot read Actions secrets** — only Dependabot secrets.
- **A skipped required check counts as passing.** Fine for a docs-only PR; dangerous if the job
  that decides whether to skip can itself fail. That job is required too.
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
- **A merge queue.** "Require branches to be up to date" is off, because without a merge queue
  (not available to user-owned repositories) it stalls every auto-merged PR. Two PRs that are
  each green alone can therefore combine into a failure — caught by the absolute gate on
  `main`, but only after merging.
- **Verify the PR baseline before trusting it.** Whoever can move `:latest` controls what the
  PR gate ignores. The release gate does not use the baseline, so the impact is bounded, but
  `cosign verify` on the baseline digest would close it.
- **Multi-arch builds** (`linux/arm64`); currently amd64 only.
- **A rollback story.** Every build is addressable by immutable digest and `sha-<commit>` tag, so
  rollback is *possible* — it is not yet *automated*.
- **Attest the test results**, not just the SBOM. "These tests passed against this digest" is a
  stronger claim than "an SBOM exists".

---

*Image: [`ghcr.io/gastoniy/netcalc-api`](https://github.com/gastoniy/netcalc-api/pkgs/container/netcalc-api)*