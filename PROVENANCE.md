# Verify provenance

Independently trusted ED25519 fingerprint:
`SHA256:AgU5bZlJSjUu0KsWMmVEEr+BfXpcMVNroTA33bHcQdU`.

Verify the downloaded SHA256SUMS signature and selected archive before extraction:
```sh
python tools/verify_downloads.py --directory DOWNLOAD_DIRECTORY --work NEW_VERIFY_DIRECTORY --trusted-fingerprint SHA256:AgU5bZlJSjUu0KsWMmVEEr+BfXpcMVNroTA33bHcQdU --archive EXACT_SELECTED_ARCHIVE_FILENAME
```
Use a separately trusted copy of this verifier/source. A checksum, public key or verifier downloaded beside an untrusted archive cannot itself establish trust. Exactly one canonical SSH ed25519 key is accepted; attacker-added keys/principals/comments and case-altered fingerprints fail. Validation remains active under python -O / PYTHONOPTIMIZE.

Signed commits, annotated tags and checksum files establish source/archive provenance under that key. They do not establish exclusive ownership, Windows Authenticode, production certification, reproducible byte builds, a SLSA level or security completeness. Local candidate, native CI artifact and actual public download receipts are separate. Never transfer the private key.

SBOM SHA512 values, when present, refer to raw signed NuGet .nupkg archive bytes at the build. NuGet lock contentHash excludes package signatures and is retained separately as the normalized restore identity; it is not mislabeled as the raw archive checksum.
