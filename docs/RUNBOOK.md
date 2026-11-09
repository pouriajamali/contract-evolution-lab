# Runbook and review

Expected full demo: all named cases PASS; independent SQL history ends at stage 2 with 50 unique effects, total 1554. The first failed Windows oracle (nullable unbackfilled column) and first Linux startup timeout were retained privately; neither was claimed as a pass. Final candidate receipts supersede uncommitted vertical slices.

Investigate in this order: native executable --version and exact commit; package file manifest; pinned upstream archive hashes; sanitized host-error.json; service stdout/stderr; private history and SQL oracle. Never paste the private connection file or whole demo folder into an issue. A digest/signature verifies provenance, not production suitability.

An earlier extracted Windows candidate returned UNKNOWN for seed-33 during normal setup and was not declared a pass; its private owned database/logs were preserved, without inferring whether that effect committed. The final harness preserves partial histories on every failure. For normal new-operation setup it explicitly resolves UNKNOWN at most twice with byte-identical requests and the same identity, accepts only APPLIED/REPLAY after independent SQL verification, and reports normalUnknownResolutionAttempts. Resolution is not a claim that the first attempt was available or successful. Explicit crash tests still expose the original UNKNOWN before resolution. Unresolved outcomes fail the bounded demo; no new identity is generated to hide them.

On UNKNOWN preserve the original operation identity, intended amount/unit/version and output. Do not invent another ID. Restart only this owned lab profile if required; its source never resets an existing database/schema to force a pass. init refuses an existing schema. Existing output paths fail instead of deleting evidence.

Stop old writers before contract. Incomplete backfill returns INVARIANT_NOT_READY with stage unchanged. After contract, ROLLBACK_BLOCKED is the intended result. Stop and plan a separately reviewed forward migration; do not drop constraints or rewrite history.

Profile bounds: 15 minutes, 256 MiB log cap, PostgreSQL 64 MiB shared buffers / 24 connections / 256 MiB max_wal_size; these are configured limits, not guarantees on total process RSS or peak disk. Request/database deadlines are finite. Existing Linux access, libraries, local disk/compute and downloads remain prerequisites.

Review slices: (a) wire/presence and semantic denial, (b) durable identity and commit uncertainty, (c) schema/backfill and old binaries, (d) notices/provenance/package/native execution. Run actual code and inspect separate receipts; static source, CI and runtime evidence are distinct.
