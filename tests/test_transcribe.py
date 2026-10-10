# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from syllaro import transcribe


class TranscribeTest(unittest.TestCase):
    def test_explicit_local_asr_releases_gpu_before_cpu_alignment(self):
        self.run_pipeline(multilingual=True)

    def test_english_only_model_omits_multilingual_generation_options(self):
        self.run_pipeline(multilingual=False)

    def run_pipeline(self, multilingual):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio, transcript = root / "audio.wav", root / "audio.json"
            audio.touch()
            calls = []
            torch = types.SimpleNamespace(
                inference_mode=nullcontext,
                float16="float16",
                float32="float32",
                set_num_threads=Mock(),
                cuda=types.SimpleNamespace(empty_cache=lambda: calls.append("release")),
            )
            model = Mock()
            model.return_value.generation_config.is_multilingual = multilingual
            model.return_value.generate.return_value = {
                "segments": [[{"start": 0, "end": 2, "tokens": [1]}]]
            }
            processor = Mock()
            processor.return_value.return_value = {
                "input_features": Mock(),
                "attention_mask": Mock(),
            }
            processor.return_value.tokenizer.decode.return_value = "Evidence"

            def load_align(**kwargs):
                calls.append(kwargs["device"])
                return object(), {}

            aligned = {
                "segments": [{"start": 0, "end": 2, "text": "Evidence"}],
                "word_segments": [{"start": 0, "end": 2, "word": "Evidence"}],
            }
            modules = {
                "torch": torch,
                "whisperx": types.SimpleNamespace(
                    load_audio=Mock(return_value=object()),
                    load_align_model=load_align,
                    align=Mock(return_value=aligned),
                ),
                "transformers": types.SimpleNamespace(
                    AutoModelForSpeechSeq2Seq=types.SimpleNamespace(from_pretrained=model),
                    AutoProcessor=types.SimpleNamespace(from_pretrained=processor),
                ),
            }
            previous = os.umask(0o022)
            try:
                with (
                    patch.dict(sys.modules, modules),
                    patch.object(
                        sys,
                        "argv",
                        [
                            "transcribe",
                            str(audio),
                            str(transcript),
                            "--model-path",
                            str(root),
                            "--device",
                            "cuda",
                            "--compute-type",
                            "float16",
                            "--language",
                            "en",
                        ],
                    ),
                ):
                    transcribe.main()
            finally:
                os.umask(previous)
            self.assertEqual(calls, ["release", "cpu"])
            self.assertTrue(model.call_args.kwargs["local_files_only"])
            self.assertTrue(processor.call_args.kwargs["local_files_only"])
            expected = {"num_beams": 5}
            if multilingual:
                expected.update(language="en", task="transcribe")
            actual = model.return_value.generate.call_args.kwargs
            self.assertEqual({k: actual[k] for k in expected}, expected)
            self.assertTrue(actual["return_timestamps"])
            self.assertTrue(actual["return_segments"])
            self.assertFalse(processor.return_value.call_args.kwargs["truncation"])
            self.assertEqual(json.loads(transcript.read_text())["language"], "en")
            self.assertEqual(transcript.stat().st_mode & 0o777, 0o600)
            self.assertFalse(transcript.with_suffix(".transcribed.tmp").exists())

    def test_native_segments_reject_missing_reversed_and_nonfinite_timestamps(self):
        tokenizer = Mock()
        tokenizer.decode.return_value = "Evidence"
        for begin, end in ((None, 2), (2, 1), (0, float("nan")), (-1, 2), (0, 0)):
            with self.subTest(begin=begin, end=end), self.assertRaises(RuntimeError):
                transcribe.generated_segments(
                    {"segments": [[{"start": begin, "end": end, "tokens": [1]}]]}, tokenizer
                )
        valid = transcribe.generated_segments(
            {"segments": [[{"start": 30, "end": 32, "tokens": [1]}]]}, tokenizer
        )
        self.assertEqual(valid, [{"start": 30.0, "end": 32.0, "text": "Evidence"}])
