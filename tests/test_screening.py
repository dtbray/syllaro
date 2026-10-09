# SPDX-License-Identifier: AGPL-3.0-or-later
import copy
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from syllaro import feeds, screening

NOTES = (
    "A practical guide to Python automation and disaster recovery. "
    + "Detailed implementation steps and testing examples. " * 12
)
RSS = (
    '<rss version="2.0"><channel><title>Systems</title><description>Python guides</description>'
    "<item><title>How to automate recovery</title><guid>one</guid>"
    "<pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate>"
    "<description><![CDATA[<p>" + NOTES + "</p><script>steal tokens</script>]]></description>"
    '<enclosure url="https://example.org/audio.mp3?private=opaque" type="audio/mpeg" />'
    "</item><item><title>Thin notes</title><guid>two</guid><description>Python.</description>"
    "</item></channel></rss>"
).encode()


class ScreeningTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        opml = self.root / "input.opml"
        opml.write_text(
            '<opml><body><outline text="Systems" xmlUrl="https://example.org/feed" /></body></opml>'
        )
        feeds.import_opml(self.root, opml)
        self.ident = feeds.read_registry(self.root)["feeds"][0]["id"]

    def tearDown(self):
        self.directory.cleanup()

    def test_rss_and_atom_parse_notes_without_following_links(self):
        _, items = screening.parse_metadata(RSS, self.ident, 1)
        self.assertEqual(len(items), 1)
        self.assertNotIn("steal", items[0]["notes"])
        self.assertIsNotNone(items[0]["published"])
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><entry><id>a</id><title>Episode</title><summary>Useful notes</summary><content src="https://example.org/external"/><link rel="enclosure" href="https://example.org/audio.mp3"/></entry></feed>'
        with patch.object(urllib.request, "urlopen", side_effect=AssertionError("No network")):
            _, entries = screening.parse_metadata(atom, self.ident, 5)
        self.assertEqual(entries[0]["notes"], "Useful notes")
        self.assertTrue(entries[0]["enclosure"])
        for raw in [b"<!DOCTYPE rss><rss/>", b"<html/>", b"<rss>"]:
            with self.assertRaises(ValueError):
                screening.parse_metadata(raw, self.ident, 5)

    def test_thin_notes_review_and_keywords_are_uncalibrated_recommendations(self):
        profile = copy.deepcopy(screening.DEFAULT_PROFILE)
        self.assertEqual(
            screening.classify("Python guide", "Python", profile)["decision"], "review"
        )
        self.assertEqual(screening.classify("Python guide", NOTES, profile)["decision"], "process")
        profile["exclude_terms"] = ["sports"]
        self.assertEqual(screening.classify("Sports", "sports " * 40, profile)["decision"], "skip")
        self.assertEqual(
            screening.classify("Other", "unrelated " * 40, profile)["decision"], "review"
        )

    def test_scan_is_metadata_only_cache_and_overrides_survive_refresh(self):
        with patch.object(screening, "fetch_metadata", return_value=(RSS, {"etag": "v1"})) as fetch:
            report = screening.scan(self.root, screening.DEFAULT_PROFILE)
        self.assertEqual(report["episodes_queued"], 0)
        self.assertEqual(fetch.call_args.args[0], "https://example.org/feed")
        rows = screening.ranked(self.root, query="implementation")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("opaque", json.dumps(rows))
        self.assertFalse(list(self.root.glob("*.json")))
        self.assertFalse(list(self.root.rglob("*.mp3")))
        ident = rows[0]["id"]
        screening.override(self.root, ident, "skip")
        with patch.object(screening, "fetch_metadata", side_effect=AssertionError("Use cache")):
            screening.scan(self.root, screening.DEFAULT_PROFILE)
        self.assertEqual(screening.ranked(self.root, decision="skip")[0]["id"], ident)
        with patch.object(screening, "fetch_metadata", return_value=(RSS, {"etag": "v2"})):
            screening.scan(self.root, screening.DEFAULT_PROFILE, refresh=True)
        self.assertEqual(screening.ranked(self.root, decision="skip")[0]["id"], ident)
        screening.override(self.root, ident, "auto")
        self.assertEqual(screening.ranked(self.root)[0]["decision"], "process")
        path = screening.state_path(self.root)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        screening.override(self.root, self.ident, "skip", scope="feed")
        self.assertTrue(all(r["decision"] == "skip" for r in screening.ranked(self.root)))
        screening.override(self.root, ident, "process")
        self.assertEqual(screening.ranked(self.root)[0]["decision"], "process")
        data = json.loads(path.read_text())
        data["episodes"][ident]["published"] = float("nan")
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "publication"):
            screening.load_state(self.root)

    def test_failure_is_reported_without_credential_leak_or_losing_cached_episodes(self):
        with patch.object(screening, "fetch_metadata", return_value=(RSS, {})):
            screening.scan(self.root, screening.DEFAULT_PROFILE)
        with patch.object(screening, "fetch_metadata", side_effect=ValueError("private_token_123")):
            report = screening.scan(self.root, screening.DEFAULT_PROFILE, refresh=True)
        self.assertEqual(report["failed"], 1)
        self.assertNotIn("private_token", json.dumps(report))
        self.assertEqual(len(screening.ranked(self.root)), 2)
        self.assertIn("metadata_status", screening.ranked(self.root)[0])

    def test_non_public_destination_and_cross_origin_auth_redirect_rejected(self):
        with patch.object(
            screening.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]
        ):
            with self.assertRaisesRegex(ValueError, "non_public"):
                screening.checked_url("https://example.org/feed")
        req = urllib.request.Request(
            "https://example.org/feed",
            headers={"Authorization": "Basic opaque", "If-None-Match": "private"},
        )
        with patch.object(screening, "checked_url", side_effect=urlsplit):
            redirected = screening.MetadataRedirect().redirect_request(
                req, None, 302, "", {}, "https://other.example/feed"
            )
            self.assertIsNone(redirected.get_header("Authorization"))
            self.assertIsNone(redirected.get_header("If-none-match"))
            with self.assertRaisesRegex(ValueError, "unsafe_redirect"):
                screening.MetadataRedirect().redirect_request(
                    req, None, 302, "", {}, "http://example.org/feed"
                )

    def test_audio_response_refused_before_body_and_basic_auth_url_not_forwarded(self):
        headers = Message()
        headers["Content-Type"] = "audio/mpeg"
        response = Mock(headers=headers)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with (
            patch.object(screening, "checked_url", side_effect=urlsplit),
            patch.object(screening.urllib.request, "build_opener", return_value=opener),
        ):
            with self.assertRaisesRegex(ValueError, "non_metadata"):
                screening.fetch_metadata("https://user:secret@example.org/feed", {}, 2)
        request = opener.open.call_args.args[0]
        self.assertNotIn("secret", request.full_url)
        self.assertIsNotNone(request.get_header("Authorization"))
        response.read.assert_not_called()

    def test_conditional_http_cache_and_response_byte_limit(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://example.org/feed", 304, "", {}, None
        )
        previous = {"etag": "v1", "last_modified": "yesterday", "title": "private metadata"}
        with (
            patch.object(screening, "checked_url", side_effect=urlsplit),
            patch.object(screening.urllib.request, "build_opener", return_value=opener),
        ):
            raw, validators = screening.fetch_metadata("https://example.org/feed", previous, 2)
        self.assertIsNone(raw)
        self.assertEqual(validators, {"etag": "v1", "last_modified": "yesterday"})
        self.assertEqual(opener.open.call_args.args[0].get_header("If-none-match"), "v1")
        headers = Message()
        headers["Content-Type"] = "application/xml"
        response = Mock(headers=headers)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"x" * 17
        opener.open.side_effect = None
        opener.open.return_value = response
        with (
            patch.object(screening, "checked_url", side_effect=urlsplit),
            patch.object(screening.urllib.request, "build_opener", return_value=opener),
            patch.object(screening, "MAX_BYTES", 16),
        ):
            with self.assertRaisesRegex(ValueError, "too_large"):
                screening.fetch_metadata("https://example.org/feed", {}, 2)
        response.read.assert_called_once_with(17)
        prefix = RSS.split(b"</item>", 1)[0] + b"</item><item>"
        sampled = screening.sample_prefix(prefix, limit=1)
        _, entries = screening.parse_metadata(sampled, self.ident, 5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "How to automate recovery")


if __name__ == "__main__":
    unittest.main()
