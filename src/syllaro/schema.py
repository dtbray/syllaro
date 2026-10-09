# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency-free types and validation for persisted configuration and jobs."""

import math
import re
from pathlib import Path
from typing import Literal, TypedDict, cast
from urllib.parse import urlparse

ProfileName = Literal["local", "workstation"]
Stage = Literal["all", "ingest", "summarize"]
Status = Literal["pending", "running", "transcribed", "summarizing", "done", "failed"]


class Profile(TypedDict):
    base_url: str
    model: str


class ConfigRequired(TypedDict):
    data_dir: str
    whisper_model: str
    cpu_threads: int
    diarize: bool
    chunk_chars: int
    http_timeout: float
    process_timeout: float


class Config(ConfigRequired, total=False):
    local: Profile
    workstation: Profile
    device: Literal["cpu", "cuda"]
    compute_type: str
    diarization_device: Literal["cpu", "cuda"]
    diarization_batch_size: int
    diarization_model_path: str
    batch_size: int
    language: str


class JobRequired(TypedDict):
    id: str
    source: str
    kind: Literal["transcript", "youtube"]
    profile: ProfileName
    status: Status


class Job(JobRequired, total=False):
    created: float
    started: float
    finished: float
    stage: Stage
    error: str | None
    output: str
    summary_provider: Literal["local", "workstation", "assistant"]


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")


def number(value, field, minimum=0, integer=False):
    try:
        finite = math.isfinite(value) if isinstance(value, (int, float)) else False
    except OverflowError:
        finite = False
    if (
        isinstance(value, bool)
        or not isinstance(value, int if integer else (int, float))
        or not finite
        or value <= minimum
    ):
        raise ValueError(f"{field} must be {'an integer' if integer else 'a number'} > {minimum}")


def validate_endpoint(url):
    # Remote workstation inference is deliberately reached through a local tunnel.
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            "Inference endpoints must be HTTP loopback URLs; use an SSH tunnel for the workstation"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Inference endpoint must not contain credentials, queries, or fragments")


def validate_config(value: object) -> Config:
    if not isinstance(value, dict):
        raise ValueError("Configuration must be a JSON object")
    unknown = set(value) - set(Config.__annotations__)
    if unknown:
        raise ValueError("Unknown configuration keys: " + ", ".join(sorted(unknown)))
    for field in ("data_dir", "whisper_model"):
        text(value.get(field), field)
    for field in ("cpu_threads", "chunk_chars"):
        number(value.get(field), field, 999 if field == "chunk_chars" else 0, integer=True)
    for field in ("http_timeout", "process_timeout"):
        number(value.get(field), field)
    if not isinstance(value.get("diarize"), bool):
        raise ValueError("diarize must be a boolean")
    for field in ("device", "diarization_device"):
        if field in value and value[field] not in ("cpu", "cuda"):
            raise ValueError(f"{field} must be cpu or cuda")
    if "compute_type" in value and value["compute_type"] not in (
        "int8",
        "int8_float16",
        "float16",
        "float32",
    ):
        raise ValueError("Unsupported WhisperX compute_type")
    for field in ("batch_size", "diarization_batch_size"):
        if field in value:
            number(value[field], field, integer=True)
    if "language" in value:
        text(value["language"], "language")
    if "diarization_model_path" in value:
        text(value["diarization_model_path"], "diarization_model_path")
        if not Path(value["diarization_model_path"]).is_absolute():
            raise ValueError("diarization_model_path must be an absolute local directory path")
    for name in ("local", "workstation"):
        if name not in value:
            continue  # Ingestion does not require inference profiles.
        profile = value[name]
        if not isinstance(profile, dict):
            raise ValueError(f"{name} must be an inference profile object")
        for field in ("base_url", "model"):
            text(profile.get(field), f"{name}.{field}")
        validate_endpoint(profile["base_url"])
    return cast(Config, value)


def validate_job(value: object, expected_id: str | None = None) -> Job:
    if not isinstance(value, dict):
        raise ValueError("Job must be a JSON object")
    missing = set(JobRequired.__annotations__) - set(value)
    if missing:
        raise ValueError("Missing job fields: " + ", ".join(sorted(missing)))
    ident = value.get("id")
    if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", ident):
        raise ValueError("Job id must be a safe single path component")
    if expected_id is not None and ident != expected_id:
        raise ValueError("Job id does not match its queue filename")
    text(value.get("source"), "source")
    choices = {
        "kind": ("youtube", "transcript"),
        "profile": ("local", "workstation"),
        "status": ("pending", "running", "transcribed", "summarizing", "done", "failed"),
        "stage": ("all", "ingest", "summarize"),
        "summary_provider": ("local", "workstation", "assistant"),
    }
    for field, allowed in choices.items():
        if field in ("stage", "summary_provider") and field not in value:
            continue
        if value.get(field) not in allowed:
            raise ValueError(f"Invalid job {field}")
    if value["kind"] == "youtube":
        parsed = urlparse(value["source"])
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname
            not in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Job source must be a YouTube URL")
    for field in ("created", "started", "finished"):
        if field in value:
            number(value[field], field)
    if "error" in value and value["error"] is not None and not isinstance(value["error"], str):
        raise ValueError("Job error must be a string or null")
    if "output" in value:
        text(value["output"], "output")
    return cast(Job, value)
