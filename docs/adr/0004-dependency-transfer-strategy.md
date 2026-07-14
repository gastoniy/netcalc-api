# ADR-0004: Multi-Stage Dependency Transfer via `site-packages`, Not a Portable venv

**Status:** Accepted
**Date:** 2026-07-12

## Context

The conventional pattern — create a venv in the builder stage, copy the whole
venv into a minimal final stage — breaks in true-distroless final images.
`python -m venv` creates `venv/bin/python` as a symlink to the interpreter that
created it (e.g. `/usr/local/bin/python3.12` in a Debian-based builder). A
distroless final image ships Python at a different absolute path with no shell
to diagnose the failure, so the copied symlink dangles and the container fails
to start with a confusing missing-interpreter error.

## Decision

Do not rely on a copied venv's own interpreter at runtime. Instead:
- Install dependencies directly into the builder's `site-packages` (no venv
  needed at all, since the builder stage is single-purpose and discarded), or
  create the venv with `--without-pip` and install with `pip install --target=`
  pointing straight at the intended final `site-packages` path.
- Copy only `site-packages` (or the app-relevant subset) to the *identical
  absolute path* in the final image, which is already on that image's own
  interpreter's default `sys.path`.
- Invoke the final image's own baked-in interpreter (`ENTRYPOINT ["python3",
  `"-m", "app"]` or the base image's default entrypoint), never a copied venv
  binary.
- Strip `pip` (and `setuptools`/`wheel` if present) from the copied
  `site-packages` before shipping — build-time tooling with no runtime purpose
  and no `pip` binary available to run them with anyway.

## Consequences

- Eliminates the broken-symlink failure mode entirely — there is no venv
  interpreter to break, because it's never executed.
- Requires the builder's Python **minor version to exactly match** the final
  image's Python version, since compiled-wheel ABI tags (e.g. `cp311` vs.
  `cp312`) are version-specific — this is the direct link to the bug found and
  fixed in ADR-0003.
- Slightly smaller final image and reduced scan surface from excluding
  build-only packages.

## Alternatives Considered

- Copy the full venv including its own interpreter — rejected, this is exactly
  the pattern that produces the broken-symlink failure.
- `PYTHONPATH` pointing into a still-present venv directory — viable but
  strictly more moving parts than aligning the copy path with the final
  image's default `sys.path`.
