# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syllaro import cli
from syllaro.schema import validate_job


class AudioTests(unittest.TestCase):
    def test_local_audio_paths_are_required(self):
        job = {
            "id": "speech",
            "kind": "audio",
            "source": "/tmp/audio.wav",
            "profile": "local",
            "status": "pending",
        }
        validate_job(job)
        for source in ("https://example.org/audio.mp3", "relative.wav"):
            with self.assertRaises(ValueError):
                validate_job(dict(job, source=source))

    def test_cached_audio_result_finalizes_without_ml_or_inference(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            out = root / "speech"
            out.mkdir()
            audio = out / "audio.wav"
            audio.write_bytes(b"cached audio")
            job = {
                "id": "speech",
                "kind": "audio",
                "source": str(audio),
                "profile": "local",
                "status": "pending",
            }
            cli.write_json(root / "speech.json", job)
            cli.write_json(
                out / "audio.json",
                {
                    "_syllaro_diarized": True,
                    "segments": [
                        {"start": 0, "end": 2, "text": "Check backups", "speaker": "SPEAKER_00"}
                    ],
                },
            )
            with (
                patch.object(cli, "run_process", side_effect=AssertionError("Cached results only")),
                patch.object(cli, "chat", side_effect=AssertionError("No inference")),
            ):
                cli.work(root, {"diarize": True}, stage="ingest")
            self.assertEqual(
                json.loads((root / "speech.json").read_text())["status"], "transcribed"
            )
            self.assertFalse(audio.exists())
            self.assertIn("SPEAKER_00", (out / "transcript.txt").read_text())

    def test_local_import_converts_without_youtube_download_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "original.mp3"
            source.write_bytes(b"source media")
            job = {
                "id": "speech",
                "kind": "audio",
                "source": str(source),
                "profile": "local",
                "status": "pending",
            }

            def run(args, log, config):
                self.assertNotEqual(args[0], "yt-dlp")
                if args[0] == "ffmpeg":
                    self.assertIn(str(source), args)
                    (root / "speech/audio.wav").write_bytes(b"converted media")
                else:
                    cli.write_json(
                        root / "speech/audio.json",
                        {
                            "_syllaro_diarized": True,
                            "segments": [
                                {"start": 0, "end": 2, "text": "Evidence", "speaker": "SPEAKER_00"}
                            ],
                        },
                    )

            with (
                patch.object(cli, "run_process", side_effect=run),
                patch.object(cli.shutil, "which", return_value="available"),
            ):
                cli.ingest(job, root, {"diarize": True, "whisper_model": "small", "cpu_threads": 1})
            self.assertEqual(source.read_bytes(), b"source media")
            self.assertFalse((root / "speech/audio.wav").exists())

    def test_failed_audio_job_preserves_media(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            out = root / "speech"
            out.mkdir()
            audio = out / "audio.wav"
            audio.write_bytes(b"cached audio")
            cli.write_json(
                root / "speech.json",
                {
                    "id": "speech",
                    "kind": "audio",
                    "source": str(audio),
                    "profile": "local",
                    "status": "pending",
                },
            )
            cli.write_json(out / "audio.json", {"segments": []})
            cli.work(root, {"diarize": True}, stage="ingest")
            self.assertTrue(audio.exists())
            self.assertEqual(json.loads((root / "speech.json").read_text())["status"], "failed")
