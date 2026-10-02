# Syllaro

A local-first assistant that turns media into timestamped, speaker-labelled
transcripts and concise briefings. Early prototype; real-media testing is next.

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

Tests use a local mock inference server; no GPU, model weights, or API tokens
are needed. The core CLI uses the standard library. For actual audio processing:

```bash
pip install -e '.[transcription]'
```

Install FFmpeg separately. Transcription dependencies and first-run model
downloads are substantial. Direct ML dependencies are pinned; their transitive
dependencies are not yet locked. GPU support has not been validated.

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

For YouTube, submit a URL instead of a file and omit `--transcript`. Defaults:
Whisper small, CPU int8, four threads, batch size one, diarization enabled.
Accept the free [pyannote community-1 model terms](https://huggingface.co/pyannote/speaker-diarization-community-1)
and provide a read-only Hugging Face token as `HF_TOKEN` in the worker's
environment. Keep tokens outside Git and command-line arguments. Audio
processing runs locally. Set `diarize` to false to skip speaker attribution.
Speaker labels do not establish real names; overlapping speech needs review.

Jobs and artifacts live under `~/.local/share/syllaro/`: raw audio, WhisperX
JSON, timestamped transcript, partial summaries, final summary, and process log.
Audio is retained for retries; retention cleanup is currently manual. Failed
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
