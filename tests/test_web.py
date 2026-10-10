# SPDX-License-Identifier: AGPL-3.0-or-later
import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient

    from syllaro.dashboard.api import create_app
except ImportError:
    TestClient = None

from syllaro.cli import write_json
from syllaro.services import QueueError, read_artifact, retry_job, submit_job


class SharedServiceTests(unittest.TestCase):
    def test_retry_preserves_cached_summary_input_and_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = submit_job(root, "https://youtu.be/example")
            job.update(status="failed", stage="summarize", error="offline")
            write_json(root / f"{job['id']}.json", job)
            with (root / "worker.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(QueueError) as error:
                    retry_job(root, job["id"])
                self.assertEqual(error.exception.status, 423)
                # Enqueue remains available while a worker owns execution.
                submit_job(root, "https://youtu.be/second")
            retried = retry_job(root, job["id"])
            self.assertEqual(retried["status"], "transcribed")
            self.assertIsNone(retried["error"])

    def test_artifact_cannot_escape_via_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = submit_job(root, "https://youtu.be/example")
            (root / job["id"]).symlink_to("/tmp", target_is_directory=True)
            with self.assertRaises(QueueError):
                read_artifact(root, job["id"], "transcript")


@unittest.skipIf(TestClient is None, "Optional web dependencies not installed")
class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app({"main": self.root}))
        self.addCleanup(self.client.close)

    def submit(self):
        response = self.client.post("/api/v1/jobs", json={"source": "https://youtu.be/example"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_submission_is_only_durable_enqueue(self):
        with (
            patch("syllaro.cli.work", side_effect=AssertionError("must not execute")),
            patch("syllaro.cli.process", side_effect=AssertionError("must not process")),
        ):
            job = self.submit()
        self.assertEqual(job["status"], "pending")
        self.assertEqual(
            json.loads((self.root / f"{job['id']}.json").read_text())["status"], "pending"
        )
        listed = self.client.get("/api/v1/jobs").json()
        self.assertEqual(listed["jobs"][0]["id"], job["id"])
        self.assertEqual(listed["invalid_records"], 0)
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)

    def test_invalid_submission_and_foreign_browser(self):
        for source in [
            "/etc/passwd",
            "https://example.com/video",
            "https://user:pass@youtu.be/x",
            "javascript:alert(1)",
        ]:
            self.assertEqual(
                self.client.post("/api/v1/jobs", json={"source": source}).status_code, 400
            )
        self.assertEqual(
            self.client.post(
                "/api/v1/jobs", json={"source": "https://youtu.be/x", "kind": "audio"}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/jobs",
                headers={"Origin": "https://evil.example"},
                json={"source": "https://youtu.be/x"},
            ).status_code,
            403,
        )
        self.assertEqual(list(self.root.glob("*.json")), [])

    def test_details_artifacts_errors_and_missing(self):
        job = self.submit()
        ident = job["id"]
        artifact_dir = self.root / ident
        artifact_dir.mkdir()
        (artifact_dir / "transcript.txt").write_text("[00:12] SPEAKER_00: hello")
        (artifact_dir / "summary.md").write_text("## Briefing\n<script>bad()</script>")
        (artifact_dir / "action-items.md").write_text("- Review evidence")
        path = f"/api/v1/jobs/{ident}"
        self.assertEqual(
            self.client.get(path).json()["artifacts"], ["transcript", "briefing", "action-items"]
        )
        self.assertIn("SPEAKER_00", self.client.get(path + "/transcript").json()["content"])
        self.assertEqual(self.client.get(path + "/briefing").json()["format"], "markdown")
        self.assertEqual(self.client.get(path + "/action-items").status_code, 200)
        for suffix in ["", "/transcript", "/briefing"]:
            self.assertEqual(self.client.get("/api/v1/jobs/missing" + suffix).status_code, 404)
        (artifact_dir / "transcript.txt").unlink()
        self.assertEqual(self.client.get(path + "/transcript").status_code, 404)
        persisted = json.loads((self.root / f"{ident}.json").read_text())
        persisted.update(status="failed", error="Download failed")
        write_json(self.root / f"{ident}.json", persisted)
        self.assertEqual(self.client.get(path).json()["error"], "Download failed")
        self.assertEqual(self.client.post(path + "/retry").json()["status"], "pending")
        self.assertEqual(self.client.post(path + "/retry").status_code, 409)

    def test_busy_retry_and_invalid_records(self):
        job = self.submit()
        with (self.root / "worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.client.post(f"/api/v1/jobs/{job['id']}/retry").status_code, 423)
            self.submit()
        (self.root / "broken.json").write_text("{}")
        self.assertEqual(self.client.get("/api/v1/jobs").json()["invalid_records"], 1)
        self.assertEqual(self.client.get("/api/v1/jobs/broken").status_code, 500)
        self.assertEqual(self.client.get("/api/v1/jobs?queue=unknown").status_code, 404)

    def test_explicit_lan_host_preserves_origin_checks(self):
        with TestClient(
            create_app({"main": self.root}, host="192.168.1.157"),
            base_url="http://192.168.1.157:8765",
        ) as client:
            self.assertEqual(client.get("/api/v1/jobs").status_code, 200)
            response = client.post(
                "/api/v1/jobs",
                headers={"Origin": "http://192.168.1.157:8765"},
                json={"source": "https://youtu.be/example"},
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(
                client.post(
                    "/api/v1/jobs",
                    headers={"Origin": "https://foreign.example"},
                    json={"source": "https://youtu.be/example"},
                ).status_code,
                403,
            )
            self.assertEqual(
                client.get("/api/v1/jobs", headers={"Host": "foreign.example"}).status_code, 400
            )

    def test_storage_failure_is_sanitized(self):
        with patch("syllaro.cli.write_json", side_effect=OSError("private path and token")):
            response = self.client.post("/api/v1/jobs", json={"source": "https://youtu.be/x"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "storage_error")
        self.assertNotIn("private", response.text)

    def test_spa_does_not_swallow_api_or_asset_errors(self):
        frontend = self.root / "frontend"
        frontend.mkdir()
        (frontend / "index.html").write_text("<html>UI</html>")
        with TestClient(create_app({"main": self.root}, frontend)) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/some-route").status_code, 200)
            self.assertEqual(client.get("/api/v1/unknown").status_code, 404)
            self.assertEqual(client.get("/missing.js").status_code, 404)
            self.assertEqual(client.get("/api/v1/jobs/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
