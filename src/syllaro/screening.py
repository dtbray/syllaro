# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded RSS/Atom metadata screening. No enclosure downloads or inference calls."""

import base64
import concurrent.futures
import hashlib
import ipaddress
import json
import math
import re
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from syllaro.feeds import feed_url, local_name, read_registry

MAX_BYTES = 5 * 1024 * 1024
DECISIONS = ("process", "skip", "review")
ERROR_CODES = {
    "dns_failure",
    "non_public_address",
    "unsafe_redirect",
    "authentication_requires_https",
    "metadata_too_large",
    "non_metadata_content",
    "metadata_request_failed",
    "invalid_feed_xml",
    "invalid_rss_channel",
    "unsupported_feed_format",
    "xml_declarations_not_supported",
}
DEFAULT_PROFILE = {
    "version": 1,
    "topics": {
        "systems": [
            "distributed systems",
            "networking",
            "kubernetes",
            "linux",
            "storage",
            "self-hosted",
            "observability",
        ],
        "software": [
            "python",
            "rust",
            "golang",
            "software engineering",
            "open source",
            "testing",
            "api",
        ],
        "ai": [
            "coding agents",
            "local inference",
            "quantization",
            "llm",
            "agentic",
            "machine learning",
        ],
        "operations": [
            "msp",
            "halopsa",
            "automation",
            "disaster recovery",
            "security",
            "microsoft",
            "endpoint",
        ],
        "diy": [
            "home repair",
            "electrical",
            "troubleshooting",
            "tools",
            "building science",
            "woodworking",
        ],
        "media": ["fiction", "audiobook", "comedy", "music", "storytelling"],
    },
    "priority_topics": ["systems", "software", "ai", "operations", "diy"],
    "action_terms": [
        "how to",
        "tutorial",
        "guide",
        "practical",
        "implement",
        "workflow",
        "troubleshooting",
        "lessons",
        "checklist",
        "repair",
        "deploy",
        "benchmark",
    ],
    "exclude_terms": [],
}


def validate_profile(profile):
    if (
        not isinstance(profile, dict)
        or type(profile.get("version")) is not int
        or profile["version"] != 1
    ):
        raise ValueError("Unsupported screening profile")
    topics = profile.get("topics")
    if not isinstance(topics, dict) or not topics:
        raise ValueError("Screening topics are required")
    for name, terms in topics.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Invalid screening topic")
        if (
            not isinstance(terms, list)
            or not terms
            or any(not isinstance(t, str) or not t.strip() for t in terms)
        ):
            raise ValueError("Topic terms must be nonempty strings")
    for name in ("action_terms", "exclude_terms", "priority_topics"):
        terms = profile.get(name, [])
        if not isinstance(terms, list) or any(
            not isinstance(t, str) or not t.strip() for t in terms
        ):
            raise ValueError("Invalid screening terms")
    if any(t not in topics for t in profile.get("priority_topics", [])):
        raise ValueError("Unknown priority topic")
    return profile


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(text):
    parser = PlainText()
    parser.feed(text)
    return " ".join(" ".join(parser.parts).split())[:16000]


def child_text(node, *names):
    for name in names:
        for child in node:
            if local_name(child) == name:
                value = plain(" ".join(child.itertext()))
                if value:
                    return value
    return ""


def published(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    try:
        return (date if date.tzinfo else date.replace(tzinfo=UTC)).timestamp()
    except (ValueError, OverflowError):
        return None


def parse_metadata(raw, ident, limit):
    if len(raw) > MAX_BYTES:
        raise ValueError("metadata_too_large")
    declaration = raw.replace(b"\x00", b"").lower()
    if b"<!doctype" in declaration or b"<!entity" in declaration:
        raise ValueError("xml_declarations_not_supported")
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("invalid_feed_xml") from error
    kind = local_name(tree)
    if kind == "rss":
        channels = [n for n in tree if local_name(n) == "channel"]
        if len(channels) != 1:
            raise ValueError("invalid_rss_channel")
        channel, entry_name = channels[0], "item"
    elif kind == "feed":
        channel, entry_name = tree, "entry"
    else:
        raise ValueError("unsupported_feed_format")
    feed = {
        "title": child_text(channel, "title"),
        "description": child_text(channel, "description", "subtitle"),
    }
    items, seen = [], set()
    for entry in channel:
        if local_name(entry) != entry_name:
            continue
        title = child_text(entry, "title") or "Untitled episode"
        notes = child_text(entry, "encoded", "content", "description", "summary")
        # External Atom content is intentionally not followed.
        enclosure = ""
        for node in entry:
            if local_name(node) == "enclosure" or (
                local_name(node) == "link" and node.get("rel") == "enclosure"
            ):
                enclosure = node.get("url") or node.get("href") or ""
                break
        date_text = child_text(entry, "pubDate", "published", "updated")
        guid = child_text(entry, "guid", "id")
        identity = guid or enclosure or (title + "\n" + date_text)
        episode_id = "episode-" + hashlib.sha256((ident + "\n" + identity).encode()).hexdigest()
        if episode_id in seen:
            continue
        seen.add(episode_id)
        items.append(
            {
                "id": episode_id,
                "feed_id": ident,
                "title": title,
                "notes": notes,
                "published": published(date_text),
                "guid": guid,
                "enclosure": enclosure,
                "metadata_hash": hashlib.sha256((title + "\n" + notes).encode()).hexdigest(),
            }
        )
    items.sort(
        key=lambda item: item["published"] if item["published"] is not None else float("-inf"),
        reverse=True,
    )
    return feed, items[:limit]


def checked_url(url):
    feed_url(url)
    parsed = urlsplit(url)
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise ValueError("dns_failure") from error
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("non_public_address")
    return parsed


def origin(url):
    p = urlsplit(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80)


def sample_prefix(raw, limit=5):
    """Extract complete leading entries from a bounded, intentionally unclosed prefix."""
    declaration = raw.replace(b"\x00", b"").lower()
    if b"<!doctype" in declaration or b"<!entity" in declaration:
        raise ValueError("xml_declarations_not_supported")
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(events=("start", "end"))
    stack: list[ET.Element] = []
    items: list[ET.Element] = []
    metadata: list[ET.Element] = []
    root_tag = None
    try:
        parser.feed(raw)
        for event, node in cast("Iterator[tuple[str, ET.Element]]", parser.read_events()):
            if event == "start":
                stack.append(node)
                if root_tag is None:
                    root_tag = node.tag
            else:
                parent = local_name(stack[-2]) if len(stack) > 1 else ""
                if parent in ("channel", "feed"):
                    if local_name(node) in ("item", "entry"):
                        if len(items) < limit:
                            items.append(node)
                    else:
                        metadata.append(node)
                stack.pop()
    except ET.ParseError:
        raise ValueError("metadata_too_large") from None
    if not items or root_tag is None:
        raise ValueError("metadata_too_large")
    if root_tag.rsplit("}", 1)[-1] == "rss":
        root = ET.Element("rss", version="2.0")
        container = ET.SubElement(root, "channel")
    elif root_tag.rsplit("}", 1)[-1] == "feed":
        root = container = ET.Element(root_tag)
    else:
        raise ValueError("unsupported_feed_format")
    container.extend(metadata)
    container.extend(items)
    return ET.tostring(root)


class MetadataRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urljoin(req.full_url, newurl)
        parsed = checked_url(newurl)
        if parsed.username is not None or (
            urlsplit(req.full_url).scheme == "https" and parsed.scheme != "https"
        ):
            raise ValueError("unsafe_redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and origin(req.full_url) != origin(newurl):
            for name in ("Authorization", "If-none-match", "If-modified-since"):
                redirected.remove_header(name)
        return redirected


def fetch_metadata(url, previous, timeout):
    p = checked_url(url)
    headers = {
        "User-Agent": "Syllaro-metadata/0.2",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        "Accept-Encoding": "identity",
    }
    if p.username is not None:
        if p.scheme != "https":
            raise ValueError("authentication_requires_https")
        credentials = unquote(p.username) + ":" + unquote(p.password or "")
        headers["Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode()
    netloc = p.netloc.rsplit("@", 1)[-1]
    clean = urlunsplit((p.scheme, netloc, p.path, p.query, ""))
    for name, key in (("If-None-Match", "etag"), ("If-Modified-Since", "last_modified")):
        if previous.get(key):
            headers[name] = previous[key]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), MetadataRedirect())
    try:
        with opener.open(
            urllib.request.Request(clean, headers=headers), timeout=timeout
        ) as response:
            content_type = response.headers.get_content_type()
            if (
                content_type.startswith(("audio/", "video/"))
                or content_type == "application/octet-stream"
            ):
                raise ValueError("non_metadata_content")
            raw = response.read(MAX_BYTES + 1)
            sampled = False
            if len(raw) > MAX_BYTES:
                raw = sample_prefix(raw[:MAX_BYTES])
                sampled = True
            return raw, {
                "etag": response.headers.get("ETag", ""),
                "last_modified": response.headers.get("Last-Modified", ""),
                "sampled_prefix": sampled,
            }
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return None, {key: previous.get(key, "") for key in ("etag", "last_modified")}
        raise ValueError(f"http_{error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("metadata_request_failed") from None


def matched(text, terms):
    return [
        term
        for term in terms
        if re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text.casefold())
    ]


def classify(title, notes, profile, feed=False):
    text = title + "\n" + notes
    topics = {name: matched(text, terms) for name, terms in profile["topics"].items()}
    topics = {name: terms for name, terms in topics.items() if terms}
    actions = matched(text, profile.get("action_terms", []))
    exclusions = matched(text, profile.get("exclude_terms", []))
    priority = any(name in profile.get("priority_topics", []) for name in topics)
    score = min(
        100,
        sum(min(20, len(terms) * 5) for terms in topics.values())
        + (20 if priority else 0)
        + min(20, len(actions) * 5),
    )
    thin = len(notes.split()) < 30
    decision = "review"
    rationale = (
        "Limited show notes; human review needed"
        if thin and not feed
        else "No strong actionable match; human review needed"
    )
    if not thin or feed:
        if topics and (actions or feed) and priority:
            decision, rationale = (
                "process",
                "Priority interests and practical cues matched"
                if not feed
                else "Priority feed interests matched",
            )
        elif exclusions and not topics:
            decision, rationale = (
                "skip",
                "Explicit exclusion terms matched without interest matches",
            )
    return {
        "decision": decision,
        "score": score,
        "topics": topics,
        "action_cues": actions,
        "rationale": rationale,
        "notes_quality": "thin" if thin else "substantial",
        "method": "keyword-v1; uncalibrated recommendation",
        "confidence": "low",
    }


def state_path(root):
    directory = root / "feeds" / "screening"
    if (root / "feeds").is_symlink() or directory.is_symlink():
        raise ValueError("Screening directory must not be a symlink")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "catalog.json"
    if path.is_symlink() or path.with_suffix(".tmp").is_symlink():
        raise ValueError("Screening state must not be a symlink")
    if path.with_name("screening.lock").is_symlink():
        raise ValueError("Screening lock must not be a symlink")
    return path


def load_state(root):
    path = state_path(root)
    state = (
        json.loads(path.read_text())
        if path.exists()
        else {"version": 1, "feeds": {}, "episodes": {}, "overrides": {"feed": {}, "episode": {}}}
    )
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Invalid screening catalog")
    for scope, prefix in (("feeds", "feed"), ("episodes", "episode")):
        if not isinstance(state.get(scope), dict):
            raise ValueError("Invalid screening records")
        for ident, record in state[scope].items():
            if not re.fullmatch(prefix + r"-[0-9a-f]{64}", ident) or not isinstance(record, dict):
                raise ValueError("Invalid screening identity")
            if record.get("id") != ident or not isinstance(record.get("title"), str):
                raise ValueError("Invalid screening record")
            classification = record.get("classification")
            if (
                not isinstance(classification, dict)
                or classification.get("decision") not in DECISIONS
            ):
                raise ValueError("Invalid screening decision")
            score = classification.get("score")
            if type(score) is not int or not 0 <= score <= 100:
                raise ValueError("Invalid screening score")
            if classification.get("notes_quality") not in ("thin", "substantial") or not isinstance(
                classification.get("rationale"), str
            ):
                raise ValueError("Invalid screening rationale")
            topics = classification.get("topics")
            if not isinstance(topics, dict) or any(
                not isinstance(name, str)
                or not isinstance(terms, list)
                or any(not isinstance(term, str) for term in terms)
                for name, terms in topics.items()
            ):
                raise ValueError("Invalid persisted topics")
            if not isinstance(classification.get("action_cues"), list) or any(
                not isinstance(term, str) for term in classification["action_cues"]
            ):
                raise ValueError("Invalid persisted action cues")
            if not isinstance(
                record.get("notes" if scope == "episodes" else "description", ""), str
            ):
                raise ValueError("Invalid persisted metadata")
            if scope == "episodes":
                if record.get("feed_id") not in state["feeds"] or not isinstance(
                    record.get("notes"), str
                ):
                    raise ValueError("Invalid episode feed membership")
                for field in ("guid", "enclosure", "metadata_hash"):
                    if not isinstance(record.get(field), str):
                        raise ValueError("Invalid episode identity metadata")
                if not re.fullmatch(r"[0-9a-f]{64}", record["metadata_hash"]):
                    raise ValueError("Invalid episode metadata hash")
                date = record.get("published")
                if date is not None and (
                    isinstance(date, bool)
                    or not isinstance(date, (int, float))
                    or not math.isfinite(date)
                ):
                    raise ValueError("Invalid publication timestamp")
            else:
                date = record.get("fetched_at")
                if date is not None and (
                    isinstance(date, bool)
                    or not isinstance(date, (int, float))
                    or not math.isfinite(date)
                    or date < 0
                ):
                    raise ValueError("Invalid fetch timestamp")
    if not isinstance(state.get("overrides"), dict):
        raise ValueError("Invalid screening overrides")
    for scope in ("feed", "episode"):
        if not isinstance(state["overrides"].get(scope), dict) or any(
            key not in state[scope + "s"] or value not in DECISIONS
            for key, value in state["overrides"][scope].items()
        ):
            raise ValueError("Invalid persisted override")
    return state


def save_state(root, state):
    from syllaro.cli import write_json

    path = state_path(root)
    path.with_suffix(".tmp").touch(mode=0o600)
    path.with_suffix(".tmp").chmod(0o600)
    write_json(path, state)
    path.chmod(0o600)


def effective(state, record, scope, completed=False):
    result = dict(record["classification"])
    override = state["overrides"][scope].get(record["id"])
    if scope == "episode" and completed and not override:
        result.update(
            decision="skip",
            rationale="Already completed in Pocket Casts",
            listening_status="completed",
        )
        return result
    if scope == "episode" and not override:
        feed_override = state["overrides"]["feed"].get(record["feed_id"])
        if feed_override in ("skip", "review") or (
            feed_override == "process" and result["notes_quality"] != "thin"
        ):
            override = feed_override
    if override:
        result.update(decision=override, rationale="Manual preference", overridden=True)
    return result


def scan(root, profile, feed_limit=20, episode_limit=5, timeout=15, refresh=False):
    profile = validate_profile(profile)
    if (
        not 1 <= feed_limit <= 1000
        or not 1 <= episode_limit <= 100
        or not math.isfinite(timeout)
        or not 0 < timeout <= 60
    ):
        raise ValueError("Invalid screening limits")
    state = load_state(root)
    subscriptions = [f for f in read_registry(root)["feeds"] if f["enabled"]]
    selected = subscriptions[:feed_limit]
    report: dict[str, Any] = {
        "selected": len(selected),
        "unselected": max(0, len(subscriptions) - len(selected)),
        "fetched": 0,
        "cached": 0,
        "failed": 0,
        "errors": [],
        "episodes_queued": 0,
    }

    def request(feed):
        previous = state["feeds"].get(feed["id"], {})
        if (
            not refresh
            and previous.get("fetched_at", 0) > time.time() - 3600
            and not previous.get("error")
        ):
            return feed, "cache", {}, None
        try:
            raw, validators = fetch_metadata(feed["url"], previous, timeout)
            metadata = parse_metadata(raw, feed["id"], episode_limit) if raw is not None else None
            return feed, metadata, validators, None
        except Exception as error:
            # Exception strings can contain credential-bearing URLs; whitelist codes.
            message = str(error)
            code = (
                message
                if isinstance(error, ValueError)
                and (message in ERROR_CODES or re.fullmatch(r"http_[0-9]{3}", message))
                else "metadata_fetch_or_parse_failed"
            )
            return feed, None, {}, code

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(request, feed) for feed in selected]
        for number, future in enumerate(concurrent.futures.as_completed(futures), 1):
            subscription, metadata, validators, error = future.result()
            ident = subscription["id"]
            previous = state["feeds"].get(ident, {})
            record = dict(previous, id=ident, title=subscription["title"])
            if error:
                record["error"] = error
                report["failed"] += 1
                report["errors"].append({"id": ident, "error": error})
            else:
                record.pop("error", None)
                record.update(validators)
                if metadata != "cache":
                    record["fetched_at"] = time.time()
                if isinstance(metadata, tuple):
                    feed_metadata, episodes = metadata
                    record.update(description=feed_metadata["description"])
                    for episode in episodes:
                        episode["classification"] = classify(
                            episode["title"], episode["notes"], profile
                        )
                        state["episodes"][episode["id"]] = episode
                    report["fetched"] += 1
                else:
                    report["cached"] += 1
            record["classification"] = classify(
                record["title"], record.get("description", ""), profile, feed=True
            )
            state["feeds"][ident] = record
            if number % 10 == 0:
                save_state(root, state)
    # Re-score stored metadata when preferences change, retaining manual overrides.
    for feed in state["feeds"].values():
        feed["classification"] = classify(
            feed["title"], feed.get("description", ""), profile, feed=True
        )
    duplicates: dict[str, str] = {}
    for episode in state["episodes"].values():
        episode["classification"] = classify(episode["title"], episode["notes"], profile)
        if not episode.get("enclosure"):
            episode["classification"].update(
                decision="review", rationale="No enclosure advertised in feed metadata"
            )
        signature = episode["metadata_hash"]
        if signature in duplicates and len(episode["notes"].split()) >= 30:
            episode["classification"].update(
                decision="skip",
                rationale="Duplicate metadata already indexed",
                duplicate_of=duplicates[signature],
            )
        else:
            duplicates[signature] = episode["id"]
    state["profile_hash"] = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
    state["last_scan"] = report
    save_state(root, state)
    return report


def ranked(root, limit=20, decision=None, query=None, scope="episode", include_listened=False):
    if (
        not 1 <= limit <= 10000
        or scope not in ("feed", "episode")
        or (decision and decision not in DECISIONS)
    ):
        raise ValueError("Invalid review options")
    state = load_state(root)
    from syllaro.listening import is_completed, load

    listening = load(root)
    completed_keys = set(listening["completed"])
    completed_metadata = set(listening.get("completed_metadata", []))
    result = []
    for record in state[scope + "s"].values():
        completed = scope == "episode" and is_completed(record, completed_keys, completed_metadata)
        explicit = state["overrides"]["episode"].get(record["id"]) if scope == "episode" else None
        if (
            completed
            and not include_listened
            and decision != "skip"
            and explicit not in ("process", "review")
        ):
            continue
        classification = effective(state, record, scope, completed)
        if scope == "episode":
            classification["listening_status"] = "completed" if completed else "unknown"
        if decision and classification["decision"] != decision:
            continue
        if (
            query
            and query.casefold()
            not in (
                record["title"] + " " + record.get("notes", record.get("description", ""))
            ).casefold()
        ):
            continue
        row = {
            "id": record["id"],
            "title": re.sub(r"https?://\S+", "[link]", record["title"]),
            **classification,
        }
        parent = state["feeds"][record.get("feed_id", record["id"])]
        if parent.get("sampled_prefix"):
            row["metadata_scope"] = "bounded prefix; publisher order, not guaranteed newest"
        if scope == "episode":
            row.update(
                feed_id=record["feed_id"],
                feed_title=re.sub(
                    r"https?://\S+", "[link]", state["feeds"][record["feed_id"]]["title"]
                ),
                published=record["published"],
                has_enclosure=bool(record.get("enclosure")),
            )
        if parent.get("error"):
            row["metadata_status"] = "fetch_failed; cached evidence may be stale"
        result.append(row)
    order = {"process": 0, "review": 1, "skip": 2}
    result.sort(key=lambda row: (order[row["decision"]], -row["score"], row["id"]))
    return result[:limit]


def override(root, ident, decision, scope="episode"):
    state = load_state(root)
    if (
        scope not in ("feed", "episode")
        or ident not in state[scope + "s"]
        or decision not in (*DECISIONS, "auto")
    ):
        raise ValueError("Invalid screening override")
    if decision == "auto":
        state["overrides"][scope].pop(ident, None)
    else:
        state["overrides"][scope][ident] = decision
    save_state(root, state)
