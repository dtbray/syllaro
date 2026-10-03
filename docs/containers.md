# Containers

The core target packages queue management and summarization without ML packages.
The pascal target adds FFmpeg and the Python 3.13 GPU dependency snapshot.
No model weights, tokens, cookies, or host virtualenvs enter the build context.

## Core CLI

Run from the repository root:

```bash
mkdir -p data models
export SYLLARO_UID=$(id -u) SYLLARO_GID=$(id -g)
docker compose build cli
docker compose run --rm cli status
docker compose run --rm cli submit https://youtu.be/VIDEO_ID --profile workstation
```

For GPU ingestion, provide an external mode-600 secrets file with HF_TOKEN and
set SYLLARO_SECRETS_FILE to its absolute path. Install/configure the NVIDIA
container toolkit on the host before requesting GPU devices. The host driver
remains outside the image. Build and run explicitly:

```bash
docker compose --profile gpu build ingest
docker compose --profile gpu run --rm ingest
```

Containers run as the selected UID/GID with a read-only root filesystem.
Create writable data/cache directories with matching ownership; change
SYLLARO_DATA_DIR and SYLLARO_CACHE_DIR to use existing directories. A private
container config can be mounted with SYLLARO_CONFIG_DIR; data_dir must be /data.
The queue uses the same lock file, so native and container workers must share
the exact queue mount and must not run concurrently. Existing transcript-file
jobs may contain host absolute source paths; mount those explicitly or submit
new paths that exist inside the container.

## Scheduled summaries

The summary service is a one-shot command and uses Linux host networking to
reach a loopback inference endpoint or SSH tunnel. No port is published.
Configure the actual model/endpoint first, then invoke this from a host timer:

```bash
docker compose --profile summary run --rm summarize
```

These files do not replace the running native ingestion timer automatically.
Validate GPU transcription and diarization in the container before switching
that timer. NVIDIA container runtime configuration and GPU media validation
are still outstanding on this host.

## Checks completed

Both image targets built successfully from a fresh Python base. The Pascal
image passes `pip check` and non-root imports of Torch, TorchCodec, WhisperX
ASR/diarization, and CTranslate2. The core image passed submit/status persistence
with a read-only root filesystem and dropped capabilities. Compose validates
with both profiles enabled. These checks do not establish GPU access or real
media processing inside a container.
