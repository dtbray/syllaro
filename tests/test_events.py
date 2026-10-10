# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from syllaro.cli import write_json
from syllaro.dashboard.events import QueueEvents


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "queue"
        self.root.mkdir()
        self.hub = QueueEvents({"main": self.root})
        self.addCleanup(self.hub.close)
        self.stream = self.hub.stream()
        self.addAsyncCleanup(self.close_stream, self.stream)
        first = await anext(self.stream)
        self.assertIn('"reset":true', first)

    async def close_stream(self, stream):
        await stream.aclose()

    async def receive(self):
        event = await asyncio.wait_for(anext(self.stream), 2)
        return json.loads(event.split("data: ", 1)[1])

    async def test_atomic_external_write_and_delete(self):
        write_json(self.root / "example.json", {"status": "running"})
        message = await self.receive()
        self.assertEqual(
            message["changes"], [{"queue": "main", "id": "example", "artifact": False}]
        )
        (self.root / "example.json").unlink()
        self.assertEqual((await self.receive())["changes"][0]["id"], "example")

    async def test_new_artifact_directory_and_atomic_replacement(self):
        directory = self.root / "example"
        directory.mkdir()
        await self.receive()  # discovery subscribes to the new directory
        temporary = directory / "text.tmp"
        temporary.write_text("Synthetic evidence")
        temporary.replace(directory / "transcript.txt")
        self.assertEqual(
            (await self.receive())["changes"],
            [{"queue": "main", "id": "example", "artifact": True}],
        )

    async def test_slow_client_coalesces_to_resync_and_unsubscribes(self):
        write_json(self.root / "first.json", {})
        await asyncio.sleep(0.1)
        write_json(self.root / "second.json", {})
        await asyncio.sleep(0.1)
        self.assertTrue((await self.receive())["reset"])
        await self.stream.aclose()
        self.assertEqual(len(self.hub.clients), 0)

    async def test_missing_root_is_detected_when_created(self):
        other = self.root / "nested" / "new"
        hub = QueueEvents({"other": other})
        self.addCleanup(hub.close)
        stream = hub.stream()
        self.addAsyncCleanup(self.close_stream, stream)
        await anext(stream)
        other.mkdir(parents=True)
        write_json(other / "new.json", {})
        self.assertIn('"reset": true', await asyncio.wait_for(anext(stream), 2))
        write_json(other / "next.json", {})
        self.assertIn('"id": "next"', await asyncio.wait_for(anext(stream), 2))

    async def test_open_file_does_not_notify_until_closed(self):
        file = (self.root / "example.json").open("w")
        try:
            file.write("{}")
            file.flush()
            waiting = asyncio.create_task(self.receive())
            await asyncio.sleep(0.1)
            self.assertFalse(waiting.done())
        finally:
            file.close()
        self.assertEqual((await waiting)["changes"][0]["id"], "example")
