# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add local speaker attribution to an already-aligned WhisperX transcript."""

import argparse
import json
import os
import time
from pathlib import Path


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--model-path", type=Path, help="Explicit local model directory")
    args = parser.parse_args()
    if args.threads < 1 or (args.batch_size is not None and args.batch_size < 1):
        parser.error("threads and batch size must be positive")
    if not args.audio.is_file() or not args.transcript.is_file():
        parser.error("Audio and transcript files must exist")
    token = os.environ.get("HF_TOKEN")
    if args.model_path is not None and (
        not args.model_path.is_absolute() or not args.model_path.is_dir()
    ):
        parser.error("model-path must be an existing absolute local directory")
    if not token and args.model_path is None:
        parser.error("HF_TOKEN is required for local diarization")

    # ML imports remain outside the dependency-free core CLI.
    import torch
    import whisperx
    from whisperx.diarize import DiarizationPipeline

    torch.set_num_threads(args.threads)
    started = time.monotonic()
    if args.model_path is None:
        pipeline = DiarizationPipeline(token=token, device=args.device)
    else:
        pipeline = DiarizationPipeline(
            model_name=str(args.model_path), token=None, device=args.device
        )
    if args.batch_size is not None:
        pipeline.model.segmentation_batch_size = args.batch_size
        pipeline.model.embedding_batch_size = args.batch_size
    last_report = -10

    def progress(percent):
        nonlocal last_report
        milestone = int(percent // 10) * 10
        if milestone > last_report:
            last_report = milestone
            print(json.dumps({"diarization_progress": milestone}), flush=True)

    turns = pipeline(str(args.audio), progress_callback=progress)
    transcript = json.loads(args.transcript.read_text())
    result = whisperx.assign_word_speakers(turns, transcript)
    result["_syllaro_diarized"] = True
    diagnostics = {
        "speaker_count": len({s.get("speaker") for s in result["segments"] if s.get("speaker")}),
        "diarization_seconds": round(time.monotonic() - started, 1),
    }
    temporary = args.transcript.with_suffix(".diarized.tmp")
    temporary.unlink(missing_ok=True)
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(args.transcript)
    print(json.dumps(diagnostics), flush=True)


if __name__ == "__main__":
    main()
