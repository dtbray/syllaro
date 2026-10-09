# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from syllaro import pocketcasts
from syllaro.feeds import read_registry


class PocketCastsTests(unittest.TestCase):
    def test_merge_is_read_only_deduplicated_and_preserves_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = pocketcasts.Client("secret")
            items = {
                "podcasts": [
                    {"uuid": "a", "title": "Technical show", "url": "https://website.example"},
                    {"uuid": "b", "title": "Duplicate"},
                    {"uuid": "c", "title": "Invalid"},
                ]
            }
            export = {
                "status": "ok",
                "result": {
                    "a": "https://example.org/feed",
                    "b": "https://example.org/feed",
                    "c": "secret-invalid-url",
                },
            }
            client.request = Mock(side_effect=lambda ident=None: items if ident is None else export)
            report = pocketcasts.sync(root, client)
            self.assertEqual(
                (report["added"], report["skipped"], report["episodes_queued"]), (1, 1, 0)
            )
            self.assertNotIn("secret", json.dumps(report))
            path = root / "feeds/subscriptions.json"
            registry = read_registry(root)
            registry["feeds"][0]["enabled"] = False
            path.write_text(json.dumps(registry))
            self.assertEqual(pocketcasts.sync(root, client)["existing"], 1)
            self.assertFalse(read_registry(root)["feeds"][0]["enabled"])
            self.assertEqual(list(root.glob("*.json")), [])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_auth_failure_and_unknown_shape_leave_registry_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = pocketcasts.Client("secret")
            for result in ({}, {"podcasts": [], "hasMore": True}):
                client.request = Mock(return_value=result)
                with self.assertRaises(pocketcasts.PocketCastsError):
                    pocketcasts.sync(root, client)
                self.assertFalse((root / "feeds").exists())
            client.request = Mock(side_effect=pocketcasts.PocketCastsError("expired"))
            with self.assertRaises(pocketcasts.PocketCastsError):
                pocketcasts.sync(root, client)
            self.assertFalse((root / "feeds").exists())

    def test_transport_scopes_token_caps_body_and_redacts_failures(self):
        client = pocketcasts.Client("private-secret")
        headers = Message()
        headers["Content-Type"] = "application/json"
        response = Mock(headers=headers)
        response.read.return_value = b'{"podcasts":[]}'
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        client.opener.open = Mock(return_value=context)
        client.request()
        req = client.opener.open.call_args.args[0]
        self.assertEqual(req.full_url, pocketcasts.API + "/user/podcast/list")
        self.assertEqual(req.get_header("Authorization"), "Bearer private-secret")
        client.request(["00000000-0000-0000-0000-000000000001"])
        self.assertIsNone(client.opener.open.call_args.args[0].get_header("Authorization"))
        response.read.return_value = b"x" * (pocketcasts.MAX_BYTES + 1)
        with self.assertRaisesRegex(pocketcasts.PocketCastsError, "size limit"):
            client.request()
        client.opener.open.side_effect = urllib.error.HTTPError(
            "https://secret", 401, "secret", {}, None
        )
        with self.assertRaisesRegex(pocketcasts.PocketCastsError, "expired") as caught:
            client.request()
        self.assertNotIn("secret", str(caught.exception))
        with self.assertRaisesRegex(pocketcasts.PocketCastsError, "redirects"):
            pocketcasts.NoRedirect().redirect_request(
                req, None, 302, "", {}, "https://other.example"
            )

    def test_explicit_firefox_profile_reads_only_known_session_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            with sqlite3.connect(profile / "cookies.sqlite") as db:
                db.execute("CREATE TABLE moz_cookies(host TEXT, name TEXT, value TEXT)")
                db.executemany(
                    "INSERT INTO moz_cookies VALUES(?,?,?)",
                    [
                        ("play.pocketcasts.com", "token", "known-token"),
                        ("evil-pocketcasts.com", "token", "other-secret"),
                        ("play.pocketcasts.com", "unrelated", "other-secret"),
                    ],
                )
            self.assertEqual(pocketcasts.firefox_token(profile), "known-token")
            token = profile / "session.txt"
            token.write_text("known-token\n")
            token.chmod(0o600)
            self.assertEqual(pocketcasts.file_token(token), "known-token")
            token.chmod(0o644)
            with self.assertRaisesRegex(pocketcasts.PocketCastsError, "private"):
                pocketcasts.file_token(token)
            for invalid in ("a\nb", "", "é"):
                with self.assertRaises(pocketcasts.PocketCastsError):
                    pocketcasts.validate_token(invalid)

    def test_missing_feed_is_resolved_by_uuid_without_audio_request(self):
        client = pocketcasts.Client("secret")
        client.request = Mock(
            side_effect=[
                {"podcasts": [{"uuid": "id", "title": "Show"}]},
                {"status": "ok", "result": json.dumps({"id": "https://example.org/rss"})},
            ]
        )
        records, errors = client.subscriptions()
        self.assertEqual(len(records), 1)
        self.assertEqual(errors, [])
        self.assertEqual(client.request.call_args.args, (["id"],))
        with patch.object(pocketcasts.Client, "request", return_value={"podcasts": []}):
            self.assertEqual(pocketcasts.Client("secret").subscriptions(), ([], []))

    def test_login_keeps_credentials_in_memory_and_redacts_server_failure(self):
        headers = Message()
        headers["Content-Type"] = "application/json"
        response = Mock(headers=headers)
        response.read.return_value = b'{"token":"session-only"}'
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = context
        with patch("syllaro.pocketcasts.urllib.request.build_opener", return_value=opener):
            self.assertEqual(
                pocketcasts.login("account@example.org", "password-only"), "session-only"
            )
            request = opener.open.call_args.args[0]
            self.assertIsNone(request.get_header("Authorization"))
            self.assertEqual(request.full_url, pocketcasts.API + "/user/login")
            self.assertEqual(json.loads(request.data)["password"], "password-only")
            opener.open.side_effect = OSError("password-only")
            with self.assertRaises(pocketcasts.PocketCastsError) as caught:
                pocketcasts.login("account@example.org", "password-only")
            self.assertNotIn("password-only", str(caught.exception))
