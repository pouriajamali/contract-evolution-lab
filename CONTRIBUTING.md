# Contributing

Use fresh synthetic counterexamples and explicit expected outcomes. Preserve the old schema/binary/descriptor baselines. Do not add live feeds, account APIs, real orders, paid services or production deployment paths.

Start with policy tests, then real Buf checks, then the four-binary/PG demo on both native client platforms. Keep sensitive demo folders private. Report source revision, OS, command, sanitized status and the smallest counterexample. Do not claim a parse/lint/test result proves authorization, recovery or production compatibility.

A reviewable change states the engineering decision, forbidden behavior, executable test and boundary. Existing v1 behavior is an immutable acceptance baseline; any intended break needs a separately reviewed version/migration contract.
