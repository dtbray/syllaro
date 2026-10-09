# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private Pocket Casts signals and publisher metadata; never claim or queue jobs."""

import concurrent.futures
import fcntl
import gzip
import hashlib
import io
import json
import math
import re
import time
import urllib.request
import uuid
from typing import Any
from urllib.parse import urlsplit

from syllaro.feeds import read_registry, registry_path
from syllaro.listening import media_key, metadata_key
from syllaro.pocketcasts import MAX_BYTES, NoRedirect
from syllaro.screening import (
    checked_url,
    classify,
    load_state,
    plain,
    save_state,
    state_path,
    validate_profile,
)

CACHE = "https://cache.pocketcasts.com"
KINDS = ("bookmarks", "starred", "up_next")


def path(root):
    directory = registry_path(root).parent
    target = directory / "pocketcasts-metadata.json"
    if target.is_symlink() or target.with_suffix(".tmp").is_symlink():
        raise ValueError("Podcast metadata must not be a symlink")
    return target


def valid_uuid(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid podcast metadata identity") from None


def public_url(value):
    from syllaro.feeds import feed_url

    feed_url(value)
    p = urlsplit(value)
    if p.scheme != "https" or p.username is not None or p.fragment:
        raise ValueError("Invalid public metadata URL")
    return value


def get_public(url, timeout=15, text=False):
    """Bounded HTTPS reads, no account credentials, proxies or redirects."""
    public_url(url)
    checked_url(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Syllaro-metadata/0.2",
            "Accept-Encoding": "gzip",
            "Accept": "text/plain, text/vtt, application/json" if text else "application/json",
        },
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            kind = response.headers.get_content_type()
            allowed = {"application/json", "text/plain", "text/vtt", "application/x-subrip"}
            if kind not in (allowed if text else {"application/json"}):
                raise ValueError()
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError()
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                    raw = compressed.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError()
            elif encoding != "identity":
                raise ValueError()
            if text:
                return raw.decode("utf-8-sig"), kind
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
    except (OSError, ValueError, EOFError):
        raise ValueError("Public podcast metadata request failed") from None


def sequence(value):
    if not isinstance(value, list) or len(value) > 10000:
        raise ValueError("Invalid podcast metadata list")
    return value


def normalize_signals(kind, value):
    if kind not in KINDS or not isinstance(value, dict):
        raise ValueError("Invalid podcast signal response")
    result: dict[str, Any] = {}
    if kind == "bookmarks":
        rows = sequence(value.get("bookmarks"))
    elif kind == "starred":
        rows = sequence(value.get("episodes"))
    else:
        episodes = value.get("episodes")
        order = value.get("order")
        if isinstance(episodes, dict):
            order = sequence(order)
            if (
                any(not isinstance(i, str) for i in order)
                or len(set(order)) != len(order)
                or any(i not in episodes or not isinstance(episodes[i], dict) for i in order)
            ):
                raise ValueError("Incomplete Up Next metadata")
            rows = [dict(episodes[i], uuid=i) for i in order]
        else:
            rows = sequence(episodes)
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Invalid podcast signal")
        episode = valid_uuid(row.get("episode_uuid", row.get("episodeUuid", row.get("uuid"))))
        podcast = valid_uuid(row.get("podcast_uuid", row.get("podcastUuid", row.get("podcast"))))
        key = podcast + "/" + episode
        signal = result.setdefault(key, {"podcast": podcast, "episode": episode})
        if kind == "bookmarks":
            second = row.get("time")
            if type(second) is not int or second < 0:
                raise ValueError("Invalid bookmark timestamp")
            bookmark = {"time": second, "title": text_value(row.get("title"))}
            passage = row.get("passage")
            if passage is not None:
                if not isinstance(passage, str):
                    raise ValueError("Invalid bookmark passage")
                bookmark["passage"] = plain(passage)
            signal.setdefault("bookmarks", []).append(bookmark)
        else:
            signal[kind] = True
            if kind == "up_next":
                signal["position"] = position
                # Some web responses also contain identity metadata, never trusted by title alone.
                signal["identity"] = {k: row[k] for k in ("url", "title", "published") if k in row}
    return result


def text_value(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Invalid podcast text metadata")
    return plain(value)


def assets(episode):
    if not isinstance(episode, dict):
        raise ValueError("Invalid podcast asset metadata")
    result = {"notes": text_value(episode.get("show_notes")), "chapters": [], "transcripts": []}
    for chapter in sequence(episode.get("chapters") if episode.get("chapters") is not None else []):
        if not isinstance(chapter, dict):
            raise ValueError("Invalid podcast chapter")
        start, end = chapter.get("startTime"), chapter.get("endTime")
        if (
            not isinstance(start, (int, float))
            or isinstance(start, bool)
            or not math.isfinite(start)
            or start < 0
        ):
            raise ValueError("Invalid chapter timestamp")
        if end is not None and (
            type(end) not in (int, float) or not math.isfinite(end) or end < start
        ):
            raise ValueError("Invalid chapter endpoint")
        result["chapters"].append(
            {"start": start, "end": end, "title": text_value(chapter.get("title"))}
        )
    for transcript in sequence(
        episode.get("transcripts") if episode.get("transcripts") is not None else []
    ):
        if not isinstance(transcript, dict) or any(
            not isinstance(transcript.get(k, ""), (str, type(None))) for k in ("type", "language")
        ):
            raise ValueError("Invalid transcript metadata")
        result["transcripts"].append(
            {
                "url": public_url(transcript.get("url")),
                "type": transcript.get("type") or "unknown",
                "language": transcript.get("language") or "unknown",
            }
        )
    if episode.get("chapters_url"):
        result["chapters_url"] = public_url(episode["chapters_url"])
    return result


def validate(state):
    if (
        not isinstance(state, dict)
        or type(state.get("version")) is not int
        or state["version"] != 1
    ):
        raise ValueError("Invalid podcast metadata state")
    if not isinstance(state.get("episodes"), dict) or not isinstance(state.get("sources"), dict):
        raise ValueError("Invalid podcast metadata records")
    for date in (
        state.get("fetched_at"),
        *(r.get("fetched_at") for r in state["sources"].values() if isinstance(r, dict)),
        *(r.get("fetched_at") for r in state["episodes"].values() if isinstance(r, dict)),
    ):
        if date is not None and (
            type(date) not in (int, float) or not math.isfinite(date) or date < 0
        ):
            raise ValueError("Invalid podcast metadata timestamp")
    for kind, source in state["sources"].items():
        if kind not in KINDS or not isinstance(source, dict):
            raise ValueError("Invalid podcast signal source")
        if source.get("status") not in ("ok", "failed") or not isinstance(
            source.get("records"), dict
        ):
            raise ValueError("Invalid podcast signal coverage")
        if len(source["records"]) > 10000:
            raise ValueError("Too many podcast signals")
        for key, row in source["records"].items():
            if not isinstance(row, dict):
                raise ValueError("Invalid persisted podcast signal")
            for field in ("starred", "up_next"):
                if field in row and type(row[field]) is not bool:
                    raise ValueError("Invalid persisted interest signal")
            if key != valid_uuid(row.get("podcast")) + "/" + valid_uuid(row.get("episode")):
                raise ValueError("Invalid persisted podcast signal")
            for bookmark in sequence(row.get("bookmarks", [])):
                if (
                    not isinstance(bookmark, dict)
                    or type(bookmark.get("time")) is not int
                    or bookmark["time"] < 0
                ):
                    raise ValueError("Invalid persisted bookmark")
                if not isinstance(bookmark.get("title"), str):
                    raise ValueError("Invalid persisted bookmark title")
                text_value(bookmark.get("title"))
                text_value(bookmark.get("passage"))
    for ident, row in state["episodes"].items():
        if not re.fullmatch(r"episode-[0-9a-f]{64}", ident) or not isinstance(row, dict):
            raise ValueError("Invalid enriched episode identity")
        valid_uuid(row.get("podcast"))
        valid_uuid(row.get("episode"))
        if not isinstance(row.get("notes"), str):
            raise ValueError("Invalid enriched show notes")
        assets({"show_notes": row["notes"], "transcripts": row.get("transcripts", [])})
        for chapter in sequence(row.get("chapters", [])):
            assets(
                {
                    "chapters": [
                        {
                            "startTime": chapter.get("start"),
                            "endTime": chapter.get("end"),
                            "title": chapter.get("title"),
                        }
                    ]
                }
            )
        if row.get("chapters_url"):
            public_url(row["chapters_url"])
    return state


def load(root):
    target = path(root)
    if not target.exists():
        return {"version": 1, "sources": {}, "episodes": {}}
    with target.open("rb") as stream:
        raw = stream.read(20 * MAX_BYTES + 1)
    if len(raw) > 20 * MAX_BYTES:
        raise ValueError("Podcast metadata state exceeds the size limit")
    return validate(json.loads(raw))


def save(root, state):
    from syllaro.cli import write_json

    validate(state)
    if len(json.dumps(state).encode()) > 20 * MAX_BYTES:
        raise ValueError("Podcast metadata state exceeds the size limit")
    target = path(root)
    target.with_suffix(".tmp").touch(mode=0o600)
    target.with_suffix(".tmp").chmod(0o600)
    write_json(target, state)
    target.chmod(0o600)


def lookup_index(catalog):
    index: dict[str, list[str]] = {}
    for ident, row in catalog["episodes"].items():
        for key in identity_keys(
            row["feed_id"],
            {"url": row["enclosure"], "title": row["title"], "published": row["published"]},
        ):
            index.setdefault(key, []).append(ident)
    return index


def identity_keys(feed, row):
    keys = []
    for fn, args in (
        (media_key, (feed, row.get("url"))),
        (metadata_key, (feed, row.get("title"), row.get("published"))),
    ):
        try:
            keys.append(fn(*args))
        except (ValueError, TypeError):
            pass
    return keys


def enrich(root, client, profile, feed_limit=20):
    """Refresh signals and bounded show metadata; callers hold worker lock."""
    profile = validate_profile(profile)
    if type(feed_limit) is not int or not 1 <= feed_limit <= 1000:
        raise ValueError("Invalid enrichment feed limit")
    with state_path(root).with_name("screening.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        catalog = load_state(root)
        state = load(root)
        report: dict[str, Any] = {
            "episodes_queued": 0,
            "account_writes": 0,
            "sources": {},
            "metadata_failed": 0,
            "metadata_fetched": 0,
            "errors": [],
        }
        for kind in KINDS:
            try:
                records = normalize_signals(kind, client.signals(kind))
                state["sources"][kind] = {
                    "status": "ok",
                    "records": records,
                    "fetched_at": time.time(),
                }
            except ValueError:
                state["sources"][kind] = dict(
                    state["sources"].get(kind, {"records": {}}), status="failed"
                )
            report["sources"][kind] = {
                "status": state["sources"][kind]["status"],
                "records": len(state["sources"][kind]["records"]),
            }
        index = lookup_index(catalog)
        for source in state["sources"].values():
            for signal in source["records"].values():
                feed = client.podcast_feeds.get(signal["podcast"])
                guid_matches = [
                    r["id"]
                    for r in catalog["episodes"].values()
                    if r["feed_id"] == feed
                    and r["guid"] in (signal["episode"], "urn:uuid:" + signal["episode"])
                ]
                if len(guid_matches) == 1:
                    state["episodes"].setdefault(
                        guid_matches[0],
                        {
                            "notes": "",
                            "chapters": [],
                            "transcripts": [],
                            "podcast": signal["podcast"],
                            "episode": signal["episode"],
                        },
                    )
        enabled = {f["id"] for f in read_registry(root)["feeds"] if f["enabled"]}
        feeds = [
            (p, f)
            for p, f in client.podcast_feeds.items()
            if f in catalog["feeds"] and f in enabled
        ]
        feeds.sort(key=lambda item: item[0])
        report["selected_feeds"] = min(feed_limit, len(feeds))
        report["unselected_feeds"] = max(0, len(feeds) - feed_limit)

        def fetch(item):
            podcast, feed = item
            full = get_public(
                CACHE + "/mobile/podcast/full/" + valid_uuid(podcast) + "?disableredirect=true",
                client.timeout,
            )
            if "url" in full:
                full = get_public(full["url"], client.timeout)
            body = full.get("podcast")
            if not isinstance(body, dict) or body.get("uuid") != podcast:
                raise ValueError("Invalid podcast metadata membership")
            identities = {valid_uuid(e.get("uuid")): e for e in sequence(body.get("episodes"))}
            location = get_public(
                CACHE + "/mobile/show_notes/full/" + podcast + "?disableredirect=true",
                client.timeout,
            )
            notes = get_public(location.get("url"), client.timeout).get("podcast")
            if not isinstance(notes, dict) or notes.get("uuid") != podcast:
                raise ValueError("Invalid show notes membership")
            rows = {}
            for episode in sequence(notes.get("episodes")):
                episode_id = valid_uuid(episode.get("uuid"))
                identity = identities.get(episode_id, {})
                matches = {i for k in identity_keys(feed, identity) for i in index.get(k, [])}
                if len(matches) != 1:
                    continue
                enriched = assets(episode)
                if enriched.get("chapters_url") and not enriched["chapters"]:
                    enriched["chapters"] = assets(
                        get_public(enriched["chapters_url"], client.timeout)
                    )["chapters"]
                rows[next(iter(matches))] = dict(
                    enriched, podcast=podcast, episode=episode_id, fetched_at=time.time()
                )
            return rows

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fetch, item): item[1] for item in feeds[:feed_limit]}
            for future in concurrent.futures.as_completed(futures):
                try:
                    state["episodes"].update(future.result())
                    report["metadata_fetched"] += 1
                except (OSError, ValueError, TypeError, KeyError):
                    report["metadata_failed"] += 1
                    report["errors"].append(
                        {
                            "feed_id": futures[future],
                            "error": "publisher_metadata_fetch_or_parse_failed",
                        }
                    )
        # Resolve Up Next skeletons even when public show notes are unavailable.
        for signal in state["sources"].get("up_next", {}).get("records", {}).values():
            feed = client.podcast_feeds.get(signal["podcast"])
            matches = (
                {
                    i
                    for k in identity_keys(feed, signal.get("identity", {}))
                    for i in index.get(k, [])
                }
                if feed
                else set()
            )
            if len(matches) == 1:
                ident = next(iter(matches))
                state["episodes"].setdefault(
                    ident,
                    {
                        "notes": "",
                        "chapters": [],
                        "transcripts": [],
                        "podcast": signal["podcast"],
                        "episode": signal["episode"],
                    },
                )
        for ident, enriched in state["episodes"].items():
            row = catalog["episodes"].get(ident)
            if row and len(enriched["notes"].split()) > len(row["notes"].split()):
                row["notes"] = enriched["notes"]
                row["metadata_hash"] = hashlib.sha256(
                    (row["title"] + "\n" + row["notes"]).encode()
                ).hexdigest()
                row["classification"] = classify(row["title"], row["notes"], profile)
                if not row["enclosure"]:
                    row["classification"].update(
                        decision="review", rationale="No enclosure advertised in feed metadata"
                    )
        state["last_sync"] = report
        save(root, state)
        save_state(root, catalog)
        mapped = {r["podcast"] + "/" + r["episode"] for r in state["episodes"].values()}
        report["unmatched_signals"] = {
            k: sum(i not in mapped for i in v["records"]) for k, v in state["sources"].items()
        }
        report["indexed_metadata"] = len(state["episodes"])
        report["transcript_candidates"] = sum(
            bool(r.get("transcripts")) for r in state["episodes"].values()
        )
        return report


def evidence(state, ident):
    row = state["episodes"].get(ident, {})
    key = row.get("podcast", "") + "/" + row.get("episode", "")
    result = {"bookmarks": [], "starred": False, "up_next": False}
    for kind in KINDS:
        source = state["sources"].get(kind, {})
        # Failed refreshes retain cached data for inspection, but do not change ranking.
        if source.get("status") == "ok":
            result[kind] = source["records"].get(key, {}).get(kind, result[kind])
    result.update(chapters=row.get("chapters", []), transcripts=row.get("transcripts", []))
    return result


def fetch_transcript(root, ident, index=0, timeout=15):
    """Export an explicitly selected text candidate, preserving publisher evidence."""
    from syllaro.cli import write_json

    if not re.fullmatch(r"episode-[0-9a-f]{64}", ident) or type(index) is not int or index < 0:
        raise ValueError("Invalid transcript selection")
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("Invalid transcript timeout")
    candidates = load(root)["episodes"].get(ident, {}).get("transcripts", [])
    if index >= len(candidates):
        raise ValueError("No publisher transcript at the selected index")
    content, kind = get_public(candidates[index]["url"], timeout, text=True)
    if not content.strip():
        raise ValueError("Publisher transcript is empty")
    # Text candidates remain separate from worker artifacts; never mark ASR/diarization done.
    directory = path(root).parent / "publisher-transcripts"
    if directory.is_symlink():
        raise ValueError("Publisher transcript directory must not be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    target = directory / (ident + "-" + str(index) + ".json")
    if target.is_symlink() or target.with_suffix(".tmp").is_symlink():
        raise ValueError("Publisher transcript must not be a symlink")
    timed = bool(re.search(r"\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}\s*-->", content))
    artifact = {
        "version": 1,
        "episode_id": ident,
        "content": content,
        "content_type": kind,
        "source": "publisher; untrusted evidence",
        "has_cue_timestamps": timed,
        "speaker_labels": "unverified",
        "asr_replaced": False,
        "diarization_replaced": False,
    }
    target.with_suffix(".tmp").touch(mode=0o600)
    target.with_suffix(".tmp").chmod(0o600)
    write_json(target, artifact)
    target.chmod(0o600)
    return {
        k: v
        for k, v in dict(artifact, artifact=str(target), episodes_queued=0).items()
        if k != "content"
    }
