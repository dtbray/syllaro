# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from syllaro import diarize


class DiarizeTest(unittest.TestCase):
    def test_local_model_does_not_pass_environment_token(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio, transcript = root / "audio.wav", root / "audio.json"
            audio.touch()
            transcript.write_text(json.dumps({"segments": [{"text": "Evidence"}]}))
            calls = []

            class Pipeline:
                def __init__(self, **kwargs):
                    calls.append(kwargs)
                    self.model = types.SimpleNamespace()

                def __call__(self, filename, progress_callback):
                    return object()

            modules = {
                "torch": types.SimpleNamespace(set_num_threads=lambda n: None),
                "whisperx": types.SimpleNamespace(assign_word_speakers=lambda turns, data: data),
                "whisperx.diarize": types.SimpleNamespace(DiarizationPipeline=Pipeline),
            }
            previous = os.umask(0o022)
            try:
                with (
                    patch.dict(sys.modules, modules),
                    patch.dict(os.environ, {"HF_TOKEN": "must-not-pass"}),
                    patch.object(
                        sys,
                        "argv",
                        ["diarize", str(audio), str(transcript), "--model-path", str(root)],
                    ),
                ):
                    diarize.main()
            finally:
                os.umask(previous)
            self.assertEqual(calls, [{"model_name": str(root), "token": None, "device": "cpu"}])

    def test_wrapper_batches_callback_and_private_atomic_output(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "audio.wav"
            transcript = Path(folder) / "audio.json"
            audio.touch()
            transcript.write_text(json.dumps({"segments": [{"text": "Evidence"}]}))
            model = types.SimpleNamespace()
            calls = []

            class Pipeline:
                def __init__(self, token, device):
                    self.model = model
                    calls.append((token, device))

                def __call__(self, filename, progress_callback):
                    calls.append(filename)
                    progress_callback(50)
                    return object()  # Diagnostics must not assume Annotation/DataFrame internals.

            def assign(turns, data):
                data["segments"][0]["speaker"] = "SPEAKER_00"
                return data

            modules = {
                "torch": types.SimpleNamespace(set_num_threads=lambda n: None),
                "whisperx": types.SimpleNamespace(assign_word_speakers=assign),
                "whisperx.diarize": types.SimpleNamespace(DiarizationPipeline=Pipeline),
            }
            previous = os.umask(0o022)
            try:
                with (
                    patch.dict(sys.modules, modules),
                    patch.dict(os.environ, {"HF_TOKEN": "test"}),
                    patch.object(
                        sys,
                        "argv",
                        [
                            "diarize",
                            str(audio),
                            str(transcript),
                            "--device",
                            "cuda",
                            "--batch-size",
                            "4",
                        ],
                    ),
                ):
                    diarize.main()
            finally:
                os.umask(previous)
            self.assertEqual(model.segmentation_batch_size, 4)
            self.assertEqual(model.embedding_batch_size, 4)
            self.assertEqual(calls, [("test", "cuda"), str(audio)])
            self.assertTrue(json.loads(transcript.read_text())["_syllaro_diarized"])
            self.assertEqual(transcript.stat().st_mode & 0o777, 0o600)
            self.assertFalse(transcript.with_suffix(".diarized.tmp").exists())

    def test_invalid_batch_rejected_before_ml_import(self):
        previous = os.umask(0o022)
        try:
            with patch.object(
                sys, "argv", ["diarize", "missing.wav", "missing.json", "--batch-size", "0"]
            ):
                with self.assertRaises(SystemExit):
                    diarize.main()
        finally:
            os.umask(previous)
