# Releases

Syllaro follows SemVer: patches fix compatible behavior, minors add features,
and majors break the public CLI/config contract. Before 1.0, breaking changes
may ship in a minor release and must be identified in the changelog.

Inspired by HaloCLI's tag-driven GitHub release workflow: build a wheel and
source distribution, check metadata, generate an SBOM, audit dependencies, and
publish installable assets. No package-upload token is required. The SBOM/audit
cover the lightweight core runtime; the GPU snapshot is a separate dependency
surface and is included as a release asset, not represented as audited by the
core environment scan.

Update `pyproject.toml` and `CHANGELOG.md` in a reviewed PR. Once merged and CI
passes, tag the main commit using the exact package version:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The release workflow refuses a tag/version mismatch, runs tests and Ruff,
builds distributions, smoke-tests the installed wheel from outside the checkout,
and publishes GitHub assets with SHA-256 checksums. A manual dispatch accepts
an existing tag for recovery. Release artifacts come from CI. GPU container
validation remains separate; a release does not claim untested GPU deployment.
