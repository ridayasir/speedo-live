"""In-process pub/sub hub feeding the SSE and WebSocket streams.

`publish()` is thread-safe: GPS ingestion runs in worker threads and hands the
event to the event loop. For several backend instances, put Redis pub/sub in
front of this (documented in docs/DEPLOYMENT.md).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

log = logging.getLogger("speedo.realtime")


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue
    channel: str                       # "public" or "admin"
    route_ids: set[int] = field(default_factory=set)
    bus_ids: set[int] = field(default_factory=set)

    def wants(self, channel: str, event: dict) -> bool:
        if channel != self.channel:
            return False
        if event.get("type") in ("alert", "heartbeat"):
            return True
        bus = event.get("bus") or {}
        if self.bus_ids and bus.get("id") not in self.bus_ids:
            return False
        if self.route_ids and bus.get("route_id") not in self.route_ids:
            return False
        return True


class Hub:
    def __init__(self) -> None:
        self._subs: set[Subscriber] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self, channel: str, route_ids=(), bus_ids=()) -> Subscriber:
        sub = Subscriber(asyncio.Queue(maxsize=500), channel, set(route_ids), set(bus_ids))
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def _deliver(self, channel: str, event: dict) -> None:
        for sub in list(self._subs):
            if sub.wants(channel, event):
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:  # slow client: drop oldest
                    try:
                        sub.queue.get_nowait()
                        sub.queue.put_nowait(event)
                    except Exception:
                        pass

    def publish(self, channel: str, event: dict) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._deliver(channel, event)
        else:
            self.loop.call_soon_threadsafe(self._deliver, channel, event)


hub = Hub()
