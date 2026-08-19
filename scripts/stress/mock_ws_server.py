"""Mock WebSocket server untuk stress-test UI dashboard Astronacci.

Memuntahkan tick harga cepat sesuai profil ramp/burst/sustain/recovery
selama 480 detik (8 menit). Tidak butuh paket baru — memakai FastAPI +
uvicorn yang sudah jadi dependency proyek.

Jalankan:
    python scripts/stress/mock_ws_server.py
Lalu buka frontend probe: scripts/stress/fe_probe.html di browser,
atau arahkan dashboard ke ws://localhost:8001/ws

Profil beban (msg/detik):
    0-60s    : 0      (baseline)
    60-120s  : 100    (ramp)
    120-180s : 500
    180-240s : 1000
    240-300s : 2000   (peak)
    300-360s : 5000   (burst)
    360-420s : 2000   (sustained, backpressure-aware)
    420-480s : 100    (recovery)

Mendengarkan perintah backpressure dari client:
    {"cmd":"throttle","max_rate":50}  -> batasi push ke max_rate msg/s
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

DURATION_S = 480
TICKERS = ["BBCA", "TLKM", "ASII", "GOTO", "BMRI", "INDF", "UNVR", "ICBP",
           "ADRO", "ANTM", "PGAS", "KRAS", "MBAP", "SMRA", "CPIN", "^JKSE"]

# Profil beban: (start_s, end_s, msg_per_s)
PROFILE = [
    (0,   60,  0),
    (60,  120, 100),
    (120, 180, 500),
    (180, 240, 1000),
    (240, 300, 2000),
    (300, 360, 5000),
    (360, 420, 2000),
    (420, 480, 100),
]


def target_rate(elapsed: float) -> int:
    for s, e, r in PROFILE:
        if s <= elapsed < e:
            return r
    return 0


class Hub:
    """Pub/sub channel manager sederhana untuk single-user."""

    def __init__(self) -> None:
        self.conns: set[WebSocket] = set()
        self.throttle_rate: int | None = None  # set by client backpressure
        self.start = time.monotonic()
        self.sent = 0

    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        self.conns.add(ws)
        try:
            # Dengarkan perintah dari client (throttle)
            while True:
                msg = await ws.receive_text()
                try:
                    cmd = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                if cmd.get("cmd") == "throttle":
                    self.throttle_rate = int(cmd.get("max_rate", 50))
                    print(f"[hub] backpressure ON: max_rate={self.throttle_rate}")
                elif cmd.get("cmd") == "throttle_off":
                    self.throttle_rate = None
                    print("[hub] backpressure OFF")
        except WebSocketDisconnect:
            pass
        finally:
            self.conns.discard(ws)

    async def broadcaster(self) -> None:
        """Loop utama: push tick sesuai profil + throttle."""
        while True:
            elapsed = time.monotonic() - self.start
            if elapsed > DURATION_S:
                print(f"[hub] selesai. total sent={self.sent}")
                break

            rate = target_rate(elapsed)
            if self.throttle_rate is not None:
                rate = min(rate, self.throttle_rate)

            if rate == 0 or not self.conns:
                await asyncio.sleep(0.5)
                continue

            interval = 1.0 / rate
            t0 = time.monotonic()
            # Kirim `rate` pesan dalam 1 detik (batched per interval)
            for _ in range(rate):
                if not self.conns:
                    break
                tick = {
                    "ch": "prices.tick",
                    "t": random.choice(TICKERS),
                    "p": round(random.uniform(100, 9000), 2),
                    "ts": int(time.time() * 1000),
                }
                payload = json.dumps(tick, separators=(",", ":"))
                dead: list[WebSocket] = []
                for ws in self.conns:
                    try:
                        await ws.send_text(payload)
                        self.sent += 1
                    except Exception:
                        dead.append(ws)
                for d in dead:
                    self.conns.discard(d)
                # Jaga cadence; jika kirim terlalu cepat, yield
                elapsed_loop = time.monotonic() - t0
                sleep_for = interval - (elapsed_loop % interval)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            # Sisa detik
            spent = time.monotonic() - t0
            if spent < 1.0:
                await asyncio.sleep(1.0 - spent)


hub = Hub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(hub.broadcaster())
    yield
    task.cancel()


app = FastAPI(title="Mock WS Stress Server", lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.join(ws)


@app.get("/profile")
async def get_profile():
    """FE bisa GET untuk menampilkan timeline fase uji."""
    return {"duration_s": DURATION_S, "phases": [
        {"start": s, "end": e, "rate": r} for s, e, r in PROFILE
    ]}


if __name__ == "__main__":
    import uvicorn

    print(f"[mock] WS server di ws://localhost:8001/ws  (durasi {DURATION_S}s)")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
