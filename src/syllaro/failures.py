# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded, redacted subprocess diagnostics suitable for persisted job errors."""

from pathlib import Path


def log_failure(path: Path, label: str, returncode: int, offset: int = 0) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(offset, stream.tell() - 65536))
            tail = stream.read(65536).decode("utf-8", errors="replace")
    except OSError:
        tail = ""
    causes = (
        ("missing a timestamp", "ASR returned missing timestamps; audio retained for retry"),
        ("invalid timestamps", "ASR returned invalid timestamps; audio retained for retry"),
        (
            "HTTP Error 403",
            "YouTube rejected the download (HTTP 403); check downloader/JavaScript runtime",
        ),
        (
            "No supported JavaScript runtime",
            "YouTube downloader needs a supported JavaScript runtime",
        ),
        ("out of memory", "GPU memory exhausted; retry when GPU memory is available"),
        (
            "Alignment produced no timestamped words",
            "Alignment produced no timestamped words; audio retained",
        ),
    )
    for marker, message in causes:
        if marker.lower() in tail.lower():
            return message
    return f"{label} failed (exit {returncode}); see process.log for details"
