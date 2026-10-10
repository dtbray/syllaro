# GPU environment snapshot

`pascal-py313.lock.txt` records versions; `pascal-py313.hashes.txt` pins the third-party packages in the working Linux
x86_64, CPython 3.13.5 GPU environment. It preserves Torch 2.8 CUDA 12.6 and
cuDNN 9.10.2.21 for Pascal. It excludes the editable Syllaro checkout and
unrelated development/build tools. The captured environment passes `pip check`.

Use a fresh environment with Python 3.13:

```bash
python3.13 -m venv .venv-gpu
.venv-gpu/bin/python -m pip install --require-hashes -r requirements/pascal-py313.hashes.txt
.venv-gpu/bin/python -m pip install --no-deps -e .
.venv-gpu/bin/python -m pip check
```

Hashes are recorded from PyPI release metadata and the official PyTorch CUDA
12.6 indexes. Only CPython 3.13 Linux x86_64 CUDA wheels are allowed for Torch,
torchaudio, and torchvision. Other packages permit published release artifacts;
some dependencies ship source distributions. This is not a vendored wheel
archive. A clean
installation of the pinned dependencies passes `pip check` in the Pascal
container. The exact plain TorchCodec requirement avoids the extra PyTorch index choosing
a CUDA local-version variant instead of the host's plain wheel. Other Python versions, operating
systems, and GPU generations need their own validated lock. The NVIDIA driver,
FFmpeg, model weights, Hugging Face model access, and local CUDA library search
paths remain external requirements; see `../docs/gpu-pascal.md`.

When updating, use a separate candidate environment, run `pip check`, test
transcription and diarization on real media, and regenerate the pins only after
those checks pass. Do not upgrade the active ingestion environment in place.

## Isolated YouTube downloader

`download.in` and its hashed `download.lock.txt` select yt-dlp's default extras and
EJS challenge solver without upgrading an active ML virtualenv. Install the lock
in a separate downloader environment and expose its executable plus a supported
Deno runtime on the worker PATH. See [recovery validation](../docs/testing/2026-10-09-pipeline-recovery.md).
Regenerate with `uv pip compile --universal --generate-hashes requirements/download.in
--output-file requirements/download.lock.txt` and review all changes.
