# Notices and attribution

Original synthetic lab: Copyright (c) 2026 Pouria Jamali, MIT (LICENSE).

Delivery/provenance fixture, canonical single-key verifier, notice resolver and extracted PostgreSQL fixture lifecycle are adapted from the public MIT [Fenced Shard Ownership Lab](https://github.com/pouriajamali/fenced-shard-ownership-lab/tree/7c853fde7bf2aeab9bf60f6b6e979cb17738d802); retain its original MIT notice. The fixture contains a public key/signature only. Regression tests generate their own disposable attacker keys privately, never copy or bundle the signing private key.

Shipped components retain their licenses/copyright: Google.Protobuf BSD-3-Clause (pinned original Google text), gRPC .NET Apache-2.0, Npgsql PostgreSQL license, Microsoft.Extensions/.NETCore/ASP.NETCore runtime MIT plus supplied third-party notices. Exact full-text sources, NuGet content identities and original copyrights are frozen in vendor/notices/NOTICE-SOURCES.json. Packages include a DEPENDENCIES.json and actual shipped SPDX graph; no dependency is relabeled MIT by the original-code license.

Grpc.Tools, Buf and xUnit are build/test tools, not bundled runtime libraries. Five pinned upstream PostgreSQL/support archives and native Buf binaries are separate downloaded references under their own upstream licenses. Source pins do not claim vendor-signature verification. No public/private partner code, data or shared project ownership is transferred.
