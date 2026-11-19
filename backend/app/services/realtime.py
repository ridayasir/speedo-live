"""Real-time fan-out of bus positions to WebSocket subscribers.

With Redis configured, events go through a Redis pub/sub channel so several API instances
share them. Without Redis, events are broadcast in-process.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

from ..config import get_settings

log = logging.getLogger("speedo.realtime")
CHANNEL = "speedo:live"


@dataclass
class Subscriber:
    ws: WebSocket
    route_ids: set[int] = field(default_factory=set)
    bus_ids: set[int] = field(default_factory=set)

    def wants(self, event: dict) -> bool:
        if not self.route_ids and not self.bus_ids:
            return True
        return event.get("route_id") in self.route_ids or event.get("bus_id") in self.bus_ids


class LiveHub:
    def __init__(self) -> None:
        self.subs: dict[int, Subscriber] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.redis_sync = None
        self._listener: asyncio.Task | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        url = get_settings().redis_url
        if not url:
            return
        try:
            import redis
            import redis.asyncio as aredis

            self.redis_sync = redis.Redis.from_url(url, socket_connect_timeout=2)
            self.redis_sync.ping()
            self._aredis = aredis.Redis.from_url(url)
            self._listener = asyncio.create_task(self._listen())
            log.info("Live hub using Redis pub/sub")
        except Exception as exc:  # pragma: no cover - depends on environment
            log.warning("Redis unavailable (%s); using in-process broadcast", exc)
            self.redis_sync = None

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
        for sub in list(self.subs.values()):
            try:
                await sub.ws.close()
            except Exception:
                pass
        self.subs.clear()

    async def _listen(self) -> None:
        pubsub = self._aredis.pubsub()
        await pubsub.subscribe(CHANNEL)
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                await self._broadcast(json.loads(msg["data"]))
            except Exception:  # pragma: no cover
                log.exception("bad live message")

    async def _broadcast(self, event: dict) -> None:
        dead = []
        text = json.dumps(event, default=str)
        for key, sub in list(self.subs.items()):
            if not sub.wants(event):
                continue
            try:
                await sub.ws.send_text(text)
            except Exception:
                dead.append(key)
        for key in dead:
            self.subs.pop(key, None)

    def publish(self, event: dict) -> None:
        """Thread-safe publish, callable from sync request handlers and background threads."""
        if self.redis_sync is not None:
            try:
                self.redis_sync.publish(CHANNEL, json.dumps(event, default=str))
                return
            except Exception as exc:  # pragma: no cover
                log.warning("Redis publish failed (%s); falling back to local broadcast", exc)
        if self.loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(self._broadcast(event))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(event), self.loop)

    def add(self, sub: Subscriber) -> int:
        key = id(sub)
        self.subs[key] = sub
        return key

    def remove(self, key: int) -> None:
        self.subs.pop(key, None)


hub = LiveHub()
