# ADR-0002: Two-Tier Test Architecture (Pure Logic vs. API Integration)

**Status:** Accepted
**Date:** 2026-07-12

## Context

A CI pipeline's test gate is only trustworthy if the suite is fast,
deterministic, and its failures are easy to localize. Mixing business-logic
edge cases with HTTP-level concerns in one test file makes failures ambiguous
and slows the suite down with unnecessary app bootstrapping for cases that
don't need it.

## Decision

Split tests into two layers:
- `tests/test_calculator.py` — unit tests calling `app/calculator.py` functions
  directly, no HTTP involved. Covers edge cases exhaustively (via
  `pytest.mark.parametrize`) including `/31`, `/32`, IPv6 `/64`, and oversized
  splits.
- `tests/test_api.py` — integration tests via FastAPI's `TestClient` (in-process
  ASGI calls through `httpx`, no real socket/server), checking routing, error
  mapping (400 vs. 422), and response shape.

## Consequences

- The unit layer caught a real bug before it shipped: computing host counts via
  `list(net.hosts())` enumerates every address, which OOM-kills the process on
  an IPv6 `/64` (2⁶⁴ addresses). Fixed to O(1) arithmetic; a regression test
  (`test_ipv6_64_does_not_enumerate`) guards against recurrence.
- API tests stay fast and deterministic because `TestClient` never opens a
  socket — no flaky "server not ready" failures in CI.
- Splitting 400 (business-logic rejection) from 422 (framework/Pydantic request
  validation) in the API tests makes the validation boundary explicit and
  testable.
- `ruff`'s `S101` (assert-in-production-code) rule is suppressed for `tests/*`
  only, since asserts are the intended mechanism there, not a security smell.

## Alternatives Considered

- Single flat test file — rejected: slower feedback loop, and edge-case
  coverage would be diluted by needing an app instance for every test.
