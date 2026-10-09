# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit local Transformers ASR with independently placed WhisperX alignment."""

import argparse
import gc
import json
import math
import os
import time
from pathlib import Path


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--alignment-device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--compute-type", choices=["float16", "float32"], required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.threads < 1 or args.batch_size < 1:
        parser.error("threads and batch size must be positive")
    if not args.audio.is_file():
        parser.error("Audio file must exist")
    if not args.model_path.is_absolute() or not args.model_path.is_dir():
        parser.error("model-path must be an existing absolute local directory")
    if not args.language.strip():
        parser.error("language must be explicit")

    # Imports stay in this optional subprocess, never in ordinary CLI startup.
    import torch
    import whisperx
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

    torch.set_num_threads(args.threads)
    started = time.monotonic()
    audio = whisperx.load_audio(str(args.audio))
    dtype = torch.float16 if args.compute_type == "float16" else torch.float32
    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        str(args.model_path), dtype=dtype, attn_implementation="sdpa", local_files_only=True
    )
    generation: dict[str, str | int] = {"num_beams": 5}
    if getattr(model.generation_config, "is_multilingual", True):
        generation.update(language=args.language, task="transcribe")
    elif args.language != "en":
        raise ValueError("English-only ASR model requires language en")
    processor = AutoProcessor.from_pretrained(str(args.model_path), local_files_only=True)
    recognizer = pipeline(
        "automatic-speech-recognition",
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        device=0 if args.device == "cuda" else -1,
        dtype=dtype,
        chunk_length_s=30,
        batch_size=args.batch_size,
    )
    result = recognizer(audio, return_timestamps=True, generate_kwargs=generation)
    segments = []
    for chunk in result["chunks"]:
        begin, end = chunk["timestamp"]
        if begin is None or end is None:
            raise RuntimeError("Transcription chunk is missing a timestamp")
        begin, end = float(begin), float(end)
        if not math.isfinite(begin) or not math.isfinite(end) or begin < 0 or end < begin:
            raise RuntimeError("Transcription chunk has invalid timestamps")
        segments.append({"start": begin, "end": end, "text": chunk["text"]})
    if not segments or not any(s["text"].strip() for s in segments):
        raise RuntimeError("Transcription is empty")
    print(json.dumps({"transcription_seconds": round(time.monotonic() - started, 1)}), flush=True)
    del recognizer, processor, model
    gc.collect()
    if args.device == "cuda":
        torch.cuda.empty_cache()

    started = time.monotonic()
    model, metadata = whisperx.load_align_model(
        language_code=args.language, device=args.alignment_device
    )
    aligned = whisperx.align(segments, model, metadata, audio, args.alignment_device)
    aligned["language"] = args.language
    if not aligned.get("segments") or not aligned.get("word_segments"):
        raise RuntimeError("Alignment produced no timestamped words")
    temporary = args.transcript.with_suffix(".transcribed.tmp")
    temporary.unlink(missing_ok=True)
    temporary.write_text(json.dumps(aligned, indent=2) + "\n")
    temporary.replace(args.transcript)
    print(json.dumps({"alignment_seconds": round(time.monotonic() - started, 1)}), flush=True)


if __name__ == "__main__":
    main()
