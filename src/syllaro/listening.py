# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private durable evidence of completed listens; missing evidence is unknown."""

import hashlib
import html
import json
import math
import re
import time
from datetime import datetime

from syllaro.feeds import feed_url, registry_path

MAX_BYTES = 10 * 1024 * 1024


def media_key(feed, url):
    return hashlib.sha256((feed + "\0" + feed_url(url)).encode()).hexdigest()


def metadata_key(feed, title, published):
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Missing episode title")
    if isinstance(published, str):
        date = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("Missing episode timezone")
        published = date.timestamp()
    if type(published) not in (int, float) or not math.isfinite(published) or published < 0:
        raise ValueError("Invalid episode publication date")
    title = " ".join(html.unescape(title).split())
    return hashlib.sha256((feed + "\0" + title + "\0" + str(int(published))).encode()).hexdigest()


def state_path(root):
    directory = registry_path(root).parent
    directory.chmod(0o700)
    path = directory / "pocketcasts-listening.json"
    if path.is_symlink() or path.with_suffix(".tmp").is_symlink():
        raise ValueError("Listening state must not be a symlink")
    return path


def load(root):
    path = state_path(root)
    if not path.exists():
        return {"version": 1, "completed": [], "coverage": "unknown"}
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Listening state exceeds the size limit")
    state = json.loads(raw)
    if (
        not isinstance(state, dict)
        or type(state.get("version")) is not int
        or state["version"] != 1
    ):
        raise ValueError("Invalid listening state version")
    keys = state.get("completed")
    if (
        not isinstance(keys, list)
        or len(keys) != len(set(k for k in keys if isinstance(k, str)))
        or any(not isinstance(k, str) or not re.fullmatch("[0-9a-f]{64}", k) for k in keys)
    ):
        raise ValueError("Invalid completed-listen evidence")
    metadata = state.get("completed_metadata", [])
    if not isinstance(metadata, list) or any(
        not isinstance(k, str) or not re.fullmatch("[0-9a-f]{64}", k) for k in metadata
    ):
        raise ValueError("Invalid completed metadata evidence")
    if state.get("coverage") not in ("unknown", "recent_history_only"):
        raise ValueError("Invalid listening coverage")
    date = state.get("last_sync")
    if date is not None and (type(date) not in (int, float) or not math.isfinite(date) or date < 0):
        raise ValueError("Invalid listening timestamp")
    return state


def update(root, rows, podcast_feeds):
    """Accumulate positive completion evidence; never infer unplayed from absence."""
    from syllaro.cli import write_json

    state = load(root)
    completed = set(state["completed"])
    metadata = set(state.get("completed_metadata", []))
    matched = unknown = partial = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid listening history record")
        status = row.get("playingStatus")
        if type(status) is not int or status not in (1, 2, 3):
            unknown += 1
            continue
        if status != 3:
            partial += 1
            continue
        feed = podcast_feeds.get(row.get("podcastUuid"))
        url = row.get("url")
        if not feed or not url:
            unknown += 1
            continue
        try:
            completed.add(media_key(feed, url))
        except ValueError:
            unknown += 1
            continue
        try:
            metadata.add(metadata_key(feed, row.get("title"), row.get("published")))
        except (ValueError, OverflowError):
            pass
        matched += 1
    state.update(
        completed=sorted(completed),
        completed_metadata=sorted(metadata),
        coverage="recent_history_only",
        last_sync=time.time(),
    )
    if len(json.dumps(state).encode()) > MAX_BYTES:
        raise ValueError("Listening state exceeds the size limit")
    path = state_path(root)
    path.with_suffix(".tmp").touch(mode=0o600)
    path.with_suffix(".tmp").chmod(0o600)
    write_json(path, state)
    path.chmod(0o600)
    return {
        "history_received": len(rows),
        "completed_received": matched,
        "completed_retained": len(completed),
        "partial_or_unplayed": partial,
        "unknown_or_unmatched": unknown,
        "coverage": state["coverage"],
    }


def is_completed(record, completed, metadata=()):
    try:
        if (
            record.get("enclosure")
            and media_key(record["feed_id"], record["enclosure"]) in completed
        ):
            return True
        return metadata_key(record["feed_id"], record["title"], record.get("published")) in metadata
    except (ValueError, OverflowError):
        return False
