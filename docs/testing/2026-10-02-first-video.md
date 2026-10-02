# First real-video run

Input: [The Ridiculous Engineering Of Chat](https://youtu.be/6DSW1rN-ZV4)
by Enrico Tartarotti, 17 minutes 51 seconds. Tested 2026-10-02.

Result: local download, transcription, alignment, and speaker attribution
completed. At the user's request, the assistant wrote the final briefing from
the resulting transcript. Automatic local summarization completed two chunk
responses before being stopped; a complete automatic summary run is not yet
validated. The job records its final summary provider as `assistant`.

## Setup

- Intel i7-8750H, six cores/twelve threads, 31 GiB RAM.
- CPU-only PyTorch 2.8.0, WhisperX 3.8.6, Whisper small, INT8, batch size one,
  four threads; Silero speech detection and word alignment.
- Local pyannote speaker-diarization-community-1, with a free model-download
  token retrieved from 1Password and kept outside the repository.
- Local Qwen2.5-3B-Instruct Q4_K_M through llama.cpp b11352
  (`4e2713c16`), four CPU threads, 8,192-token context, loopback HTTP only.
- Qwen GGUF SHA256 matched Hugging Face's published LFS hash:
  `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`.

The configured workstation was unavailable, so all audio processing and model
inference took place on the scout host. Model and package downloads are setup
costs; there were no paid inference calls.

## Transcript observations

- 268 aligned segments, 3,500 aligned words; last speech ended at 1,063.05s.
- Three generic speaker labels, with segment counts 246, 20, and 2.
- All aligned words and segments received speaker labels. This is coverage,
  not a claim that every assignment is correct; identities were not resolved.
- Approximately 90% of distinct YouTube-caption word pairs were also present
  in Whisper's transcript after normalizing punctuation and rolling captions.
  Automatic captions are not ground truth; this is not a word-error-rate score.
- One likely recognition error: “chat” became “chess” around 15:42.

## Measured stages

- Transcription: approximately 3m16s, including language detection.
- Alignment: approximately 4m09s, including its first-run model download.
- Speaker attribution: approximately 16m35s, including local model loading.
- First local summary chunk: approximately 3m58s, including 2m49s of prompt
  processing and 1m09s of generation, 382 generated tokens at 5.5 tokens/second.

Speaker embeddings dominated diarization time. A profiler confirmed active
convolution work. The CPU was observed at around 1.9 GHz during sustained load.
These measurements cover one recording on a laptop CPU, not a throughput SLA.

## Changes prompted by the run

Use ungated Silero speech detection for tokenless transcription; split speaker
attribution into a separate process so cached transcripts can gain labels
without repeating transcription; report diarization progress; document
CPU-only PyTorch installation to avoid unnecessary CUDA package downloads.
Record the summary provider in job status so assistant-written results are
distinguishable from local/workstation inference.

Interrupted-job recovery was exercised after alignment, switching the same
cached job from transcript-only processing to speaker attribution.
Raw audio, transcripts, captions, secrets, and generated briefings remain
local and are not committed here.
