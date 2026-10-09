# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small shared operations over the authoritative filesystem queue."""

import fcntl
import json
import re
import time
import uuid
from pathlib import Path

from syllaro.schema import Job, validate_job


class QueueError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def contained(root: Path, path: Path) -> Path:
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise QueueError("unsafe_path", "Queue path is unsafe", 409)
    return path


def job_path(root: Path, ident: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", ident):
        raise QueueError("invalid_id", "Invalid job ID")
    return contained(root, root / f"{ident}.json")


def get_job(root: Path, ident: str) -> Job:
    path = job_path(root, ident)
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("Oversized record")
        return validate_job(json.loads(path.read_text()), ident)
    except FileNotFoundError as error:
        raise QueueError("missing_job", "Job not found", 404) from error
    except (ValueError, OSError) as error:
        raise QueueError("invalid_record", "Cannot read a valid job record", 500) from error


def list_jobs(root: Path) -> tuple[list[Job], int]:
    jobs = []
    invalid = 0
    for path in sorted(root.glob("*.json")):
        try:
            jobs.append(get_job(root, path.stem))
        except QueueError:
            invalid += 1
    return jobs, invalid


def submit_job(root: Path, source: str, kind="youtube", profile="local") -> Job:
    from syllaro.cli import write_json

    if kind in ("audio", "transcript"):
        path = Path(source)
        if kind == "audio" and (path.is_symlink() or not path.is_file()):
            raise ValueError("Audio source must be a regular local file")
        source = str(path.resolve(strict=True))
    ident = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
    job = validate_job(
        dict(
            id=ident,
            source=source,
            kind=kind,
            profile=profile,
            status="pending",
            created=time.time(),
        ),
        ident,
    )
    root.mkdir(parents=True, exist_ok=True)
    write_json(job_path(root, ident), job)
    return job


def retry_job(root: Path, ident: str) -> Job:
    from syllaro.cli import write_json

    path = job_path(root, ident)
    lock_path = contained(root, root / "worker.lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise QueueError(
                "worker_busy", "Worker is busy; retry after it releases the queue", 423
            ) from error
        job = get_job(root, ident)
        if job["status"] != "failed":
            raise QueueError("not_failed", "Only failed jobs can be retried", 409)
        job["status"] = "transcribed" if job.get("stage") == "summarize" else "pending"
        job["error"] = None
        write_json(path, job)
        return job


ARTIFACTS = {
    "transcript": "transcript.txt",
    "briefing": "summary.md",
    "action-items": "action-items.md",
}


def artifact_path(root: Path, ident: str, name: str) -> Path:
    job_path(root, ident)
    directory = contained(root, root / ident)
    return contained(root, directory / ARTIFACTS[name])


def read_artifact(root: Path, ident: str, name: str) -> str:
    get_job(root, ident)
    path = artifact_path(root, ident, name)
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            raise QueueError("artifact_too_large", "Artifact exceeds the browser size limit", 413)
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise QueueError("missing_artifact", "Artifact is not available yet", 404) from error
    except (OSError, UnicodeError) as error:
        raise QueueError("unreadable_artifact", "Cannot read artifact", 500) from error
