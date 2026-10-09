# AMD/ROCm workstation candidate

The Pop!_OS workstation uses an RX 9060 XT (gfx1200, 15.92 GiB VRAM), Ryzen
5 7500X3D, 32 GB RAM, and Python 3.12.3. Its opt-in candidate environment is
`/home/thomasbray/.local/share/syllaro-rocm/candidate-20261009`; source
`/home/thomasbray/.local/share/syllaro-rocm/activate-candidate.sh` to use it.

ROCm 7.2.1 user-space packages and Ubuntu FFmpeg shared libraries are extracted
into that user-owned directory. No system driver change or sudo is required on
this already-working amdgpu host. PyTorch's and CTranslate2's `cuda` device
names select HIP on these AMD builds. Do not use the ordinary PyPI CTranslate2
wheel; the candidate uses the official 4.8.2 HIP release archive.

WhisperX 3.8.6, faster-whisper 1.2.1, CTranslate2 4.8.2 HIP, pyannote.audio 4.0.7,
and torch/torchaudio 2.8.0 ROCm 7.2.1 passed the public JFK fixture. Both the
full CLI and GPU transcription/alignment/diarization wrapper were exercised.
The machine configuration, package hashes, observed Python dependency snapshot,
activation script, and benchmark evidence are recorded in the Homelab repository
under `ops/hardware/pop-os/`. This is candidate evidence, not a production claim.

Extended validation rejected CTranslate2 HIP on this host: long float16 and
float32 runs failed with illegal GPU access/instructions, and int8 emitted
degenerate repeated text despite a successful exit. Keep CTranslate2 HIP ASR out
of production on this host. PyTorch/ROCm ASR
is an explicit backend, not an automatic fallback.

## Validated longer route

Select `transcription_backend: "transformers"` explicitly to use PyTorch for
ASR, then WhisperX for alignment and the existing separate diarization helper.
The ASR model must be an absolute local Transformers model directory; it is
loaded with `local_files_only=True`. Set `compute_type` to float16 or float32
and provide `language`. The default backend remains WhisperX. `alignment_device`
is supported only with Transformers and defaults to CPU, releasing the ASR GPU
model before loading alignment. No remote inference or automatic fallback is added.

The 1049.35-second public AMI ES2004a meeting completed with small-model GPU ASR
in 111.845 seconds, CPU alignment in 73.412 seconds, and GPU diarization in
174.391 seconds: 362.26 seconds including process overhead. It produced 2,218
aligned words and five generic speaker clusters. No WER/DER evaluation was
performed; the cluster count does not establish accurate speaker separation.
Peak sampled CPU temperature was 71.75°C, GPU edge 66°C and hotspot 88°C.
Global VRAM peaked at 14.67 GB with the existing Qwen server still loaded.

The Transformers pipeline uses 30-second overlapping chunks, which upstream
marks experimental for sequence-to-sequence models. Retain that quality caveat
and review timestamps, silence hallucinations, and speaker attribution. An
application error, missing timestamp, or empty output retains audio for retry.

A workstation configuration fragment for this route is:

```json
{
  "transcription_backend": "transformers",
  "whisper_model": "/home/thomasbray/.local/share/syllaro-rocm/hf-cache/hub/models--openai--whisper-small/snapshots/973afd24965f72e36ca33b3055d56a652f456b4d",
  "device": "cuda",
  "compute_type": "float16",
  "batch_size": 1,
  "cpu_threads": 4,
  "language": "en",
  "alignment_device": "cpu",
  "diarization_device": "cuda",
  "diarization_batch_size": 1,
  "diarization_model_path": "/home/thomasbray/.local/share/syllaro-rocm/models/community-1"
}
```

This is a fragment for a complete config with an isolated data directory. The
public model revision is pinned above. The queue and completed laptop jobs have
not been migrated.

For local diarization without moving credentials, configure:

```json
{
  "diarization_device": "cuda",
  "diarization_batch_size": 1,
  "diarization_model_path": "/home/thomasbray/.local/share/syllaro-rocm/models/community-1"
}
```

Merge these fields into a complete configuration with an isolated `data_dir`;
this fragment is not a standalone config. Existing configs continue to use
HF_TOKEN and the default Hub model when the new field is omitted. Local model
directories must exist; no automatic remote model fallback is added.

Do not copy live laptop queue files or let two workers claim the same job. Keep
benchmark media and jobs separate. The workstation's existing local LLM service
occupies most GPU memory; long-media validation must account for that contention.
The initial 17-minute float16 meeting test failed with a HIP illegal shader
instruction, while a three-minute excerpt passed transcription and alignment.
Direct faster-whisper filename decoding also has a PyAV incompatibility; the
tested WhisperX FFmpeg-to-array path works. Neither the short fixture nor unit
tests establish speaker accuracy or sustained production readiness.
