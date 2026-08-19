"""Real-time transport layer for the Quant API.

Provides:
  * ``Hub``           — async pub/sub channel manager for WebSocket clients.
  * ``LogStreamHandler`` — ``logging.Handler`` that fans log records out to
    SSE subscribers via an asyncio queue (thread-safe bridge).
  * ``MetricsBroadcaster`` — periodic emitter of system metrics (DB pool,
    rate-limiter stats, FPS backpressure) to SSE subscribers.
  * FastAPI endpoints ``/ws`` (WebSocket) and ``/api/observability/stream``
    (Server-Sent Events).

Design goals (single-user private app):
  * One TCP connection reused for many channels (prices/signals/portfolio).
  * Client may subscribe/unsubscribe per channel and send backpressure
    commands (``{"cmd":"throttle","max_rate":N}``).
  * SSE for observability is simpler & auto-reconnects natively; no need
    to multiplex on the WS connection.
  * All cross-thread bridges use ``asyncio.run_coroutine_threadsafe`` so the
    logging thread can feed the asyncio SSE loop safely.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────

_LOG_RING_MAX = 500          # max log entries kept in memory
_SSE_QUEUE_MAX = 256         # per-subscriber SSE queue backpressure
_METRIC_INTERVAL_S = 2.0     # metrics pushed every 2s
_HEARTBEAT_S = 25.0          # WS heartbeat (ping) interval


# ── Hub: WebSocket pub/sub ──────────────────────────────────────────────

class Hub:
    """Async pub/sub channel manager for WebSocket clients.

    Each connection holds its own set of subscribed channels. Broadcasts
    only reach connections subscribed to the target channel.
    """

    def __init__(self) -> None:
        # conn -> set[channel]
        self._subs: dict[WebSocket, set[str]] = {}
        # channel -> set[conn]  (derived cache for fast broadcast)
        self._channels: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self.throttle_rate: int | None = None  # backpressure from FE
        self.sent = 0
        self.recv = 0

    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._subs[ws] = set()
        logger.info("ws joined (conns=%d)", len(self._subs))

    async def leave(self, ws: WebSocket) -> None:
        async with self._lock:
            chans = self._subs.pop(ws, set())
            for ch in chans:
                conns = self._channels.get(ch)
                if conns:
                    conns.discard(ws)
                    if not conns:
                        del self._channels[ch]
        logger.info("ws left (conns=%d)", len(self._subs))

    async def subscribe(self, ws: WebSocket, channels: list[str]) -> None:
        async with self._lock:
            cur = self._subs.setdefault(ws, set())
            for ch in channels:
                cur.add(ch)
                self._channels.setdefault(ch, set()).add(ws)

    async def unsubscribe(self, ws: WebSocket, channels: list[str]) -> None:
        async with self._lock:
            cur = self._subs.get(ws)
            if not cur:
                return
            for ch in channels:
                cur.discard(ch)
                conns = self._channels.get(ch)
                if conns:
                    conns.discard(ws)
                    if not conns:
                        del self._channels[ch]

    async def broadcast(self, channel: str, payload: dict[str, Any]) -> None:
        """Send ``payload`` to every connection subscribed to ``channel``.

        Non-blocking per connection: a slow client is dropped after one
        failed send to protect the rest of the fan-out.
        """
        async with self._lock:
            conns = list(self._channels.get(channel, ()))
        if not conns:
            return
        text = json.dumps(payload, separators=(",", ":"), default=str)
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(text)
                self.sent += 1
            except Exception:
                dead.append(ws)
        for d in dead:
            await self.leave(d)

    async def handle_command(self, ws: WebSocket, msg: str) -> None:
        """Parse a client command (subscribe/unsubscribe/throttle)."""
        self.recv += 1
        try:
            cmd = json.loads(msg)
        except json.JSONDecodeError:
            return
        action = cmd.get("cmd") or cmd.get("action")
        if action == "subscribe":
            await self.subscribe(ws, list(cmd.get("channels", [])))
        elif action == "unsubscribe":
            await self.unsubscribe(ws, list(cmd.get("channels", [])))
        elif action == "throttle":
            self.throttle_rate = int(cmd.get("max_rate", 50))
            logger.warning("backpressure ON: max_rate=%s", self.throttle_rate)
        elif action == "throttle_off":
            self.throttle_rate = None
            logger.info("backpressure OFF")

    def stats(self) -> dict[str, Any]:
        return {
            "conns": len(self._subs),
            "channels": {ch: len(s) for ch, s in self._channels.items()},
            "sent": self.sent,
            "recv": self.recv,
            "throttle_rate": self.throttle_rate,
        }


# ── Log stream handler (logging -> asyncio queue) ───────────────────────

class LogStreamHandler(logging.Handler):
    """Bridges stdlib ``logging`` records into SSE subscriber queues.

    Thread-safe: log records may originate from worker threads; we marshal
    them onto the event loop via ``call_soon_threadsafe``.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, ring_max: int = _LOG_RING_MAX) -> None:
        super().__init__(level=logging.INFO)
        self._loop = loop
        self._ring: deque[dict[str, Any]] = deque(maxlen=ring_max)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": record.created,
            "level": record.levelname,
            "src": record.name,
            "msg": record.getMessage(),
        }
        # Thread-safe: schedule append + fanout on the loop.
        try:
            self._loop.call_soon_threadsafe(self._dispatch, entry)
        except RuntimeError:
            # Loop closed during shutdown — drop silently.
            pass

    def _dispatch(self, entry: dict[str, Any]) -> None:
        self._ring.append(entry)
        for q in self._subscribers:
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                # Slow subscriber: drop oldest to make room.
                try:
                    q.get_nowait()
                    q.put_nowait(entry)
                except Exception:
                    pass

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._ring)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SSE_QUEUE_MAX)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)


# ── Metrics broadcaster ─────────────────────────────────────────────────

class MetricsBroadcaster:
    """Periodically pushes a merged metrics snapshot to SSE subscribers."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        hub: Hub,
        log_handler: LogStreamHandler,
        get_db_status: Any,
        get_rate_limiter_stats: Any,
    ) -> None:
        self._loop = loop
        self._hub = hub
        self._log_handler = log_handler
        self._get_db_status = get_db_status
        self._get_rate_limiter_stats = get_rate_limiter_stats
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SSE_QUEUE_MAX)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = self._loop.create_task(self._run())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                snapshot = {
                    "ts": time.time(),
                    "db": self._get_db_status(),
                    "rate_limiters": self._get_rate_limiter_stats(),
                    "ws": self._hub.stats(),
                    "log_ring_size": len(self._log_handler.snapshot()),
                }
            except Exception as exc:
                snapshot = {"ts": time.time(), "error": str(exc)}
            for q in list(self._subscribers):
                try:
                    q.put_nowait(snapshot)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                        q.put_nowait(snapshot)
                    except Exception:
                        pass
            await asyncio.sleep(_METRIC_INTERVAL_S)


# ── SSE helpers ─────────────────────────────────────────────────────────

def _sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


# ── Wiring ──────────────────────────────────────────────────────────────

def install(
    app: FastAPI,
    *,
    get_db_status: Any,
    get_rate_limiter_stats: Any,
) -> Hub:
    """Install WS + SSE endpoints and lifecycle hooks on ``app``.

    Returns the shared ``Hub`` so other modules can broadcast (e.g. push a
    price tick via ``hub.broadcast("prices.tick", {...})``). The
    ``LogStreamHandler`` and ``MetricsBroadcaster`` are created at startup
    and accessible via ``app.state.realtime_log_handler`` /
    ``app.state.realtime_metrics``.
    """
    hub = Hub()
    # Loop reference is captured at startup (uvicorn runs one loop).
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # ── startup ──
        loop = asyncio.get_running_loop()
        log_handler = LogStreamHandler(loop)
        # Attach to root logger so all subsystems are captured.
        root = logging.getLogger()
        root.addHandler(log_handler)
        # Also attach to uvicorn.access — it sets propagate=False by default,
        # so HTTP access logs ("GET /api/... 200 12ms") would never reach the
        # root logger. Bridge it explicitly so the FE observability console
        # sees real API traffic.
        access_logger = logging.getLogger("uvicorn.access")
        access_logger.addHandler(log_handler)
        metrics = MetricsBroadcaster(
            loop, hub, log_handler, get_db_status, get_rate_limiter_stats,
        )
        metrics.start()
        state["log_handler"] = log_handler
        state["metrics"] = metrics
        state["loop"] = loop
        _app.state.realtime_log_handler = log_handler
        _app.state.realtime_metrics = metrics
        _app.state.realtime_loop = loop
        _app.state.realtime_hub = hub
        logger.info("realtime layer installed (ws=/ws, sse=/api/observability/stream)")

        # ── Simulation tick broadcaster ──
        # Polls the simulation engine and broadcasts ticks to WS clients
        # subscribed to the "prices.tick" channel.
        async def _sim_broadcaster():
            from quant.simulation import get_simulation_engine
            while True:
                await asyncio.sleep(0.5)  # check every 500ms
                sim = get_simulation_engine()
                if not sim or not sim._running:
                    continue
                # Respect backpressure
                if hub.throttle_rate:
                    await asyncio.sleep(1.0 / hub.throttle_rate)
                # Broadcast IHSG tick
                ihsg = sim.get_latest_tick("^JKSE")
                if ihsg:
                    await hub.broadcast("prices.tick", {
                        "ch": "prices.tick",
                        "t": "^JKSE",
                        "p": ihsg["price"],
                        "v": ihsg["volume"],
                        "ts": ihsg["timestamp"],
                    })
                # Broadcast a random stock tick (round-robin)
                for ticker in list(sim.latest_ticks.keys()):
                    if ticker == "^JKSE":
                        continue
                    tick = sim.get_latest_tick(ticker)
                    if tick:
                        await hub.broadcast("prices.tick", {
                            "ch": "prices.tick",
                            "t": ticker,
                            "p": tick["price"],
                            "v": tick["volume"],
                            "ts": tick["timestamp"],
                        })

        sim_task = asyncio.create_task(_sim_broadcaster())
        state["sim_task"] = sim_task

        try:
            yield
        finally:
            # ── shutdown ──
            sim_task.cancel()
            if metrics:
                await metrics.stop()
            if log_handler:
                root.removeHandler(log_handler)
                access_logger.removeHandler(log_handler)

    # Wire lifespan (FastAPI ≥0.93 supports app.router.lifespan_context).
    app.router.lifespan_context = lifespan

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await hub.join(ws)
        try:
            while True:
                msg = await ws.receive_text()
                await hub.handle_command(ws, msg)
        except WebSocketDisconnect:
            pass
        finally:
            await hub.leave(ws)

    @app.get("/api/observability/stream")
    async def observability_stream():
        """Server-Sent Events: log + metric stream for the FE console.

        Reuses a single SSE channel; events are typed (``log`` / ``metric``).
        Auto-reconnect is handled by the browser ``EventSource`` API.
        """
        log_handler: LogStreamHandler | None = state.get("log_handler")
        metrics: MetricsBroadcaster | None = state.get("metrics")
        if log_handler is None or metrics is None:
            # Startup not finished yet — tell client to retry shortly.
            async def _not_ready():
                yield _sse("metric", {"ready": False, "retry_in_ms": 500})
            return StreamingResponse(
                _not_ready(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        log_q = log_handler.subscribe()
        metric_q = metrics.subscribe()

        async def gen():
            try:
                # Replay recent log ring on connect.
                for entry in log_handler.snapshot():
                    yield _sse("log", entry)
                while True:
                    done, pending = await asyncio.wait(
                        {asyncio.create_task(log_q.get()),
                         asyncio.create_task(metric_q.get())},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for p in pending:
                        p.cancel()
                    for t in done:
                        entry = t.result()
                        if "level" in entry:
                            yield _sse("log", entry)
                        else:
                            yield _sse("metric", entry)
            except asyncio.CancelledError:
                pass
            finally:
                log_handler.unsubscribe(log_q)
                metrics.unsubscribe(metric_q)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # disable proxy buffering
            },
        )

    @app.get("/api/observability/snapshot")
    async def observability_snapshot():
        """One-shot snapshot of current logs + metrics (no streaming)."""
        log_handler: LogStreamHandler = state.get("log_handler")  # type: ignore[assignment]
        if log_handler is None:
            return {"logs": [], "metrics": None, "ready": False}
        metrics: MetricsBroadcaster = state["metrics"]
        return {
            "ready": True,
            "logs": log_handler.snapshot(),
            "metrics": {
                "db": get_db_status(),
                "rate_limiters": get_rate_limiter_stats(),
                "ws": hub.stats(),
            },
        }

    # Expose hub for other modules via app state.
    app.state.realtime_hub = hub
    return hub
