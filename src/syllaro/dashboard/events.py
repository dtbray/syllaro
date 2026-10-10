# SPDX-License-Identifier: AGPL-3.0-or-later
"""Linux filesystem notifications for the optional web adapter."""

import asyncio
import ctypes
import json
import os
import re
import struct
from pathlib import Path

from syllaro.services import ARTIFACTS

# Observe completed writes and atomic replacements, never partial file contents.
MASK = 0x00000008 | 0x00000080 | 0x00000100 | 0x00000200 | 0x00000400 | 0x00000800
OVERFLOW = 0x00004000
DIRECTORY = 0x40000000
NOFOLLOW = 0x02000000
ONLYDIR = 0x01000000
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
HEADER = struct.Struct("iIII")


class QueueEvents:
    """One bounded notification hub per API process; disk remains authoritative."""

    def __init__(self, roots: dict[str, Path]):
        self.roots = {name: path.expanduser().resolve() for name, path in roots.items()}
        self.clients: set[asyncio.Queue] = set()
        self.watches: dict[int, Path] = {}
        self.pending: dict[tuple[str, str], dict] = {}
        self.reset = False
        self.timer = None
        self.loop = asyncio.get_running_loop()
        self.lib = ctypes.CDLL(None, use_errno=True)
        self.lib.inotify_init1.argtypes = [ctypes.c_int]
        self.lib.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.fd = self.lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "Cannot start queue notifications")
        try:
            self.scan()
            self.loop.add_reader(self.fd, self.read)
        except BaseException:
            os.close(self.fd)
            raise

    def watch(self, path: Path):
        if path in self.watches.values():
            return
        wd = self.lib.inotify_add_watch(self.fd, os.fsencode(path), MASK | NOFOLLOW | ONLYDIR)
        if wd < 0:
            raise OSError(ctypes.get_errno(), "Cannot watch queue directory")
        self.watches[wd] = path

    def scan(self):
        for root in self.roots.values():
            parent = root.parent
            while not parent.exists():
                parent = parent.parent
            self.watch(parent)
            if not root.is_dir():
                continue
            self.watch(root)
            for child in root.iterdir():
                if IDENT.fullmatch(child.name) and not child.is_symlink() and child.is_dir():
                    self.watch(child)

    def read(self):
        rescan = False
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            offset = 0
            while offset < len(data):
                wd, mask, _, size = HEADER.unpack_from(data, offset)
                offset += HEADER.size
                name = os.fsdecode(data[offset : offset + size].split(b"\0", 1)[0])
                offset += size
                directory = self.watches.get(wd)
                if mask & OVERFLOW:
                    self.reset = True
                    rescan = True
                if mask & (
                    0x00008000 | 0x00000400 | 0x00000800
                ):  # IN_IGNORED: removed/replaced watched directory
                    self.lib.inotify_rm_watch(self.fd, wd)
                    self.watches.pop(wd, None)
                    self.reset = True
                    rescan = True
                if directory is None:
                    continue
                path = directory / name
                for queue, root in self.roots.items():
                    if directory == root and name.endswith(".json") and mask & (8 | 128 | 512):
                        ident = name[:-5]
                        if IDENT.fullmatch(ident):
                            self.changed(queue, ident, False)
                    elif (
                        directory.parent == root
                        and name in ARTIFACTS.values()
                        and mask & (8 | 128 | 512)
                    ):
                        self.changed(queue, directory.name, True)
                    if path == root or (directory == root and mask & DIRECTORY):
                        rescan = True
                        self.reset = True
                    elif root.is_relative_to(path):
                        rescan = True
                        self.reset = True
        if rescan:
            try:
                self.scan()
            except OSError:
                self.reset = True
        if (self.pending or self.reset) and self.timer is None:
            self.timer = self.loop.call_later(0.05, self.publish)

    def changed(self, queue: str, ident: str, artifact: bool):
        key = (queue, ident)
        if len(self.pending) >= 1024:
            self.reset = True
            return
        previous = self.pending.get(key, {})
        self.pending[key] = {
            "queue": queue,
            "id": ident,
            "artifact": artifact or previous.get("artifact", False),
        }

    def publish(self):
        message = {"reset": self.reset, "changes": list(self.pending.values())}
        self.pending.clear()
        self.reset = False
        self.timer = None
        for client in self.clients:
            if client.full():
                client.get_nowait()
                client.put_nowait({"reset": True, "changes": []})
            else:
                client.put_nowait(message)

    async def stream(self):
        client: asyncio.Queue = asyncio.Queue(maxsize=1)
        self.clients.add(client)
        try:
            # Subscribe before snapshot refresh: reconnect never misses the gap.
            yield 'event: change\ndata: {"reset":true,"changes":[]}\n\n'
            while True:
                try:
                    message = await asyncio.wait_for(client.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                else:
                    yield f"event: change\ndata: {json.dumps(message)}\n\n"
        finally:
            self.clients.discard(client)

    def close(self):
        if self.timer:
            self.timer.cancel()
        self.loop.remove_reader(self.fd)
        os.close(self.fd)
