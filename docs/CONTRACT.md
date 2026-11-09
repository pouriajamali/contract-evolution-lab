# Version and migration contract

Wire: proto3 package evolution.v1, stable actions.proto path, explicit optional presence for semantic_version/capability/unit. Removed tag 6 and its old name are reserved. v2 adds confirmation/memo and enum values; Buf FILE must pass. Changing amount's int64 wire type is an executable negative fixture, not an alternative published schema.

Consumers accept the legacy tuple (version=1, BASIC=1, TICKS=1). v2 additionally accepts (version=2, MILLITICKS_CONFIRMED=2, MILLITICKS=2, confirmed=true) with exact conversion to integer ticks. Missing/unknown enum values, missing required presence, unknown versions, fractional conversions or unbounded identities/amounts deny before a transaction. A v1 binary parsing unknown v2 fields does not authorize them.

Business identity is a 1..64 lowercase ASCII alphanumeric/hyphen operation_id. Canonical SHA256 input is UTF-8 "effect-v1\\n{id}\\nTICKS\\n{normalizedTicks}\\n", with invariant decimal digits. Identity is independent of wire version and representation. UNIQUE(operation_id), request digest, effect amount, aggregate total and first result are committed together. Duplicate same intent replays; different intent conflicts. This is a trusted synthetic capability contract, not identity/security authentication.

| Stage | v1 writer | v2 writer | Stored amount | Rollback |
| --- | --- | --- | --- | --- |
| 0 legacy | accepts legacy semantics | normalizes then writes legacy | amount_ticks | no migration to undo |
| 1 expanded | trigger fills new column for new effects | writes both representations | legacy rows may still have NULL scaled values | demonstrated rollback to 0 |
| 2 contracted | explicit SCHEMA_UNSUPPORTED, including replay | writes new column | NOT NULL amount_scaled | ROLLBACK_BLOCKED |

Every writer locks the singleton stage/state row FOR UPDATE before checking or writing. Migration takes the same lock: an in-flight write finishes before the stage moves, and a later old writer reads the new stage and stops. The demo actually stops the owned old server before contract and acknowledges this precondition; it also restarts an old binary afterward to verify rejection. This is not a production process registry or deployment controller.

Expand adds a nullable column and a dual-write trigger that independently rejects inconsistent units. Backfill processes at most 32 rows per transaction (demo uses 7), updates a durable progress count with those rows and restarts by selecting remaining NULL rows. It uses no unsafe external high-water cursor. New old-version inserts are filled by the trigger. Contract refuses until all rows have valid matching units, then atomically removes the old column/trigger and advances stage to 2. Backfill cannot silently skip its invariant.

Before contract, rollback drops the new representation and retains all normalized legacy amounts/identities/receipts. After contract, data/schema rollback is explicitly unsupported and blocked; rebuilding old binaries or parsing messages cannot recover the removed schema. External database restore/rollback, multiple sites, deployment orchestration, and arbitrary schema changes are outside this lab.

Fault hooks are opt-in lab environment variables, bounded to 20 seconds; before/after-commit tests kill only owned consumer processes. The client reports UNKNOWN after a lost RPC. Same-identity replay/query of the authoritative history resolves it. Ordinary PostgreSQL process restart preserves effects/receipts. A restored older database is not ordinary process restart.
