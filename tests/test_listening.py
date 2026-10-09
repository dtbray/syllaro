# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syllaro import feeds, listening, screening


class ListeningTests(unittest.TestCase):
    def test_completed_only_is_durable_and_unknown_is_not_unplayed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ident = feeds.feed_id("https://example.org/feed")
            mapping = {"show": ident}
            rows = [
                {
                    "podcastUuid": "show",
                    "url": "https://example.org/completed.mp3",
                    "playingStatus": 3,
                },
                {
                    "podcastUuid": "show",
                    "url": "https://example.org/partial.mp3",
                    "playingStatus": 2,
                    "playedUpTo": 99,
                    "duration": 100,
                },
                {
                    "podcastUuid": "show",
                    "url": "https://example.org/unknown.mp3",
                    "playingStatus": True,
                },
            ]
            report = listening.update(root, rows, mapping)
            self.assertEqual(report["completed_received"], 1)
            self.assertEqual(report["partial_or_unplayed"], 1)
            self.assertEqual(report["unknown_or_unmatched"], 1)
            previous = listening.load(root)["completed"]
            listening.update(root, [], mapping)
            self.assertEqual(listening.load(root)["completed"], previous)
            path = listening.state_path(root)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("example.org", path.read_text())
            self.assertFalse(list(root.glob("*.json")))

    def test_default_exclusion_feed_priority_and_explicit_resurfacing_survive_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opml = root / "input.opml"
            opml.write_text(
                '<opml><body><outline text="Systems" xmlUrl="https://example.org/feed"/></body></opml>'
            )
            feeds.import_opml(root, opml)
            ident = feeds.read_registry(root)["feeds"][0]["id"]
            notes = "A practical Python automation guide with implementation steps. " * 12
            rss = (
                "<rss><channel><title>Systems</title><item><guid>one</guid><title>Python guide</title>"
                "<description>"
                + notes
                + '</description><enclosure url="https://example.org/audio.mp3"/>'
                "</item></channel></rss>"
            ).encode()
            with patch.object(screening, "fetch_metadata", return_value=(rss, {})):
                screening.scan(root, screening.DEFAULT_PROFILE)
            episode = screening.ranked(root)[0]["id"]
            listening.update(
                root,
                [
                    {
                        "podcastUuid": "show",
                        "url": "https://example.org/audio.mp3",
                        "playingStatus": 3,
                    }
                ],
                {"show": ident},
            )
            screening.override(root, ident, "process", scope="feed")
            self.assertEqual(screening.ranked(root), [])
            skipped = screening.ranked(root, decision="skip")
            self.assertEqual(skipped[0]["listening_status"], "completed")
            self.assertEqual(screening.ranked(root, include_listened=True)[0]["decision"], "skip")
            with patch.object(screening, "fetch_metadata", return_value=(rss, {})):
                screening.scan(root, screening.DEFAULT_PROFILE, refresh=True)
            self.assertEqual(screening.ranked(root), [])
            screening.override(root, episode, "process")
            self.assertEqual(screening.ranked(root)[0]["decision"], "process")
            screening.override(root, episode, "auto")
            self.assertEqual(screening.ranked(root), [])

    def test_corrupt_state_and_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = listening.state_path(root)
            for state in (
                {"version": 1, "completed": [{}], "coverage": "unknown"},
                {
                    "version": 1,
                    "completed": [],
                    "coverage": "recent_history_only",
                    "last_sync": float("nan"),
                },
            ):
                path.write_text(json.dumps(state))
                with self.assertRaises(ValueError):
                    listening.load(root)
            path.unlink()
            path.symlink_to(root / "elsewhere")
            with self.assertRaises(ValueError):
                listening.load(root)

    def test_exact_feed_title_and_date_can_match_changed_media_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feed = feeds.feed_id("https://example.org/feed")
            listening.update(
                root,
                [
                    {
                        "podcastUuid": "show",
                        "url": "https://old.example/audio.mp3",
                        "title": "Episode &amp; tools",
                        "published": "2026-10-09T12:00:00Z",
                        "playingStatus": 3,
                    }
                ],
                {"show": feed},
            )
            state = listening.load(root)
            episode = {
                "feed_id": feed,
                "title": "Episode & tools",
                "published": 1791547200.0,
                "enclosure": "https://new.example/audio.mp3",
            }
            self.assertTrue(
                listening.is_completed(
                    episode, set(state["completed"]), set(state["completed_metadata"])
                )
            )
            episode["feed_id"] = feeds.feed_id("https://other.example/rss")
            self.assertFalse(
                listening.is_completed(
                    episode, set(state["completed"]), set(state["completed_metadata"])
                )
            )
