# Podcast audio pilot

The user-selected first audio batch processes five recommended episodes from
explicit priority feeds whose fetched Pocket Casts metadata advertises no
transcript. Known completed episodes remain excluded. This is an explicit batch,
not an automatic feed downloader, subscription-wide queue, or summary run.

The private source-side preparation script guards public HTTPS enclosure reads,
redirects, content types, download duration and size. It records failed intake
candidates separately and converts accepted recordings to mono 16 kHz WAV with
FFmpeg. Feed URLs, downloaded media, private manifests and transcripts stay outside
Git. Deterministic episode-based job IDs prevent duplicate jobs on repeated intake.

`submit /absolute/recording.mp3 --audio` also imports local files through the core
CLI. The new `audio` job kind validates absolute local sources, converts uncached
inputs with FFmpeg, and shares the existing speech pipeline. Original files outside
the job cache are preserved. Ordinary `ingest` may use the configured local ML
environment; the workstation pilot explicitly selects the SSH handoff instead.

The laptop owns the isolated `podcast-audio-pilot` queue and its exclusive worker
lock. The pilot handoff coordinator accepts cached audio jobs, fails if cached media
is missing, and transfers only WAV data to the existing isolated workstation
receiver. It never sends feed/account credentials or silently downloads on Pop!_OS.
The receiver uses the previously validated Transformers/WhisperX alignment and
pyannote community-1 configuration without dependency changes. Its global lock
serializes workstation speech work. Source queue recovery, result validation,
durable writes, checksum receipts and cleanup remain the same as the existing
[workstation handoff](gpu-rocm.md).

The one-shot `syllaro-podcast-ingest.service` claims at most five jobs and has a
12-hour batch deadline. No recurring podcast intake timer is enabled. Inference
profiles remain loopback-only and summarization is not launched. The idle Qwen
server on Pop!_OS was stopped to release approximately 12 GB of GPU memory; it was
not disabled or reconfigured.

Validation: regression tests cover local source validation, conversion without
YouTube download, preservation of original recordings, cached speaker-labelled
results without ML or inference calls, and retention of audio after failure.
Live queue intake and worker launch are distinct from completed real-media
validation; completion/status and timings belong in the private batch manifest.
