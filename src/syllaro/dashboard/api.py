# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional, loopback-only HTTP adapter; never starts a processing worker."""

import argparse
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from syllaro.schema import ProfileName, Status, validate_config
from syllaro.services import (
    ARTIFACTS,
    QueueError,
    artifact_path,
    get_job,
    list_jobs,
    read_artifact,
    retry_job,
    submit_job,
)


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=2048)
    profile: ProfileName = "local"


class JobView(BaseModel):
    id: str
    queue: str
    title: str
    source: str
    kind: Literal["youtube", "transcript", "audio"]
    profile: ProfileName
    status: Status
    created: float | None = None
    started: float | None = None
    finished: float | None = None
    stage: str | None = None
    error: str | None = None
    artifacts: list[str]


class JobList(BaseModel):
    jobs: list[JobView]
    queues: list[str]
    invalid_records: int


class Artifact(BaseModel):
    content: str
    format: Literal["text", "markdown"]


class Health(BaseModel):
    status: str = "ok"
    execution: str = "Existing CLI workers; API only enqueues"


class ErrorBody(BaseModel):
    code: str
    message: str


ERRORS = {status: {"model": ErrorBody} for status in (400, 403, 404, 409, 413, 422, 423, 500)}


def create_app(queues: dict[str, Path], frontend: Path | None = None) -> FastAPI:
    if not queues or any(not name.replace("-", "").isalnum() for name in queues):
        raise ValueError("Provide named queues using letters, numbers and hyphens")
    app = FastAPI(title="Syllaro local API", version="1.0.0")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        # Browser cross-origin writes (including simple form requests) are forbidden.
        # No CORS middleware: browser reads remain same-origin as well.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"code": "foreign_origin", "message": "Use the local interface"},
                    status_code=403,
                )
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    {"code": "foreign_origin", "message": "Use the local interface"},
                    status_code=403,
                )
        return await call_next(request)

    @app.exception_handler(QueueError)
    async def queue_error(request, error):
        return JSONResponse({"code": error.code, "message": str(error)}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse(
            {"code": "invalid_request", "message": "Invalid request fields"}, status_code=422
        )

    @app.exception_handler(OSError)
    async def storage_error(request, error):
        return JSONResponse(
            {"code": "storage_error", "message": "Queue storage is unavailable"}, status_code=500
        )

    def root_for(queue: str | None) -> tuple[str, Path]:
        name = queue or next(iter(queues))
        if name not in queues:
            raise QueueError("missing_queue", "Queue not found", 404)
        return name, queues[name]

    def view(job, name, root):
        available = []
        for artifact in ARTIFACTS:
            try:
                if artifact_path(root, job["id"], artifact).is_file():
                    available.append(artifact)
            except QueueError:
                pass
        return JobView(
            **{
                key: job.get(key)
                for key in (
                    "id",
                    "kind",
                    "profile",
                    "status",
                    "created",
                    "started",
                    "finished",
                    "stage",
                    "error",
                )
            },
            queue=name,
            source=job["source"] if job["kind"] == "youtube" else Path(job["source"]).name,
            title=job.get("title")
            or (job["source"] if job["kind"] == "youtube" else Path(job["source"]).name),
            artifacts=available,
        )

    @app.get("/api/v1/health", response_model=Health)
    def health():
        return Health()

    @app.get("/api/v1/jobs", response_model=JobList, responses=ERRORS)
    def jobs(queue: str | None = None):
        selected = {queue: root_for(queue)[1]} if queue else queues
        rows: list[JobView] = []
        invalid = 0
        for name, root in selected.items():
            records, count = list_jobs(root)
            invalid += count
            rows.extend(view(job, name, root) for job in records)
        rows.sort(key=lambda row: row.created or 0, reverse=True)
        return JobList(jobs=rows, queues=list(queues), invalid_records=invalid)

    @app.post("/api/v1/jobs", response_model=JobView, status_code=201, responses=ERRORS)
    def submit(body: Submission, queue: str | None = None):
        name, root = root_for(queue)
        try:
            job = submit_job(root, body.source.strip(), profile=body.profile)
        except ValueError as error:
            raise QueueError("invalid_source", "Enter an HTTP(S) YouTube URL") from error
        return view(job, name, root)

    @app.get("/api/v1/jobs/{ident}", response_model=JobView, responses=ERRORS)
    def detail(ident: str, queue: str | None = None):
        name, root = root_for(queue)
        return view(get_job(root, ident), name, root)

    @app.get("/api/v1/jobs/{ident}/transcript", response_model=Artifact, responses=ERRORS)
    def transcript(ident: str, queue: str | None = None):
        return Artifact(
            content=read_artifact(root_for(queue)[1], ident, "transcript"), format="text"
        )

    @app.get("/api/v1/jobs/{ident}/briefing", response_model=Artifact, responses=ERRORS)
    def briefing(ident: str, queue: str | None = None):
        return Artifact(
            content=read_artifact(root_for(queue)[1], ident, "briefing"), format="markdown"
        )

    @app.get("/api/v1/jobs/{ident}/action-items", response_model=Artifact, responses=ERRORS)
    def actions(ident: str, queue: str | None = None):
        return Artifact(
            content=read_artifact(root_for(queue)[1], ident, "action-items"), format="markdown"
        )

    @app.post("/api/v1/jobs/{ident}/retry", response_model=JobView, responses=ERRORS)
    def retry(ident: str, queue: str | None = None):
        name, root = root_for(queue)
        return view(retry_job(root, ident), name, root)

    if frontend and (frontend / "index.html").is_file():
        if (frontend / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api") or "." in path:
                return JSONResponse({"code": "not_found", "message": "Not found"}, status_code=404)
            return FileResponse(frontend / "index.html")

    return app


def main():
    parser = argparse.ArgumentParser(description="Syllaro local web UI (no processing worker)")
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/syllaro/config.json")
    parser.add_argument(
        "--queue",
        action="append",
        default=[],
        metavar="NAME=CONFIG",
        help="Additional existing queue configs",
    )
    parser.add_argument("--frontend-dir", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    configs = {"main": args.config}
    for value in args.queue:
        name, separator, path = value.partition("=")
        if not separator or name in configs:
            parser.error("Expected a unique NAME=CONFIG")
        configs[name] = Path(path).expanduser()
    queues = {
        name: Path(validate_config(json.loads(path.read_text()))["data_dir"]).expanduser()
        for name, path in configs.items()
    }
    import uvicorn

    uvicorn.run(create_app(queues, args.frontend_dir), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
