# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit local Transformers ASR with independently placed WhisperX alignment."""

import argparse
import gc
import json
import math
import os
import time
from pathlib import Path


def generated_segments(result, tokenizer):
    """Use native Whisper segment boundaries; never guess missing timestamps."""
    batches = result.get("segments")
    if not isinstance(batches, list) or len(batches) != 1:
        raise RuntimeError("Native transcription did not return one segment batch")
    segments = []
    previous = 0.0
    for segment in batches[0]:
        begin, end = segment.get("start"), segment.get("end")
        if begin is None or end is None:
            raise RuntimeError("Native transcription segment is missing a timestamp")
        begin, end = float(begin), float(end)
        if not math.isfinite(begin) or not math.isfinite(end) or begin < previous or end <= begin:
            raise RuntimeError("Native transcription segment has invalid timestamps")
        text = tokenizer.decode(segment["tokens"], skip_special_tokens=True).strip()
        if text:
            segments.append({"start": begin, "end": end, "text": text})
        previous = begin
    if not segments:
        raise RuntimeError("Transcription is empty")
    return segments


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
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

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
    model.to(args.device)
    inputs = processor(
        audio,
        sampling_rate=16000,
        return_tensors="pt",
        truncation=False,
        padding="longest",
        return_attention_mask=True,
    )
    with torch.inference_mode():
        result = model.generate(
            inputs["input_features"].to(args.device, dtype=dtype),
            attention_mask=inputs["attention_mask"].to(args.device),
            return_timestamps=True,
            return_segments=True,
            condition_on_prev_tokens=False,
            **generation,
        )
    segments = generated_segments(result, processor.tokenizer)
    print(json.dumps({"transcription_seconds": round(time.monotonic() - started, 1)}), flush=True)
    del result, inputs, processor, model
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
