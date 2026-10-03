# GPU environment snapshot

`pascal-py313.lock.txt` pins the third-party packages in the working Linux
x86_64, CPython 3.13.5 GPU environment. It preserves Torch 2.8 CUDA 12.6 and
cuDNN 9.10.2.21 for Pascal. It excludes the editable Syllaro checkout and
unrelated development/build tools. The captured environment passes `pip check`.

Use a fresh environment with Python 3.13:

```bash
python3.13 -m venv .venv-gpu
.venv-gpu/bin/python -m pip install -r requirements/pascal-py313.lock.txt
.venv-gpu/bin/python -m pip install --no-deps --force-reinstall --index-url https://pypi.org/simple 'torchcodec===0.7.0'
.venv-gpu/bin/python -m pip install --no-deps -e .
.venv-gpu/bin/python -m pip check
```

This is a version-pinned snapshot, not a hash-locked wheel archive. A clean
installation of the pinned dependencies passes `pip check` in the Pascal
container. The explicit TorchCodec step avoids the extra PyTorch index choosing
a CUDA local-version variant instead of the host's plain wheel. Other Python versions, operating
systems, and GPU generations need their own validated lock. The NVIDIA driver,
FFmpeg, model weights, Hugging Face model access, and local CUDA library search
paths remain external requirements; see `../docs/gpu-pascal.md`.

When updating, use a separate candidate environment, run `pip check`, test
transcription and diarization on real media, and regenerate the pins only after
those checks pass. Do not upgrade the active ingestion environment in place.
