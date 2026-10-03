# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from syllaro import cli as scout


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/v1/chat/completions"
        assert data["model"] == "test-local"
        body = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Summary [0.0s]: SPEAKER_00 discussed a topic."},
                    }
                ]
            }
        ).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class SyllaroTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = {
            "local": {
                "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
                "model": "test-local",
            },
            "diarize": True,
            "chunk_chars": 1000,
            "http_timeout": 5,
            "process_timeout": 5,
            "cpu_threads": 4,
            "whisper_model": "small",
        }

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temp.cleanup()

    def job(self, kind="transcript", status="pending"):
        source = self.root / "input.txt"
        source.write_text("[0.0s] SPEAKER_00: " + "Topic evidence. " * 200)
        job = {
            "id": "test",
            "profile": "local",
            "source": "https://youtu.be/test" if kind == "youtube" else str(source),
            "kind": kind,
            "status": status,
        }
        scout.write_json(self.root / "test.json", job)
        return job

    def test_transcript_pipeline_and_interrupted_recovery(self):
        self.job(status="running")
        scout.work(self.root, self.config)
        result = json.loads((self.root / "test.json").read_text())
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["summary_provider"], "local")
        self.assertIn("SPEAKER_00", (self.root / "test/summary.md").read_text())
        self.assertTrue((self.root / "test/chunk-summaries.md").exists())

    def test_missing_token_marks_failure(self):
        self.job(kind="youtube")
        with patch.dict("os.environ", {}, clear=True):
            out = self.root / "test"
            out.mkdir()
            (out / "audio.json").write_text(
                json.dumps({"segments": [{"start": 0, "end": 2, "text": "Topic"}]})
            )
            scout.work(self.root, self.config)
        result = json.loads((self.root / "test.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertIn("HF_TOKEN", result["error"])

    def test_cached_transcript_avoids_retranscription(self):
        job = self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.json").write_text(
            json.dumps(
                {"segments": [{"start": 0, "end": 2, "text": "Topic", "speaker": "SPEAKER_00"}]}
            )
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(scout.shutil, "which", return_value=None),
            patch.object(scout, "run_process") as run,
        ):
            scout.process(job, self.root, self.config)
            run.assert_not_called()
        self.assertIn("[0.0s–2.0s] SPEAKER_00", (out / "transcript.txt").read_text())

    def test_remote_endpoints_rejected(self):
        for url in [
            "https://api.openai.com/v1",
            "http://example.com/v1",
            "http://user:secret@localhost/v1",
        ]:
            with self.assertRaises(ValueError):
                scout.validate_endpoint(url)

    def test_ingestion_is_independent_and_cleans_media(self):
        self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.wav").write_bytes(b"media")
        (out / "audio.json").write_text(
            json.dumps(
                {
                    "_syllaro_diarized": True,
                    "segments": [
                        {"start": 0, "end": 2, "text": "Evidence", "speaker": "SPEAKER_00"}
                    ],
                }
            )
        )
        config = {k: v for k, v in self.config.items() if k != "local"}
        with patch.object(scout, "chat", side_effect=AssertionError("No inference")):
            scout.work(self.root, config, stage="ingest")
        self.assertEqual(json.loads((self.root / "test.json").read_text())["status"], "transcribed")
        self.assertFalse((out / "audio.wav").exists())
        self.assertTrue((out / "audio.json").exists())
        scout.work(self.root, self.config, stage="summarize")
        self.assertEqual(json.loads((self.root / "test.json").read_text())["status"], "done")

    def test_failed_ingestion_preserves_media(self):
        self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.wav").write_bytes(b"media")
        (out / "audio.json").write_text(json.dumps({"segments": []}))
        with patch.dict("os.environ", {}, clear=True):
            scout.work(self.root, self.config, stage="ingest")
        self.assertEqual(json.loads((self.root / "test.json").read_text())["status"], "failed")
        self.assertTrue((out / "audio.wav").exists())

    def test_cached_transcript_can_gain_speaker_labels(self):
        job = self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.wav").touch()
        raw = {"segments": [{"start": 0, "end": 2, "text": "Topic"}]}
        (out / "audio.json").write_text(json.dumps(raw))

        def fake_diarize(args, log, config):
            self.assertEqual(Path(args[1]).name, "diarize.py")
            self.assertEqual(args[2:4], [str(out / "audio.wav"), str(out / "audio.json")])
            raw["segments"][0]["speaker"] = "SPEAKER_00"
            raw["_syllaro_diarized"] = True
            (out / "audio.json").write_text(json.dumps(raw))

        with (
            patch.dict("os.environ", {"HF_TOKEN": "test"}),
            patch.object(scout, "run_process", side_effect=fake_diarize) as run,
        ):
            scout.process(job, self.root, self.config)
            self.assertEqual(run.call_count, 1)
        self.assertIn("SPEAKER_00", (out / "transcript.txt").read_text())

    def test_tokenless_transcription_uses_silero(self):
        job = self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.wav").touch()
        config = {**self.config, "diarize": False}

        def fake_transcribe(args, log, config):
            self.assertEqual(args[1:4], ["-I", "-m", "whisperx"])
            self.assertEqual(args[args.index("--vad_method") + 1], "silero")
            self.assertNotIn("--hf_token", args)
            (out / "audio.json").write_text(
                json.dumps({"segments": [{"start": 0, "end": 2, "text": "Topic"}]})
            )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(scout.shutil, "which", return_value="/fake"),
            patch.object(scout, "run_process", side_effect=fake_transcribe) as run,
        ):
            scout.process(job, self.root, config)
            self.assertEqual(run.call_count, 1)

    def test_exclusive_worker_lock(self):
        with (self.root / "worker.lock").open("w") as lock:
            scout.fcntl.flock(lock, scout.fcntl.LOCK_EX | scout.fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "already running"):
                scout.work(self.root, self.config)

    def test_corrupt_queue_does_not_block_ready_transcript(self):
        self.job(status="transcribed")
        out = self.root / "test"
        out.mkdir()
        (out / "transcript.txt").write_text("[0.0s] SPEAKER_00: Evidence")
        (self.root / "000-corrupt.json").write_text("{")
        (self.root / "001-invalid.json").write_text(json.dumps({"id": "001-invalid"}))
        scout.work(self.root, self.config)
        self.assertEqual(json.loads((self.root / "test.json").read_text())["status"], "done")
        self.assertIsNone(scout.read_job(self.root / "000-corrupt.json"))
        self.assertIsNone(scout.read_job(self.root / "001-invalid.json"))

    def test_partial_labels_require_diarization_and_missing_audio_fails_early(self):
        job = self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.json").write_text(
            json.dumps(
                {
                    "segments": [
                        {"start": 0, "end": 1, "text": "Known", "speaker": "SPEAKER_00"},
                        {"start": 1, "end": 2, "text": "Unknown"},
                    ]
                }
            )
        )
        with (
            patch.dict("os.environ", {"HF_TOKEN": "test"}),
            patch.object(scout, "run_process") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "audio.wav is missing"):
                scout.ingest(job, self.root, self.config)
            run.assert_not_called()

    @unittest.skipIf(
        scout.os.geteuid() == 0, "Read-only permission enforcement requires non-root uid"
    )
    def test_readonly_cached_transcript_still_allows_safe_media_cleanup(self):
        job = self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.wav").write_bytes(b"media")
        artifact = out / "audio.json"
        artifact.write_text(
            json.dumps(
                {
                    "_syllaro_diarized": True,
                    "segments": [
                        {"start": 0, "end": 1, "text": "Evidence", "speaker": "SPEAKER_00"}
                    ],
                }
            )
        )
        artifact.chmod(0o400)
        scout.ingest(job, self.root, self.config)
        self.assertFalse((out / "audio.wav").exists())
        self.assertEqual(artifact.stat().st_mode & 0o777, 0o400)

    def test_directory_sync_error_identifies_path_and_errno(self):
        original_open = scout.os.open

        def denied(path, *args, **kwargs):
            if path == self.root:
                raise PermissionError(13, "Permission denied")
            return original_open(path, *args, **kwargs)

        with patch.object(scout.os, "open", side_effect=denied):
            with self.assertRaises(RuntimeError) as raised:
                scout.sync_directory(self.root)
        self.assertIn(str(self.root), str(raised.exception))
        self.assertIn("Errno 13", str(raised.exception))

    def test_directory_sync_preserves_fsync_failure_when_close_also_fails(self):
        original_close = scout.os.close

        def failed_close(descriptor):
            original_close(descriptor)
            raise OSError(9, "Bad file descriptor")

        with (
            patch.object(scout.os, "fsync", side_effect=OSError(5, "Input/output error")),
            patch.object(scout.os, "close", side_effect=failed_close),
        ):
            with self.assertRaises(RuntimeError) as raised:
                scout.sync_directory(self.root)
        self.assertIn(str(self.root), str(raised.exception))
        self.assertIn("Errno 5", str(raised.exception))

    def test_directory_close_failure_identifies_operation_path_and_errno(self):
        original_close = scout.os.close

        def failed_close(descriptor):
            original_close(descriptor)
            raise OSError(9, "Bad file descriptor")

        with patch.object(scout.os, "close", side_effect=failed_close):
            with self.assertRaises(RuntimeError) as raised:
                scout.sync_directory(self.root)
        self.assertIn(f"Cannot close directory {self.root}", str(raised.exception))
        self.assertIn("Errno 9", str(raised.exception))

    def test_artifact_sync_failure_retains_media_and_identifies_path(self):
        job = self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.wav").write_bytes(b"media")
        (out / "transcript.txt").write_text("Evidence")
        (out / "audio.json").write_text(
            json.dumps(
                {
                    "_syllaro_diarized": True,
                    "segments": [
                        {"start": 0, "end": 1, "text": "Evidence", "speaker": "SPEAKER_00"}
                    ],
                }
            )
        )
        with patch.object(scout.os, "fsync", side_effect=OSError(5, "Input/output error")):
            with self.assertRaises(RuntimeError) as raised:
                scout.ingest(job, self.root, self.config)
        self.assertIn(str(out / "transcript.txt"), str(raised.exception))
        self.assertIn("Errno 5", str(raised.exception))
        self.assertTrue((out / "audio.wav").exists())

    def test_gpu_only_diarization_adds_wheel_libraries(self):
        packages = self.root / "packages"
        library = packages / "nvidia/cufft/lib"
        library.mkdir(parents=True)
        with (
            patch.object(scout.sysconfig, "get_path", return_value=str(packages)),
            patch.dict("os.environ", {"LD_LIBRARY_PATH": "/existing"}),
            patch.object(scout.subprocess, "run") as run,
        ):
            scout.run_process(
                ["test"],
                self.root / "process.log",
                {**self.config, "device": "cpu", "diarization_device": "cuda"},
            )
            self.assertEqual(run.call_args.kwargs["env"]["LD_LIBRARY_PATH"], f"{library}:/existing")

    def test_cuda_transcription_routes_legacy_precision(self):
        job = self.job(kind="youtube")
        out = self.root / "test"
        out.mkdir()
        (out / "audio.wav").touch()
        config = {**self.config, "device": "cuda", "diarize": False}

        def fake_transcribe(args, log, config):
            self.assertEqual(args[args.index("--device") + 1], "cuda")
            self.assertEqual(args[args.index("--compute_type") + 1], "int8")
            (out / "audio.json").write_text(
                json.dumps({"segments": [{"start": 0, "end": 2, "text": "Topic"}]})
            )

        with (
            patch.object(scout.shutil, "which", return_value="/fake"),
            patch.object(scout, "run_process", side_effect=fake_transcribe),
        ):
            scout.process(job, self.root, config)

    def test_cuda_subprocess_finds_wheel_libraries(self):
        packages = self.root / "packages"
        library = packages / "nvidia/cublas/lib"
        library.mkdir(parents=True)
        with (
            patch.object(scout.sysconfig, "get_path", return_value=str(packages)),
            patch.dict("os.environ", {"LD_LIBRARY_PATH": "/existing"}),
            patch.object(scout.subprocess, "run") as run,
        ):
            scout.run_process(
                ["whisperx"], self.root / "process.log", {**self.config, "device": "cuda"}
            )
            self.assertEqual(run.call_args.kwargs["env"]["LD_LIBRARY_PATH"], f"{library}:/existing")


if __name__ == "__main__":
    unittest.main()
