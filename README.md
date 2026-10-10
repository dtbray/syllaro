# Syllaro

A local-first assistant that turns media into timestamped, speaker-labelled
transcripts and concise briefings. Early prototype; see the
[first real-video test](docs/testing/2026-10-02-first-video.md) for measured CPU
timings and limitations. That test completed the audio pipeline and used an
assistant-written final briefing; automatic summary completion remains to test.

YouTube audio → WhisperX/pyannote → transcript → local LLM → Markdown briefing.
No paid API fallback. Inference endpoints must be loopback HTTP addresses;
workstation inference uses an explicit SSH tunnel and per-job profile.

## Development

Python 3.10–3.13 on Linux. The queue uses POSIX file locking.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m unittest discover -s tests -v
syllaro --help
```

Run `make check` for lint, formatting validation, and tests; `make format`
formats code, and `make build` builds the distributable wheel. Ruff is the
single linter and formatter, pinned to the same version locally and in CI.
CI checks the oldest and newest supported Python versions and builds a wheel.
ML dependencies remain separate from these lightweight development checks.
Configuration and persisted jobs have dependency-free typed schemas and runtime
validation in `src/syllaro/schema.py`. Existing jobs need no migration.
The validated GPU version snapshot and installation instructions are in
[`requirements/`](requirements/README.md).

Tests use a local mock inference server; no GPU, model weights, or API tokens
are needed. The core CLI uses the standard library. For actual audio processing:

```bash
pip install -r requirements-cpu.txt
pip install -c requirements-cpu.txt -e '.[transcription]'
```

Install FFmpeg separately. Transcription dependencies and first-run model
downloads are substantial. Direct ML dependencies are pinned; their transitive
dependencies are not yet locked. For the validated GTX 1050 Ti configuration,
see the [Pascal GPU setup](docs/gpu-pascal.md).

## First run

```bash
mkdir -p ~/.config/syllaro
cp examples/config.json ~/.config/syllaro/config.json
syllaro --config ~/.config/syllaro/config.json submit /absolute/transcript.txt --transcript
syllaro --config ~/.config/syllaro/config.json work
syllaro --config ~/.config/syllaro/config.json status
```

Configure an already-running local OpenAI-compatible Chat Completions server.
The example expects Ollama at port 11434 with `qwen3:4b`; this repository does
not install Ollama or its weights. Test summarization with a text transcript
before downloading/transcribing videos.

For a local audio recording, use `submit /absolute/recording.mp3 --audio` and
`ingest`. FFmpeg converts it into cached audio before the same transcription and
diarization stages. The original recording is retained; cached media is removed
only after durable speech artifacts. `ingest` does not contact a summary model.

For YouTube, submit a URL instead of a file and omit `--transcript`. Defaults:
Whisper small, CPU int8, four threads, batch size one, diarization enabled.
Accept the free [pyannote community-1 model terms](https://huggingface.co/pyannote/speaker-diarization-community-1)
and provide a read-only Hugging Face token as `HF_TOKEN` in the worker's
environment. Keep tokens outside Git and command-line arguments. Audio
processing runs locally. Set `diarize` to false to skip speaker attribution.
Speaker labels do not establish real names; overlapping speech needs review.
Silero performs speech detection without a gated model. Speaker diarization
runs separately after alignment, so a cached transcript can gain speaker
labels without repeating transcription. Its token is read from the environment.

For an already-authorized local model snapshot, set the optional
`diarization_model_path` to its absolute directory path. This explicitly selects
that model without requiring or passing `HF_TOKEN`; a missing directory fails
rather than falling back to the Hub. See [AMD/ROCm setup](docs/gpu-rocm.md)
for the isolated Pop!_OS workstation candidate and validation limits.
That guide also documents the explicit `transformers` transcription backend,
which loads an existing local model and can align on CPU while ASR and
diarization use ROCm. The default remains WhisperX; backend failures retain
media for retry instead of switching engines automatically.

Jobs and artifacts live under `~/.local/share/syllaro/`: raw audio, WhisperX
JSON, timestamped transcript, partial summaries, final summary, and process log.
Downloaded media is removed after successful transcription and configured diarization.
Failed ingestion retains media for retries. Failed
jobs require `syllaro --config ... retry JOB_ID`. Interrupted jobs recover on
the next worker run; an exclusive lock prevents concurrent workers.

## Workstation profile

Use `--profile workstation` when submitting a job to send its transcript to
a selectively available workstation model. Configure its model ID and tunnel
port in your local config. For example:

```bash
ssh -N -L 127.0.0.1:18083:127.0.0.1:8083 YOUR_WORKSTATION_SSH_TARGET
```

This offloads summaries only. It does not switch workstation models or offload
audio transcription. Neither an always-on service nor a container is provided
yet; both follow real-media validation.

## License

Copyright (C) 2026 Thomas Bray.

Syllaro is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option)
any later version. See [LICENSE](LICENSE). No warranty is provided.
Third-party dependencies retain their own licenses.

## Separate ingestion and summaries

`syllaro --config CONFIG ingest --limit 5` processes pending jobs without contacting
an inference server. Successful jobs become `transcribed`; timestamped text and
WhisperX speaker/word JSON are retained, and downloaded media is deleted.
`syllaro --config CONFIG summarize --limit 5` consumes ready transcripts using each
job’s selected profile. Schedule this command when the workstation is available.
Summary failures retain transcripts; `retry JOB_ID` returns them to `transcribed`.
Both stages share an exclusive lock and recover interrupted work. The original
`work` command still executes both stages for pending jobs.

Example user-systemd units live in `examples/systemd/`. The summary timer is
an example only: configure the workstation tunnel/model and choose the schedule
before enabling it. No API fallback or workstation wake-up is performed.

Container targets and one-shot Compose workers are available; see
[container setup](docs/containers.md) and [related projects](docs/related-projects.md).

CPU installs must keep `-c requirements-cpu.txt` on subsequent dependency
updates to preserve the CPU wheel pins. Automated summaries record the selected
inference profile; the first-video test’s `assistant` provider was recorded
manually when its briefing was written, not produced by the inference worker.

## Podcast subscriptions

Pocket Casts account subscriptions can also be merged read-only with
`sync-pocketcasts`; add `--enrich` for bookmarks, stars, Up Next, richer notes,
chapters and publisher transcript links. Bookmarked completed episodes can resurface
for review. `podcast-transcript EPISODE_ID` exports an advertised text candidate
without audio. See [authentication, ranking rules and transcript exports](docs/pocketcasts.md).

Import a UTF-8 OPML export without fetching feeds or creating episode jobs:

```sh
syllaro --config ~/.config/syllaro/config.json import-opml /path/to/podcasts.opml
syllaro --config ~/.config/syllaro/config.json feeds
```

Subscriptions are stored privately under the configured data directory in
`feeds/subscriptions.json` (directory 0700, registry 0600). Full feed URLs, including
subscription tokens or credentials, stay in that file and are omitted from command
reports/listings. Keep OPML exports and subscription registries out of Git.
Repeated imports deduplicate exact feed URLs, merge folder memberships and preserve
existing subscription preferences. Malformed documents leave the registry unchanged;
invalid entries are reported as skipped with a nonzero command exit rather than
claiming a complete import. [Details](docs/podcast-subscriptions.md).

This is subscription management only. Episode audio downloads and RSS media-job
support remain separate work; imported subscriptions do not start background fetching,
transcription, diarization or summarization.

## Metadata-first episode screening

```sh
syllaro --config ~/.config/syllaro/config.json screen-feeds
syllaro --config ~/.config/syllaro/config.json screening --decision process --limit 20
syllaro --config ~/.config/syllaro/config.json screening --query "automation"
```

This reads RSS/Atom titles and show notes without audio downloads or model calls.
Local keyword rules favor actionable technical/DIY interests; thin notes require
review. Recommendations and manual overrides are stored privately and never enqueue
work automatically. Fetch failures remain visible, and oversized feeds are explicitly
marked when sampled. [Screening details and overrides](docs/metadata-screening.md).

## Local web interface

The optional Svelte 5 interface shows existing jobs, submits YouTube sources,
views timestamped/speaker-labelled transcripts and sanitized Markdown briefings,
and retries failed jobs using the existing worker lock. It polls every five seconds
while pending/running/summarizing jobs exist and supports manual refresh. No worker
is launched by HTTP requests; keep your existing `ingest`, `summarize`, or `work`
service running. A worker processes a queue snapshot, so newly submitted jobs wait
for its next invocation. Transcribed jobs can remain ready without summarization.

Build and start from the repository root (Node 20.19+ or supported newer LTS,
npm 9.5+):

```bash
python3.13 -m venv .venv-dashboard
.venv-dashboard/bin/python -m pip install --require-hashes -r requirements/dashboard.lock.txt
.venv-dashboard/bin/python -m pip install --no-deps -e .
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run build
.venv-dashboard/bin/syllaro-web --config ~/.config/syllaro/config.json
```

Open **http://127.0.0.1:8765**. FastAPI serves `frontend/dist` and the API in one
process; Node is unnecessary after building. Run from the checkout root or provide
`--frontend-dir /absolute/path/to/frontend/dist`. Assets are separate from the Python
wheel; retain the built directory when installing the wheel elsewhere. The core
CLI installation has no new runtime dependencies. `pip install '.[web]'` is an
alternative optional runtime installation; the hashed web lock also supplies HTTPX
for API tests. Keep this environment separate from active ML environments.

For development, run the API command above in one terminal and
`npm --prefix frontend run dev` in another. Open http://localhost:5173; Vite provides
HMR and proxies `/api` to localhost:8765. Generate TypeScript contracts with
`npm --prefix frontend run contracts` after API model changes. The generation uses
synthetic queue configuration, never your private records.

Additional queues must be explicitly configured by the server operator:

```bash
.venv-dashboard/bin/syllaro-web --config ~/.config/syllaro/config.json \
  --queue rising-tide=~/.config/syllaro/rising-tide.json \
  --queue podcast-audio=~/.config/syllaro/podcast-audio-pilot.json \
  --queue publisher-transcripts=~/.config/syllaro/podcast-transcript-pilot.json
```

The API exposes `/api/v1/health`, `/jobs` (GET/POST), `/jobs/{id}`,
`/jobs/{id}/transcript`, `/briefing`, `/action-items` (GET), and
`/jobs/{id}/retry` (POST), all under `/api/v1`. Optional `queue=NAME` selects only
configured queues. OpenAPI is available at `/openapi.json`. Invalid records are
counted rather than silently presenting a complete list. Retry returns 423 while
an existing worker owns the queue and 409 for jobs that are not failed.

The server binds to 127.0.0.1 by default. For explicitly authorized LAN access,
pass `--host YOUR_LAN_IP`; this exposes job submission and private artifacts without
authentication to devices that can reach that address. Bind a concrete interface IP
rather than every interface. To retain loopback-only access, use an SSH
loopback forward: `ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 USER@SYLLARO_HOST`.
Local browser writes must be same-origin. Artifacts are private data; Markdown is
sanitized in the browser. There is no scheduling, worker administration, model
configuration, audio playback, or transcript editing. Browser artifact reads are
limited to 16 MiB. RSS subscription/screening administration remains in the CLI.

Web checks (no GPU/model execution):

```bash
.venv-dashboard/bin/python -m unittest discover -s tests -p test_web.py -v
npm --prefix frontend run check
npm --prefix frontend run build
# First browser-test setup only:
cd frontend && npx playwright install chromium && npm test
```

The core test suite skips only optional HTTP tests if FastAPI/HTTPX are absent;
shared queue-operation tests still run. Browser tests use synthetic mocked API data.
