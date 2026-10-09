# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private durable evidence of completed listens; missing evidence is unknown."""

import hashlib
import html
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

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
    if state.get("coverage") not in (
        "unknown",
        "recent_history_only",
        "year_backfill",
        "year_backfill_partial",
    ):
        raise ValueError("Invalid listening coverage")
    if "backfill_since_year" in state or "backfill_through_year" in state:
        first, last = state.get("backfill_since_year"), state.get("backfill_through_year")
        if type(first) is not int or type(last) is not int or not 2004 <= first <= last <= 2100:
            raise ValueError("Invalid persisted backfill range")
    date = state.get("last_sync")
    if date is not None and (type(date) not in (int, float) or not math.isfinite(date) or date < 0):
        raise ValueError("Invalid listening timestamp")
    return state


def update(
    root, rows, podcast_feeds, coverage="recent_history_only", since_year=None, through_year=None
):
    """Accumulate positive completion evidence; never infer unplayed from absence."""
    from syllaro.cli import write_json

    if coverage not in ("recent_history_only", "year_backfill", "year_backfill_partial"):
        raise ValueError("Invalid listening coverage")
    state = load(root)
    if since_year is not None or through_year is not None:
        if (
            type(since_year) is not int
            or type(through_year) is not int
            or not 2004 <= since_year <= through_year <= 2100
        ):
            raise ValueError("Invalid listening backfill range")
        state.update(backfill_since_year=since_year, backfill_through_year=through_year)
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
        coverage=state.get("coverage")
        if coverage == "recent_history_only"
        and state.get("coverage") in ("year_backfill", "year_backfill_partial")
        else coverage,
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


def validate_backfill_year(since_year):
    current_year = datetime.now(timezone.utc).year  # noqa: UP017 - Preserve core wheel Python 3.10 compatibility.
    if type(since_year) is not int or not 2004 <= since_year <= current_year:
        raise ValueError("Invalid listening backfill year")
    return current_year


def backfill(root, client, since_year):
    """Read yearly interactions, then independently verify completed playback states."""
    current_year = validate_backfill_year(since_year)
    changes = {}
    years = []
    for year in range(since_year, current_year + 1):
        count = client.request(year=year, count=True).get("count")
        if type(count) is not int or not 0 <= count <= 100000:
            raise ValueError("Invalid yearly listening count")
        history = client.request(year=year).get("history") if count else {"changes": []}
        if not isinstance(history, dict):
            raise ValueError("Invalid yearly listening history")
        rows = history.get("changes")
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError("Incomplete yearly listening response")
        years.append({"year": year, "count": count})
        for row in rows:
            if not isinstance(row, dict) or type(row.get("action")) is not int:
                raise ValueError("Invalid yearly listening change")
            if row["action"] != 1:
                continue
            podcast, episode = row.get("podcast"), row.get("episode")
            if not isinstance(podcast, str) or not isinstance(episode, str):
                raise ValueError("Invalid yearly episode identity")
            if podcast in client.podcast_feeds:
                changes[(podcast, episode)] = row
    podcasts = sorted({key[0] for key in changes})

    def fetch(podcast):
        try:
            rows = client.request(podcast=podcast).get("episodes")
            if not isinstance(rows, list) or len(rows) > 100000:
                raise ValueError("Invalid playback states")
            states = {}
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("uuid"), str):
                    raise ValueError("Invalid playback state")
                status = row.get("playingStatus")
                if type(status) is int and status in (1, 2, 3):
                    states[row["uuid"]] = status
            return podcast, states
        except ValueError:
            return podcast, None

    evidence = []
    failed = unknown = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        for podcast, states in pool.map(fetch, podcasts):
            if states is None:
                failed += 1
                continue
            for (parent, episode), row in changes.items():
                if parent != podcast:
                    continue
                status = states.get(episode)
                if status is None:
                    unknown += 1
                    continue
                evidence.append(
                    {
                        "podcastUuid": podcast,
                        "playingStatus": status,
                        "url": row.get("url"),
                        "title": row.get("title"),
                        "published": row.get("published"),
                    }
                )
    result = update(
        root,
        evidence,
        client.podcast_feeds,
        coverage="year_backfill_partial" if failed or unknown else "year_backfill",
        since_year=since_year,
        through_year=current_year,
    )
    result.update(
        years=years,
        interactions_received=sum(y["count"] for y in years),
        subscribed_interactions=len(changes),
        failed_podcasts=failed,
        missing_playback_states=unknown,
        since_year=since_year,
    )
    return result
