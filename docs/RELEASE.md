# v0.1.0-preview.2 - Contract Evolution & Safe Rollout Lab

Connection ownership correction: a newly allocated Npgsql connection remains owned by `Store` until opening succeeds. Failure and cancellation await disposal before rethrowing the original exception; cleanup failure cannot replace it. Successful open transfers the live connection to the existing caller. SQL, transaction semantics, pooling, public contracts and dependencies stay unchanged.

Nine ownership regressions include real refused loopback connections and cancelled handshakes, object-reuse disposal checks, awaited cleanup, secondary cleanup failures and successful ownership transfer. The red observation seam preserves the original await-open/return behavior; the same test bytes then pass after cleanup is added. These tests do not measure production leaks or performance.

C# layout is expanded in a separate reviewed delta from the ownership repair. Full-tree syntax, exact token text/values and non-whitespace trivia are preserved. Frozen architecture evidence remains tied to the earlier release; this preview has its own source and native delivery evidence.

Fresh synthetic Contract Evolution & Safe Rollout Lab: four versioned apphosts, pinned local Buf FILE checks and immutable descriptors, additive and semantic counterexamples, real gRPC matrix, PostgreSQL expand/restartable backfill/contract, cross-version business identity and before/after-commit owned-process faults.

Legacy-writer correction: v1 at stages 0/1 names and supplies only legacy SQL columns/parameters, while v2 writes both representations during expand and only the new representation after contract. The 14-case integration profile proves omission with an independent test-only pre-fill guard plus a named-error negative probe, checks the original unit invariant and immutable application/Core/contract hashes across all stages, and retains the old/new matrix and uncertainty cases. The prior local counterexample is preserved; shared/real databases and product guard strength are unchanged.

Published packages require native build/test/package jobs on each target OS, exact-commit manifests and actual download verification. Local cross-built candidates are explicitly distinguished in their manifests. A source push or CI artifact is not a production deployment or performance result.

Signed provenance uses the established public key. Full resolved/runtime dependency graph includes both .NETCore and ASP.NETCore runtime packs and original notices. No private/shared assets, account/market connection or resume changes.
