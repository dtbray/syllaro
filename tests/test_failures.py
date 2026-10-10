# SPDX-License-Identifier: AGPL-3.0-or-later
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syllaro.cli import run_process
from syllaro.failures import log_failure


class FailureTests(unittest.TestCase):
    def test_known_causes_and_only_current_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "process.log"
            path.write_text("RuntimeError: Transcription chunk is missing a timestamp\n")
            self.assertIn("missing timestamps", log_failure(path, "transcribe", 1))
            offset = path.stat().st_size
            with path.open("a") as stream:
                stream.write("unrelated private URL/token\n")
            message = log_failure(path, "transcribe", 2, offset)
            self.assertEqual(message, "transcribe failed (exit 2); see process.log for details")
            self.assertNotIn("private", message)
            path.write_text("ERROR HTTP Error 403: Forbidden")
            self.assertIn("HTTP 403", log_failure(path, "yt-dlp", 1))

    def test_subprocess_error_does_not_expose_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "process.log"
            with patch(
                "subprocess.run", side_effect=subprocess.CalledProcessError(1, ["tool", "secret"])
            ):
                with self.assertRaisesRegex(RuntimeError, r"tool failed \(exit 1\)") as error:
                    run_process(["tool", "secret"], path, {"cpu_threads": 1, "process_timeout": 5})
            self.assertNotIn("secret", str(error.exception))
