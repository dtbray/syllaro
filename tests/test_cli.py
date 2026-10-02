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
            "source": str(source),
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
        self.assertIn("SPEAKER_00", (self.root / "test/summary.md").read_text())
        self.assertTrue((self.root / "test/chunk-summaries.md").exists())

    def test_missing_token_marks_failure(self):
        self.job(kind="youtube")
        with patch.dict("os.environ", {}, clear=True):
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

    def test_exclusive_worker_lock(self):
        with (self.root / "worker.lock").open("w") as lock:
            scout.fcntl.flock(lock, scout.fcntl.LOCK_EX | scout.fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "already running"):
                scout.work(self.root, self.config)


if __name__ == "__main__":
    unittest.main()
