# Changelog

## 0.2.0 - 2026-10-03

- Separate ingestion and summarization queue stages; delete downloaded media
  after durable successful transcription and diarization.
- Pascal GPU support, pinned Python 3.13 dependencies, and core/GPU containers.
- Validate config and queue schemas; add Ruff, package, and container CI checks.
- Repair partial diarization handling, missing-audio diagnostics, independent
  CUDA library discovery, and interpreter selection for ML subprocesses.
- Add tag-driven release artifacts, checksums, SBOM, and dependency audit.

## 0.1.0

- Initial local-first YouTube transcription and briefing prototype.
