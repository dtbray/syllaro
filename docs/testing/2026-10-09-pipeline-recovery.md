# Pipeline failure recovery — 2026-10-09

## Causes and changes

The initial podcast pilot rejected four recordings during Transformers ASR: two
had missing chunk endpoints and two had invalid chunk endpoints. The experimental
30-second pipeline chunk merge was replaced with Whisper's native sequential
long-form generation (`return_timestamps=True`, `return_segments=True`). Input
features are not truncated. Native segment boundaries are still validated; missing,
nonfinite, negative, reversed or out-of-order starts are rejected, never guessed.
WhisperX independently aligns words on CPU; the ASR model and GPU tensors are
released before alignment/pyannote. Generic speaker labels remain unchanged.

Nine historical YouTube downloads had HTTP 403 responses. Their logs also showed
no supported JavaScript runtime. A separate hashed download-only environment adds
`yt-dlp[default]==2026.8.19`, `yt-dlp-ejs==0.8.0` and dependencies; the active ML
virtualenv is not upgraded. Deno 2.9.7 is installed in a private runtime directory,
with its release archive verified against the published SHA-256:
`c6527f24f4b16031d3ae4fa9f658d5f11534c8d84ce7dc8502420280919c3490`.
Workers explicitly prepend that directory to PATH. The recovery downloader prefers
public HLS audio (`bestaudio[protocol=m3u8_native]/bestaudio/best`), since one
recording still rejected its direct Opus stream but served its HLS audio. No browser cookies are copied
and no credentials are passed to the workstation.

Subprocess failures now use bounded diagnostics from only the current attempt's
log, returning recognized causes without full command arguments or signed URLs.
The existing private workstation receiver returns a small failure receipt to the
coordinator, so SSH's exit code doesn't hide the actual speech failure. Queue
schema and worker/retry/receipt locks are unchanged. The stray authentication-test
JSON was moved into private diagnostics instead of deleting it or treating it as a
job. Existing successful jobs and transcripts are retained.

## Validation environment and initial evidence

AMD RX 9060 XT 16 GB, Ryzen 5 7500X3D, 32 GB RAM, Pop!_OS Linux. Existing isolated
candidate dependencies remain Torch `2.8.0+rocm7.2.1.lw.gitd733adb1`, Transformers
4.57.6, WhisperX 3.8.6 and pyannote-audio 4.0.7. Patched source is deployed under a
separate recovery directory and selected with process-scoped PYTHONPATH; no model
or ML package upgrade is performed. Whisper small, English, fp16, five beams;
CPU word alignment; local community-1 GPU diarization remains configured.

A 90-second cached-audio sample completed native ASR in 7.5 seconds and alignment
in 4.9 seconds. This is real GPU/media evidence, distinct from mocked tests. A
formerly failing public YouTube recording also yielded actual audio bytes with
the isolated downloader (a 10 KiB download probe, not merely metadata extraction).
The first formerly failing 33.3-minute podcast completed native ASR in 85.8 seconds,
CPU alignment in 94.4 seconds and diarization in 57.8 seconds. Its durable returned
artifact contains 716 segments, 5,645 words and `_syllaro_diarized=true`; the source
validated its timestamp/speaker structure and stored a workstation receipt. This
is structural validation, not a claim of transcription accuracy or speaker identity.
WhisperX may retain native segment boundaries for phrases it cannot align; not
every individual word is guaranteed to have a timing.

All nine formerly failing YouTube recordings (244.6 minutes of published duration)
were fully downloaded to cached WAV files and checked with FFprobe, then retried
through the shared queue operation. The last recording required its public HLS
audio stream. No successful job was reset. Podcast recovery runs before the
YouTube recovery worker; both use existing queue/workstation locks. The regular
ingestion timer resumes automatically after the recovery worker exits. Jobs that
are pending/running are not described as completed. No private media, transcript text, feed URLs or weights are
included in this report.

## Reproduction

Use the optional Transformers profile and existing local model weights for native
ASR. For downloading, create a separate environment:

```bash
python3.13 -m venv .venv-download
.venv-download/bin/python -m pip install --require-hashes -r requirements/download.lock.txt
```

Install a supported Deno runtime following the upstream instructions, verify its
release checksum, and put its directory and `.venv-download/bin` ahead of the ML
venv on the ingestion worker's PATH. This deliberately does not modify the active
ML environment. Use existing `retry` operations only for failed jobs; retained
cached audio avoids downloading a recording again. Keep one workstation speech
handoff active at a time.

References: [Whisper native long-form generation](https://huggingface.co/docs/transformers/v4.57.2/en/model_doc/whisper),
[yt-dlp JavaScript runtime and EJS setup](https://github.com/yt-dlp/yt-dlp/wiki/ejs),
[Deno 2.9.7 release](https://github.com/denoland/deno/releases/tag/v2.9.7).
