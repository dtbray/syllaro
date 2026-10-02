# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add local speaker attribution to an already-aligned WhisperX transcript."""

import argparse
import json
import os
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    token = os.environ.get("HF_TOKEN")
    if not token:
        parser.error("HF_TOKEN is required for local diarization")

    # ML imports remain outside the dependency-free core CLI.
    import torch
    import whisperx
    from whisperx.diarize import DiarizationPipeline

    torch.set_num_threads(args.threads)
    started = time.monotonic()
    pipeline = DiarizationPipeline(token=token, device="cpu")
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
    temporary = args.transcript.with_suffix(".diarized.tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(args.transcript)
    print(
        json.dumps(
            {
                "speaker_count": len(set(turns["speaker"])),
                "turns": len(turns),
                "diarization_seconds": round(time.monotonic() - started, 1),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
