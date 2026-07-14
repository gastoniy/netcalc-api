# ADR-0012: Hash-Pinned Python Dependencies as the Single Source of Truth

**Status:** Accepted
**Date:** 2026-07-13

## Context

The pipeline signs images, attests their SBOMs, and generates SLSA provenance —
all of which are claims about *what is inside the artifact*. Those claims were
being made about contents that were never actually fixed:

- `requirements.txt` declared `fastapi`, `uvicorn`, `prometheus-client` with **no
  versions at all**. CI and the Dockerfile both install from it, so two builds of
  the same commit could — and eventually would — resolve to different dependency
  versions. Signing that is signing a moving target.
- A `Pipfile`/`Pipfile.lock` also existed, pinning *different* versions
  (`fastapi==0.115.6`), declaring `python_version = "3.12"`, and read by nothing:
  not CI, not the Dockerfile. Worse, `fastapi==0.115.6` predates pydantic-core's
  cp314 wheels, so anyone following the repo's own documented pipenv workflow on
  Python 3.14 would hit exactly the compiled-wheel ABI trap ADR-0004 warns about —
  a failure that surfaces at *container start*, not build time.
- Even with `==` pins on the three direct dependencies, the transitive graph
  (pydantic, pydantic-core, starlette, anyio, h11, click …) would still float, so
  the image would still not be reproducible and a hijacked transitive would still
  land in it.

This is the same argument as ADR-0005 (digest-pin base images), applied one layer
up: an unpinned dependency is a mutable reference, and every integrity claim built
on top of a mutable reference is weaker than it looks.

## Decision

Adopt a compiled-lock workflow, and make `requirements*.txt` the **single** source
of truth for dependencies.

- Humans edit `requirements.in` / `requirements-dev.in` (direct deps, `==`-pinned).
- `pip-compile --generate-hashes` compiles each into a fully-resolved
  `requirements.txt` / `requirements-dev.txt` covering the whole transitive graph,
  every package carrying its sha256 hashes:

  ```bash
  pip-compile --strip-extras --generate-hashes --output-file=requirements.txt requirements.in
  pip-compile --strip-extras --generate-hashes --output-file=requirements-dev.txt requirements-dev.in
  ```

- The Dockerfile installs with **`pip install --require-hashes`**, so a wheel whose
  bytes don't match the lock fails the build rather than shipping.
- **`Pipfile` and `Pipfile.lock` are deleted.** `.vscode/settings.json` moves from
  the pipenv env-manager to plain venv.

`pip-tools` is chosen over `uv` deliberately: pip-compile writes a header that
Dependabot's `pip` ecosystem recognises and can regenerate *including hashes*, so
the lock is kept fresh by the same bot that refreshes the base-image digests and
action SHAs. A uv-generated lock would sit and rot.

## Consequences

- The bytes installed into the image are now fixed and reproducible. The signature,
  SBOM attestation, and provenance are claims about a determinate artifact.
- Hash-checking is not just for the image: pip enables hash-checking mode for *all*
  requirements as soon as any one carries a hash, and `requirements-dev.txt` includes
  the runtime deps via `-r requirements.in`. So CI's `pip install -r requirements-dev.txt`
  became hash-verified with no workflow change.
- Adding or bumping a dependency is now a two-step operation (edit the `.in`,
  re-run `pip-compile`) and produces a large generated diff. That friction is the
  point — it makes an unreviewed dependency change hard to do by accident.
- One source of truth means the pipenv workflow is gone; contributors use a plain
  venv. The `.in`/`.txt` split must be respected — hand-editing a `.txt` will be
  silently overwritten on the next compile.
- Pinning forward to current versions (fastapi 0.139.0, uvicorn 0.51.0,
  prometheus-client 0.25.0) resolves pydantic-core to 2.46.4, which ships cp314
  manylinux wheels — so the ABI hazard from ADR-0004 is closed rather than merely
  documented.

## Alternatives Considered

- **Plain `==` pins, no hashes** — rejected: fixes the direct deps but leaves the
  transitive graph floating, so the image still isn't reproducible and a compromised
  transitive package still reaches production.
- **`uv` for lock generation** — attractive (much faster), but Dependabot would not
  regenerate the resulting lock. Freshness matters more than compile speed here, for
  the same reason ADR-0005 pairs digest-pinning with an update bot: a pin nobody
  refreshes becomes a security liability, not an asset.
- **Keep the Pipfile for local dev, requirements for CI** — rejected: two manifests
  that must never drift *will* drift. They already had, in both version and Python
  version, and the drift was actively dangerous.
