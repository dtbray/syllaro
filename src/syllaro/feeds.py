# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private, durable OPML subscriptions. Importing never fetches or queues episodes."""

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

MAX_OPML_BYTES = 10 * 1024 * 1024


def feed_url(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Feed URL is missing")
    value = value.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid feed URL") from error
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.fragment
        or any(c.isspace() or ord(c) < 32 for c in value)
        or port == 0
    ):
        raise ValueError("Feed URL must be HTTP(S) without whitespace or a fragment")
    return value


def feed_id(url):
    return "feed-" + hashlib.sha256(url.encode()).hexdigest()


def validate_registry(value):
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != 1
    ):
        raise ValueError("Unsupported subscription registry")
    feeds = value.get("feeds")
    if not isinstance(feeds, list):
        raise ValueError("Subscription registry feeds must be a list")
    seen = set()
    for feed in feeds:
        if not isinstance(feed, dict):
            raise ValueError("Invalid subscription record")
        url = feed_url(feed.get("url"))
        if feed.get("id") != feed_id(url) or url in seen:
            raise ValueError("Invalid or duplicate subscription identity")
        seen.add(url)
        if not isinstance(feed.get("title"), str) or not feed["title"].strip():
            raise ValueError("Subscription title is missing")
        if not isinstance(feed.get("enabled"), bool):
            raise ValueError("Subscription enabled must be boolean")
        categories = feed.get("categories")
        if not isinstance(categories, list) or any(
            not isinstance(c, str) or not c.strip() for c in categories
        ):
            raise ValueError("Subscription categories must be strings")
    return value


def registry_path(root):
    directory = root / "feeds"
    if directory.is_symlink():
        raise ValueError("Feed directory must not be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / "subscriptions.json"
    if path.is_symlink() or path.with_suffix(".tmp").is_symlink():
        raise ValueError("Subscription registry must not be a symlink")
    return path


def read_registry(root):
    path = registry_path(root)
    return (
        validate_registry(json.loads(path.read_text()))
        if path.exists()
        else {"version": 1, "feeds": []}
    )


def local_name(element):
    return element.tag.rsplit("}", 1)[-1]


def parse_opml(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_OPML_BYTES + 1)
    if len(raw) > MAX_OPML_BYTES:
        raise ValueError("OPML exceeds the 10 MiB limit")
    try:
        text = raw.decode("utf-8-sig")
        if "<!doctype" in text.lower() or "<!entity" in text.lower():
            raise ValueError("OPML document types and entities are not supported")
        tree = ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as error:
        raise ValueError("OPML must be valid UTF-8 XML") from error
    bodies = [child for child in tree if local_name(child) == "body"]
    if local_name(tree) != "opml" or len(bodies) != 1:
        raise ValueError("Expected an OPML document with one body")
    records = []
    errors: list[dict[str, str | int]] = []

    def visit(parent, categories, depth=0):
        if depth > 64:
            raise ValueError("OPML nesting exceeds the 64-level limit")
        for node in parent:
            if local_name(node) != "outline":
                continue
            title = (node.get("title") or node.get("text") or "Untitled feed").strip()
            url = node.get("xmlUrl")
            if url is not None or node.get("type", "").lower() == "rss":
                try:
                    url = feed_url(url)
                    records.append(
                        {
                            "id": feed_id(url),
                            "url": url,
                            "title": title or "Untitled feed",
                            "enabled": True,
                            "categories": [" / ".join(categories)] if categories else [],
                        }
                    )
                except ValueError as error:
                    # No supplied URL or credential is included in diagnostics.
                    errors.append({"outline": len(records) + len(errors) + 1, "error": str(error)})
                visit(node, categories, depth + 1)
            else:
                visit(node, categories + [title] if title else categories, depth + 1)

    visit(bodies[0], [])
    return records, errors


def import_opml(root, path):
    from syllaro.cli import write_json

    records, errors = parse_opml(path)
    registry = read_registry(root)
    existing = {feed["url"]: feed for feed in registry["feeds"]}
    report = {
        "added": 0,
        "existing": 0,
        "skipped": len(errors),
        "errors": errors,
        "episodes_queued": 0,
    }
    for record in records:
        if record["url"] in existing:
            feed = existing[record["url"]]
            for category in record["categories"]:
                if category not in feed["categories"]:
                    feed["categories"].append(category)
            report["existing"] += 1
        else:
            registry["feeds"].append(record)
            existing[record["url"]] = record
            report["added"] += 1
    path = registry_path(root)
    directory = path.parent
    directory.chmod(0o700)
    # This module is also callable independently of CLI umask configuration.
    descriptor = os.open(path.with_suffix(".tmp"), os.O_CREAT | os.O_WRONLY, 0o600)
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)
    write_json(path, validate_registry(registry))
    path.chmod(0o600)
    report["subscriptions"] = len(registry["feeds"])
    return report


def public_feeds(root):
    return [
        {key: feed[key] for key in ("id", "title", "enabled", "categories")}
        for feed in read_registry(root)["feeds"]
    ]
