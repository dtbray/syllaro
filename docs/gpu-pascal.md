# GTX 1050 Ti / Pascal GPU setup

Validated on a headless Debian 13 host with a GTX 1050 Ti Max-Q, 4 GiB VRAM,
compute capability 6.1. Keep the CPU environment for fallback and comparison.

## Driver and Python environment

The tested host uses Debian's proprietary NVIDIA 550.163.01 driver, matching
kernel headers and DKMS. Pascal requires the proprietary kernel module;
[NVIDIA's open kernel modules support Turing and later](https://github.com/NVIDIA/open-gpu-kernel-modules).
Enable Debian `contrib` and
`non-free` components if the driver has no APT candidate. Include `libcuda1`
explicitly when installing without recommendations: NVML/`nvidia-smi` working
does not by itself establish that CUDA's user-space driver is installed.

The driver was switched live from unused Nouveau on this headless host, after
checking that no process held its DRM devices. No reboot was performed.
Do not unload an in-use display driver. Confirm `nvidia-smi` before proceeding.

```bash
python3 -m venv .venv-gpu
. .venv-gpu/bin/activate
pip install -r requirements-pascal.txt
pip install -e '.[transcription,dev]' 'ctranslate2==4.8.2'
cp examples/config.pascal.json ~/.config/syllaro/config.json
```

The pinned stack is PyTorch 2.8.0 with CUDA 12.6 and cuDNN 9.10.2.21.
PyTorch's [CUDA 12.6 build retains SM 6.x-compatible kernels](https://github.com/pytorch/pytorch/blob/v2.8.0/.ci/manywheel/build_cuda.sh),
and [cuDNN 9.10.2 supports Pascal](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/support-matrix.html).
Newer builds can drop this architecture, so do not substitute the latest CUDA
or cuDNN packages blindly. The full CUDA compiler toolkit is not required.

WhisperX's CLI accepts `int8`, not `int8_float32`. CTranslate2 reports
`float32`, `int8`, and `int8_float32` as supported on this card; use the CLI's
`int8` alias. FP16 is not the appropriate default for this GPU.

Syllaro adds the active virtualenv's cuBLAS/cuDNN/runtime library directories
to CUDA subprocesses' library search path. Activate the GPU environment so
the worker finds its matching `whisperx` executable.

## Configuration

The Pascal example sets `device: cuda`, `compute_type: int8`,
`diarization_device: cuda`, and `diarization_batch_size: 4`. Both segmentation
and speaker embedding batches are limited for the 4 GiB VRAM budget. Audio
transcription/alignment and diarization run in separate processes, releasing
GPU memory between stages. The summary model endpoint is configured separately;
these options do not move summaries onto the GPU.

Set `HF_TOKEN` in the worker environment for local diarization, as with CPU
processing. Keep its value outside the repository and command arguments.
CUDA errors remain errors; there is no silent CPU or paid-provider fallback.
Install the `linux-headers-amd64` metapackage as well as the headers matching
the running kernel, so subsequent kernel updates have headers for DKMS.

To return to CPU processing, activate `.venv` and restore the CPU example
config. No driver removal is necessary.

## Validation

CUDA matrix operations and a cuDNN convolution passed; the GPU convolution
matched its CPU result. A 60-second clip from the first test video completed
GPU transcription, alignment, and speaker attribution: 15.8s for
transcription/alignment and 17.0s for diarization, including process startup.
It produced 18 segments, 211 aligned words, and one generic speaker label.

The full 17:51 test video then completed its GPU audio pipeline in 204.33s
(3m24s), compared with approximately 24 minutes on CPU:

| Stage | CPU first run | GPU run |
| --- | --- | --- |
| Transcription and alignment | Approximately 7m25s | 101.68s |
| Diarization | Approximately 16m35s | 102.65s |
| Total audio processing | Approximately 24m | 3m24s |

Both GPU stage durations include process startup. The GPU run specified English
instead of repeating language detection, reused downloaded audio and model
weights, and used smaller diarization batches. This is roughly 7× faster for
this sample, not a controlled throughput guarantee. Downloads, setup, and
summarization are excluded from this comparison.

The GPU transcript contained 261 segments and 3,452 aligned words, with three
speaker labels and no missing word labels. Its text and segmentation differ
slightly from the CPU run; it is not a bit-for-bit reproduction or an accuracy
benchmark. The original assistant-written briefing was preserved.

During the run, alignment was observed using approximately 1.1 GiB VRAM.
GPU temperature was observed at 92°C under load, then 76°C shortly after
completion; the driver reported a 97°C slowdown threshold. No GPU errors or
out-of-memory failures occurred.

These are native host measurements, not container validation. Docker GPU
runtime/toolkit setup is a separate deployment step.
