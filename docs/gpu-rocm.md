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

For local diarization without moving credentials, configure:

```json
{
  "device": "cuda",
  "compute_type": "float16",
  "batch_size": 1,
  "cpu_threads": 4,
  "language": "en",
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
