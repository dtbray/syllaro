# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read-only Pocket Casts subscription adapter; credentials never enter the registry."""

import json
import math
import os
import sqlite3
import stat
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlencode

from syllaro.feeds import feed_id, feed_url, import_records

API = "https://api.pocketcasts.com"
EXPORT = "https://refresh.pocketcasts.com/import/export_feed_urls"
MAX_BYTES = 5 * 1024 * 1024


class PocketCastsError(ValueError):
    """Redacted connector failure safe for CLI output."""


def validate_token(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 16384
        or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value)
    ):
        raise PocketCastsError("Pocket Casts session token is missing or invalid")
    return value


def file_token(path):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise PocketCastsError("Token file must not be a symlink")
    try:
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise PocketCastsError("Token file must be private (chmod 600)")
            raw = stream.read(16385)
        return validate_token(raw.decode("ascii").strip())
    except (OSError, UnicodeError):
        raise PocketCastsError("Cannot read Pocket Casts token file") from None


def firefox_token(profile):
    """Read only Pocket Casts cookie/localStorage token keys from an explicit profile."""
    profile = Path(profile).expanduser()
    candidates = set()
    sources = [(profile / "cookies.sqlite", "cookies")]
    storage = profile / "storage/default"
    if storage.exists():
        sources += [
            (p / "ls/data.sqlite", "storage")
            for p in storage.iterdir()
            if p.name.split("^", 1)[0] == "https+++play.pocketcasts.com"
        ]
    for path, kind in sources:
        if not path.is_file():
            continue
        try:
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
                if kind == "cookies":
                    rows = db.execute(
                        "SELECT value FROM moz_cookies WHERE host IN "
                        "('play.pocketcasts.com', '.pocketcasts.com', 'api.pocketcasts.com') "
                        "AND name IN ('token', 'accessToken', 'pocketcasts_token')"
                    )
                else:
                    rows = db.execute(
                        "SELECT value, compression_type FROM data WHERE key IN "
                        "('token', 'accessToken', 'pocketcasts_token')"
                    )
                for row in rows:
                    if kind == "storage" and row[1] != 0:
                        continue  # Firefox compressed values need an explicitly supplied token.
                    value = row[0]
                    if isinstance(value, bytes):
                        value = value.decode("utf-8")
                    if value.startswith('"'):
                        value = json.loads(value)
                    candidates.add(validate_token(value))
        except (sqlite3.Error, UnicodeError, ValueError):
            raise PocketCastsError("Cannot read supported Pocket Casts browser session") from None
    if len(candidates) != 1:
        raise PocketCastsError("No unique supported Pocket Casts session; use a private token file")
    return candidates.pop()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PocketCastsError("Pocket Casts redirects are disabled")


class Client:
    def __init__(self, token, timeout=15):
        self.token = validate_token(token)
        if not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise PocketCastsError("Pocket Casts timeout must be between 0 and 60 seconds")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, ident=None):
        # Fixed hosts and endpoints only. Never send the account token to public metadata hosts.
        if ident is None:
            url, data = API + "/user/podcast/list", b'{"v":1}'
            headers = {"Authorization": "Bearer " + self.token}
        else:
            try:
                identifiers = [str(uuid.UUID(i)) for i in ident]
                if not 1 <= len(identifiers) <= 10000:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise PocketCastsError("Invalid Pocket Casts podcast identities") from None
            url = EXPORT
            data = urlencode({"uuids": ",".join(identifiers)}).encode()
            headers = {}
        headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json"
                if ident is None
                else "application/x-www-form-urlencoded",
            }
        )
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.headers.get_content_type() != "application/json":
                    raise PocketCastsError("Pocket Casts returned unexpected content")
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise PocketCastsError("Pocket Casts metadata exceeds the size limit")
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise PocketCastsError("Invalid Pocket Casts response")
                return value
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise PocketCastsError("Pocket Casts session expired or access denied") from None
            raise PocketCastsError(f"Pocket Casts request failed (HTTP {error.code})") from None
        except (OSError, ValueError) as error:
            if isinstance(error, PocketCastsError):
                raise
            raise PocketCastsError("Pocket Casts metadata request failed") from None

    def subscriptions(self):
        value = self.request()
        items = value.get("podcasts")
        if (
            not isinstance(items, list)
            or len(items) > 10000
            or value.get("hasMore")
            or value.get("nextPage")
        ):
            raise PocketCastsError("Unsupported or incomplete Pocket Casts subscription response")
        identifiers = [item.get("uuid") for item in items if isinstance(item, dict)]
        exported = self.request(identifiers) if identifiers else {"status": "ok", "result": {}}
        if exported.get("status") != "ok":
            raise PocketCastsError("Pocket Casts feed export failed")
        mapping = exported.get("result")
        if isinstance(mapping, str):
            try:
                mapping = json.loads(mapping)
            except ValueError:
                raise PocketCastsError("Invalid Pocket Casts feed export") from None
        if not isinstance(mapping, dict):
            raise PocketCastsError("Invalid Pocket Casts feed export")
        records, errors, seen = [], [], set()
        for index, item in enumerate(items, 1):
            try:
                if not isinstance(item, dict):
                    raise PocketCastsError("Invalid Pocket Casts subscription")
                # The list's `url` is the show website, never the RSS source.
                url = mapping.get(item.get("uuid"))
                title = item.get("title")
                url = feed_url(url)
                if not isinstance(title, str) or not title.strip():
                    raise PocketCastsError("Missing Pocket Casts subscription title")
                if url in seen:
                    continue
                seen.add(url)
                records.append(
                    {
                        "id": feed_id(url),
                        "url": url,
                        "title": title,
                        "enabled": True,
                        "categories": ["Pocket Casts"],
                    }
                )
            except ValueError as error:
                # Neither account data, server bodies nor feed URLs appear in diagnostics.
                message = (
                    str(error) if isinstance(error, PocketCastsError) else "Invalid feed metadata"
                )
                errors.append({"subscription": index, "error": message})
        return records, errors


def login(email, password, timeout=15):
    """Explicit credential login; token and password remain in process memory."""
    if not isinstance(email, str) or not email or not isinstance(password, str) or not password:
        raise PocketCastsError(
            "Set POCKETCASTS_EMAIL and POCKETCASTS_PASSWORD through your secret manager"
        )
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise PocketCastsError("Pocket Casts timeout must be between 0 and 60 seconds")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    payload = json.dumps({"email": email, "password": password, "scope": "webplayer"}).encode()
    request = urllib.request.Request(
        API + "/user/login",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.headers.get_content_type() != "application/json":
                raise PocketCastsError("Pocket Casts returned unexpected login content")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise PocketCastsError("Pocket Casts login response exceeds the size limit")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise PocketCastsError("Invalid Pocket Casts login response")
            return validate_token(value.get("token"))
    except (OSError, ValueError) as error:
        if isinstance(error, PocketCastsError):
            raise
        raise PocketCastsError(
            "Pocket Casts login failed; check credentials or endpoint compatibility"
        ) from None


def sync(root, client):
    records, errors = client.subscriptions()
    report = import_records(root, records, errors)
    report["source"] = "pocketcasts"
    report["account_writes"] = 0
    return report
