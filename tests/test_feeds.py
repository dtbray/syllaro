# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from syllaro import feeds


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.opml = self.root / "input.opml"

    def tearDown(self):
        self.directory.cleanup()

    def write(self, body):
        self.opml.write_text(f'<opml version="2.0"><body>{body}</body></opml>')

    def test_installed_cli_import_never_queues_or_exposes_urls_and_reports_skips(self):
        config = self.root / "config.txt"
        data = self.root / "data"
        config.write_text(
            json.dumps(
                {
                    "data_dir": str(data),
                    "whisper_model": "small",
                    "cpu_threads": 1,
                    "diarize": False,
                    "chunk_chars": 1000,
                    "http_timeout": 1,
                    "process_timeout": 1,
                }
            )
        )

        def command(*args):
            return subprocess.run(
                [sys.executable, "-I", "-m", "syllaro", "--config", str(config), *args],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=10,
            )

        self.write('<outline text="Podcast" xmlUrl="https://example.org/feed?subscriber=opaque" />')
        first = command("import-opml", str(self.opml))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["added"], 1)
        self.assertEqual(json.loads(first.stdout)["episodes_queued"], 0)
        self.assertEqual(json.loads(command("import-opml", str(self.opml)).stdout)["added"], 0)
        listing = command("feeds")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(json.loads(listing.stdout)[0]["title"], "Podcast")
        self.assertNotIn("opaque", listing.stdout)
        self.assertFalse(list(data.glob("*.json")))
        self.write('<outline text="Invalid" type="rss" />')
        partial = command("import-opml", str(self.opml))
        self.assertNotEqual(partial.returncode, 0)
        self.assertEqual(json.loads(partial.stdout)["skipped"], 1)
        self.assertEqual(len(json.loads(command("feeds").stdout)), 1)

    def test_nested_duplicates_merge_and_reimport_preserves_disabled_state(self):
        self.write(
            '<outline text="Technology"><outline text="Show" type="rss" '
            'xmlUrl="https://example.org/feed?subscriber=opaque" /></outline>'
            '<outline text="Favorites"><outline text="Alias" '
            'xmlUrl="https://example.org/feed?subscriber=opaque" /></outline>'
        )
        report = feeds.import_opml(self.root, self.opml)
        self.assertEqual(
            (report["added"], report["existing"], report["episodes_queued"]), (1, 1, 0)
        )
        registry = feeds.read_registry(self.root)
        self.assertEqual(registry["feeds"][0]["categories"], ["Technology", "Favorites"])
        registry["feeds"][0]["enabled"] = False
        path = self.root / "feeds/subscriptions.json"
        path.write_text(json.dumps(registry))
        self.assertEqual(feeds.import_opml(self.root, self.opml)["added"], 0)
        self.assertFalse(feeds.read_registry(self.root)["feeds"][0]["enabled"])
        self.assertNotIn("opaque", json.dumps(feeds.public_feeds(self.root)))
        self.assertNotIn("example.org", json.dumps(report))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(list(self.root.glob("feed-*.json")))

    def test_invalid_entries_report_partial_import_without_exposing_credentials(self):
        self.write(
            '<outline text="Bad" xmlUrl="ftp://user:secret@example.org/feed" />'
            '<outline text="Missing" type="rss" />'
            '<outline text="Good" xmlUrl="https://example.org/rss" />'
        )
        report = feeds.import_opml(self.root, self.opml)
        self.assertEqual((report["added"], report["skipped"]), (1, 2))
        self.assertNotIn("secret", json.dumps(report))

    def test_authenticated_subscription_is_stored_privately_without_fetching(self):
        self.write('<outline text="Private" xmlUrl="https://user:secret@example.org/feed" />')
        report = feeds.import_opml(self.root, self.opml)
        self.assertEqual(report["added"], 1)
        self.assertNotIn("secret", json.dumps(report))
        self.assertNotIn("secret", json.dumps(feeds.public_feeds(self.root)))
        self.assertIn("secret", feeds.read_registry(self.root)["feeds"][0]["url"])

    def test_malformed_xml_and_entities_do_not_replace_registry(self):
        self.write('<outline text="Good" xmlUrl="https://example.org/rss" />')
        feeds.import_opml(self.root, self.opml)
        path = self.root / "feeds/subscriptions.json"
        before = path.read_bytes()
        for text in ["<opml><body>", '<!DOCTYPE opml [<!ENTITY a "unsafe">]><opml><body /></opml>']:
            self.opml.write_text(text)
            with self.assertRaises(ValueError):
                feeds.import_opml(self.root, self.opml)
            self.assertEqual(path.read_bytes(), before)

    def test_corrupt_registry_or_symlink_is_rejected(self):
        self.write('<outline text="Good" xmlUrl="https://example.org/rss" />')
        feeds.import_opml(self.root, self.opml)
        path = self.root / "feeds/subscriptions.json"
        registry = json.loads(path.read_text())
        registry["feeds"][0]["id"] = "wrong"
        path.write_text(json.dumps(registry))
        with self.assertRaises(ValueError):
            feeds.read_registry(self.root)
        path.unlink()
        outside = self.root / "outside.txt"
        outside.write_text("untouched")
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            feeds.import_opml(self.root, self.opml)
        self.assertEqual(outside.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
