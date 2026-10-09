# Changelog

## Unreleased

- Add experimental read-only Pocket Casts subscription sync with in-memory
  secret-manager login/session credentials, redacted failures, and additive imports.
  Live account validation matched 376 existing RSS subscriptions; no audio is queued.

- Add bounded RSS/Atom metadata screening, show-note searches, ranked local-rule
  recommendations, private caching, and persistent feed/episode overrides. Screening
  never downloads enclosures, queues processing jobs, or calls inference models.

- Add private, durable OPML subscription imports and URL-redacted feed listings.
  Importing subscriptions does not fetch feeds or queue episodes.

- Document the validated laptop-to-workstation audio handoff, queue ownership,
  recovery checks, and the remaining CPU alignment bottleneck.

- Handle English-only local Transformers ASR models without multilingual generation
  options. Timestamp validation still rejects invalid output before persistence.

- Add an explicit local `transformers` transcription backend for PyTorch/ROCm
  ASR, with independently placed WhisperX alignment. It requires a local model
  directory, floating-point compute type, and explicit language. The default
  WhisperX backend and existing job format remain unchanged.

- Support an explicit absolute `diarization_model_path` for offline local models,
  without requiring or passing Hugging Face credentials. Existing Hub-backed
  configurations retain their token requirement.

## 0.2.0 - 2026-10-03

- Separate ingestion and summarization queue stages; delete downloaded media
  after durable successful transcription and diarization.
- Pascal GPU support, pinned Python 3.13 dependencies, and core/GPU containers.
- Validate config and queue schemas; add Ruff, package, and container CI checks.
- Repair partial diarization handling, missing-audio diagnostics, independent
  CUDA library discovery, and interpreter selection for ML subprocesses.
- Add tag-driven release artifacts, checksums, SBOM, and dependency audit.

Compatibility changes before 1.0: unknown configuration keys are now rejected;
configured inference URL syntax and the existing loopback-only policy are checked
at startup, even for ingestion/status. No inference connection is made by those
commands, and ingestion-only configs may omit inference profiles. Queue/output
directories must be readable/writable and support directory fsync for durable
state and safe media cleanup.

## 0.1.0

- Initial local-first YouTube transcription and briefing prototype.
