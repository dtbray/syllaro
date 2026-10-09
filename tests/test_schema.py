# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import unittest
from pathlib import Path

from syllaro.schema import validate_config, validate_job


class SchemaTest(unittest.TestCase):
    def config(self):
        return json.loads((Path(__file__).parents[1] / "examples/config.json").read_text())

    def job(self):
        return dict(
            id="test-1",
            source="https://youtu.be/example",
            kind="youtube",
            profile="workstation",
            status="transcribed",
        )

    def test_ingestion_config_without_profiles(self):
        config = self.config()
        del config["local"], config["workstation"]
        self.assertEqual(validate_config(config), config)

    def test_invalid_config_rejected(self):
        for field, value in (
            ("cpu_threads", True),
            ("chunk_chars", 999),
            ("http_timeout", float("nan")),
            ("diarize", "false"),
            ("device", "magic"),
            ("diarization_batch_size", 0),
            ("diarization_model_path", "relative/model"),
            ("diarization_model_path", ""),
            ("transcription_backend", "automatic"),
            ("alignment_device", "cuda"),
        ):
            with self.subTest(field=field):
                config = self.config()
                config[field] = value
                with self.assertRaises(ValueError):
                    validate_config(config)

    def test_transformers_requires_local_model_float_compute_and_language(self):
        config = {
            **self.config(),
            "transcription_backend": "transformers",
            "whisper_model": "/models/whisper-small",
            "compute_type": "float16",
            "language": "en",
            "alignment_device": "cpu",
        }
        self.assertEqual(validate_config(config), config)
        for field, value in (
            ("whisper_model", "small"),
            ("compute_type", "int8"),
            ("language", ""),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_config({**config, field: value})

    def test_job_identity_and_source_boundaries(self):
        for field, value in (
            ("id", "../escape"),
            ("id", "."),
            ("status", "ready-ish"),
            ("profile", "paid"),
            ("source", "https://example.com/video"),
        ):
            with self.subTest(field=field):
                job = self.job()
                job[field] = value
                with self.assertRaises(ValueError):
                    validate_job(job)
        with self.assertRaises(ValueError):
            validate_job(self.job(), "other-file")

    def test_legacy_job_does_not_require_new_fields(self):
        self.assertEqual(validate_job(self.job(), "test-1"), self.job())
        job = self.job()
        job["summary_provider"] = "assistant"
        self.assertEqual(validate_job(job)["summary_provider"], "assistant")

    def test_config_typos_and_huge_numbers_rejected(self):
        for extra in (
            {"devcie": "cuda"},
            {"cpu_threads": 10**400},
            {"local": {"base_url": "https://example.com/v1", "model": "test"}},
        ):
            config = self.config()
            config.update(extra)
            with self.assertRaises(ValueError):
                validate_config(config)
