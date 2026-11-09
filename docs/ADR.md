# Decisions and alternatives

1. Four separate immutable apphosts and separate generated v1/v2 contract assemblies. This avoids accidentally testing one rebuilt "old" binary. Apps, descriptors, source revision and hashes are preserved per candidate. Shared source for CLI scaffolding is compiled into separate binaries; schema and capability behavior differ.
2. .NET 10 LTS/C#14, gRPC .NET and local pinned Protobuf generation. No preview runtime, paid registry, remote generation, extra broker or homegrown transport. Buf FILE governs generated public APIs; explicit binary/JSON/semantic tests cover the boundaries FILE does not prove.
3. Explicit Npgsql SQL and a single state row lock. This trades concurrency for a small auditable transaction. No EF migration abstraction or competing persistence model hides the cutover.
4. One synthetic unit conversion. v1 ticks versus v2 explicitly confirmed milli-ticks supplies a concrete semantically unsafe reinterpretation that a wire-compatible addition alone cannot authorize.
5. Per-app resolved .deps.json runtime graph, full upstream licenses/copyrights and SPDX. Build-only Grpc.Tools and xUnit are recorded separately; server fixtures/Buf are pinned external references, never mislabeled as bundled libraries. NuGet normalized lock contentHash is distinct from SHA512 of the actual signed .nupkg archive.
6. Application-root configuration and explicit literal loopback Kestrel binding. Ambient working-directory configuration and proxy/redirect settings cannot silently move the lab onto a remote service. HTTP/2 is intentionally plaintext on loopback only; this is not a TLS/authentication product.

No benchmark/SLO latency claim is made. Correct outcomes, bounded resources/timeouts and explicit lost availability are the acceptance criteria. Architecture/handoff evidence demonstrates a decision and its proof, not an invented management history or production HFT deployment.
