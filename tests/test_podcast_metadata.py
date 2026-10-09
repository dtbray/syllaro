# SPDX-License-Identifier: AGPL-3.0-or-later
import copy
import gzip
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from syllaro import feeds, listening, pocketcasts, screening
from syllaro import podcast_metadata as metadata

PODCAST = "12345678-1234-1234-1234-123456789abc"
EPISODE = "87654321-4321-4321-4321-cba987654321"
NOTES = "A practical guide to Python automation. " + "Implementation workflow and testing. " * 20


class PodcastMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.feed = feeds.feed_id("https://example.org/feed")
        feeds.import_records(
            self.root,
            [
                {
                    "id": self.feed,
                    "url": "https://example.org/feed",
                    "title": "Show",
                    "enabled": True,
                    "categories": [],
                }
            ],
        )
        _, episodes = screening.parse_metadata(
            (
                """<rss><channel><title>Show</title><item><title>Python guide</title><guid>"""
                + EPISODE
                + """</guid><pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate><description>Python</description><enclosure url="https://example.org/audio.mp3" /></item></channel></rss>"""
            ).encode(),
            self.feed,
            5,
        )
        self.row = episodes[0]
        self.ident = self.row["id"]
        self.row["classification"] = screening.classify(
            self.row["title"], self.row["notes"], screening.DEFAULT_PROFILE
        )
        screening.save_state(
            self.root,
            {
                "version": 1,
                "feeds": {
                    self.feed: {
                        "id": self.feed,
                        "title": "Show",
                        "classification": screening.classify(
                            "Show", "", screening.DEFAULT_PROFILE, feed=True
                        ),
                    }
                },
                "episodes": {self.ident: self.row},
                "overrides": {"feed": {}, "episode": {}},
            },
        )
        self.client = Mock(timeout=5, podcast_feeds={PODCAST: self.feed})
        self.client.signals.side_effect = lambda kind: (
            {"bookmarks": []} if kind == "bookmarks" else {"episodes": []}
        )

    def tearDown(self):
        self.temp.cleanup()

    def fetch(self, url, timeout):
        if "/podcast/full/" in url:
            return {
                "podcast": {
                    "uuid": PODCAST,
                    "episodes": [
                        {
                            "uuid": EPISODE,
                            "url": self.row["enclosure"],
                            "title": self.row["title"],
                            "published": "2026-10-09T12:00:00Z",
                        }
                    ],
                }
            }
        if "/show_notes/full/" in url:
            return {"url": "https://example.org/notes.json"}
        if url.endswith("notes.json"):
            return {
                "podcast": {
                    "uuid": PODCAST,
                    "episodes": [
                        {
                            "uuid": EPISODE,
                            "show_notes": NOTES,
                            "chapters_url": "https://example.org/chapters.json",
                            "transcripts": [
                                {
                                    "url": "https://example.org/transcript.vtt",
                                    "type": "text/vtt",
                                    "language": "en",
                                }
                            ],
                        }
                    ],
                }
            }
        return {"chapters": [{"startTime": 20, "endTime": 30, "title": "Deploy"}]}

    def enrich(self):
        with patch.object(metadata, "get_public", side_effect=self.fetch):
            return metadata.enrich(self.root, self.client, screening.DEFAULT_PROFILE)

    def test_notes_chapters_transcripts_and_interest_ranking_without_queueing(self):
        self.client.signals.side_effect = lambda kind: (
            {"bookmarks": []}
            if kind == "bookmarks"
            else {"episodes": [{"uuid": EPISODE, "podcastUuid": PODCAST}]}
        )
        report = self.enrich()
        self.assertEqual(report["metadata_failed"], 0)
        self.assertEqual(report["transcript_candidates"], 1)
        self.assertEqual(list(self.root.glob("*.json")), [])
        row = screening.ranked(self.root)[0]
        self.assertEqual(row["decision"], "process")
        self.assertTrue(row["interest_signals"]["starred"])
        self.assertTrue(row["interest_signals"]["up_next"])
        self.assertEqual(row["chapters"][0]["start"], 20)
        self.assertNotIn("transcript.vtt", json.dumps(row))
        self.assertEqual(metadata.path(self.root).stat().st_mode & 0o777, 0o600)
        catalog = screening.load_state(self.root)
        catalog["episodes"][self.ident].update(notes="Python", enclosure="")
        screening.save_state(self.root, catalog)
        self.enrich()
        self.assertEqual(screening.ranked(self.root)[0]["decision"], "review")

    def test_bookmark_resurfaces_completed_for_review_but_star_queue_do_not(self):
        listening.update(
            self.root,
            [{"playingStatus": 3, "podcastUuid": PODCAST, "url": self.row["enclosure"]}],
            {PODCAST: self.feed},
        )
        self.enrich()
        self.assertEqual(screening.ranked(self.root), [])
        self.client.signals.side_effect = lambda kind: (
            {
                "bookmarks": [
                    {
                        "episode_uuid": EPISODE,
                        "podcast_uuid": PODCAST,
                        "time": 42,
                        "title": "Check this",
                        "passage": "saved evidence",
                    }
                ]
            }
            if kind == "bookmarks"
            else {"episodes": [{"uuid": EPISODE, "podcastUuid": PODCAST}]}
        )
        self.enrich()
        row = screening.ranked(self.root)[0]
        self.assertEqual(row["decision"], "review")
        self.assertEqual(row["listening_status"], "completed")
        self.assertEqual(row["bookmarks"][0]["time"], 42)
        screening.override(self.root, self.ident, "skip")
        self.assertEqual(screening.ranked(self.root), [])
        screening.override(self.root, self.ident, "auto")
        screening.override(self.root, self.feed, "skip", scope="feed")
        self.assertEqual(screening.ranked(self.root), [])

    def test_failed_sources_keep_cache_without_ranking_or_bookmark_exception(self):
        self.enrich()
        self.client.signals.side_effect = ValueError("private server data")
        with patch.object(metadata, "get_public", side_effect=ValueError("private url")):
            report = metadata.enrich(self.root, self.client, screening.DEFAULT_PROFILE)
        self.assertEqual(report["metadata_failed"], 1)
        self.assertNotIn("private", json.dumps(report))
        self.assertEqual(report["indexed_metadata"], 1)
        self.assertFalse(screening.ranked(self.root)[0]["interest_signals"]["starred"])

    def test_transcript_export_preserves_cues_without_marking_worker_complete(self):
        self.enrich()
        content = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Speaker 1>Check backups\n"
        with patch.object(metadata, "get_public", return_value=(content, "text/vtt")):
            report = metadata.fetch_transcript(self.root, self.ident)
        self.assertTrue(report["has_cue_timestamps"])
        self.assertFalse(report["asr_replaced"])
        self.assertFalse(report["diarization_replaced"])
        target = Path(report["artifact"])
        self.assertEqual(json.loads(target.read_text())["content"], content)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            metadata.fetch_transcript(self.root, "../bad")
        with self.assertRaises(ValueError):
            metadata.fetch_transcript(self.root, self.ident, 1)

    def test_network_bounds_gzip_and_no_authorization_on_public_hosts(self):
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["Content-Encoding"] = "gzip"
        response = Mock(headers=headers)
        response.read.return_value = gzip.compress(b'{"url":"https://example.org/notes"}')
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = context
        with (
            patch.object(metadata, "checked_url"),
            patch.object(metadata.urllib.request, "build_opener", return_value=opener),
        ):
            self.assertIn("url", metadata.get_public("https://example.org/notes"))
            self.assertIsNone(opener.open.call_args.args[0].get_header("Authorization"))
            with patch.object(metadata, "MAX_BYTES", 128):
                response.read.return_value = gzip.compress(b" " * 1000)
                with self.assertRaises(ValueError):
                    metadata.get_public("https://example.org/notes")
        for url in (
            "http://example.org/notes",
            "https://user:secret@example.org/notes",
            "file:///tmp/x",
        ):
            with self.assertRaises(ValueError):
                metadata.public_url(url)

    def test_up_next_payload_has_no_changes_and_signal_shape_validation(self):
        headers = Message()
        headers["Content-Type"] = "application/json"
        response = Mock(headers=headers)
        response.read.return_value = b'{"episodes":[]}'
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        client = pocketcasts.Client("secret")
        client.opener.open = Mock(return_value=context)
        client.signals("up_next")
        request = client.opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data)["upNext"], {"serverModified": 0, "changes": []})
        parsed = metadata.normalize_signals(
            "up_next",
            {
                "order": [EPISODE],
                "episodes": {
                    EPISODE: {
                        "podcast": PODCAST,
                        "title": "Episode",
                        "url": "https://example.org/audio.mp3",
                    }
                },
            },
        )
        self.assertTrue(parsed[PODCAST + "/" + EPISODE]["up_next"])
        for value in (
            {},
            {"order": [EPISODE], "episodes": {}},
            {"order": [[], []], "episodes": {}},
        ):
            with self.assertRaises(ValueError):
                metadata.normalize_signals("up_next", value)
        with self.assertRaises(ValueError):
            metadata.assets({"chapters": [{"startTime": float("nan")}]})

    def test_enriched_notes_survive_rss_refresh_and_chapters_are_searchable(self):
        self.enrich()
        raw = (
            "<rss><channel><title>Show</title><item><title>Python guide</title><guid>"
            + EPISODE
            + "<"
            + '/guid><description>Python</description><enclosure url="https://example.org/audio.mp3" /></item></channel></rss>'
        ).encode()
        with patch.object(screening, "fetch_metadata", return_value=(raw, {})):
            screening.scan(self.root, screening.DEFAULT_PROFILE, refresh=True)
        self.assertEqual(
            screening.load_state(self.root)["episodes"][self.ident]["notes"], NOTES.strip()
        )
        self.assertEqual(screening.ranked(self.root, query="Deploy")[0]["id"], self.ident)

    def test_corrupt_state_and_symlinks_are_rejected(self):
        self.enrich()
        state = metadata.load(self.root)
        broken = copy.deepcopy(state)
        broken["episodes"][self.ident]["transcripts"][0]["url"] = "http://localhost/audio"
        metadata.path(self.root).write_text(json.dumps(broken))
        with self.assertRaises(ValueError):
            metadata.load(self.root)
        metadata.path(self.root).unlink()
        metadata.path(self.root).symlink_to(self.root / "elsewhere")
        with self.assertRaises(ValueError):
            metadata.load(self.root)


if __name__ == "__main__":
    unittest.main()
