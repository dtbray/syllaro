# Changelog

## Unreleased

- Replace hand-built web controls with vendored shadcn-svelte components, accessible
  artifact tabs and scroll areas, and system light/dark styling. API and queue
  behavior remain unchanged; frontend component/tool dependencies are pinned.

- Allow explicit web LAN binding with `--host IP`; loopback remains the default
  and browser same-origin writes and trusted-host checks remain enforced.

- Add an optional localhost FastAPI web adapter and Svelte 5 interface for existing
  jobs, YouTube submission, artifact viewing and locked retries. CLI submission and
  retry share the same queue operations; no worker or job-state migration is added.

- Add `submit --audio` for local recordings through the existing transcription,
  diarization, recovery and durable cleanup stages. Original recordings stay intact.
  Persisted `audio` jobs require an updated Syllaro core; older readers reject them.

- Add optional read-only Pocket Casts bookmarks, stars, Up Next, richer show notes,
  timed chapters and publisher transcript candidates. Bookmarked completed episodes
  can resurface for review; stars/Up Next boost ranking without bypassing exclusion.
  Add explicit private transcript exports without marking ASR/diarization complete.

- Add read-only year-based Pocket Casts history backfill with count verification
  and separate playback-state checks, extending listened-episode exclusions
  beyond the web player’s 100 recent history entries.

- Exclude known completed Pocket Casts episodes from default RSS screening using
  a private persistent listening ledger. Partial listens stay eligible; explicit
  episode overrides can resurface completed episodes. History coverage is recent-only.

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
