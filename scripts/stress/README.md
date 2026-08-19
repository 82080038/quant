# UI Stress-Test Toolkit — Astronacci Dashboard

Mock simulasi lonjakan data BE→FE untuk menguji ketahanan UI dashboard.

## Cara pakai

### 1. Jalankan mock WS server (BE simulator)
```bash
# dari root repo — pakai venv proyek (fastapi & uvicorn sudah terpasang)
source .venv/bin/activate
python scripts/stress/mock_ws_server.py
# -> ws://localhost:8001/ws  (durasi 480s / 8 menit)
```

### 2. Jalankan FE probe (pengukur FPS/heap/backlog)
Buka **`scripts/stress/fe_probe.html`** langsung di browser Chrome
(double-click file, atau `python -m http.server` lalu buka).

Klik **Start**. Probe akan:
- connect ke `ws://localhost:8001/ws`
- menghitung FPS (rAF), JS heap (`performance.memory`), long tasks
  (`PerformanceObserver`), WS backlog (msg recv vs render)
- **kirim backpressure** `{cmd:throttle,max_rate:50}` otomatis saat FPS<30
- kirim `{cmd:throttle_off}` saat FPS pulih >55

### 3. Profil beban (8 menit)
| Fase        | Waktu (s) | Msg/detik |
|-------------|-----------|-----------|
| Baseline    | 0-60      | 0         |
| Ramp        | 60-120    | 100       |
| Ramp        | 120-180   | 500       |
| Ramp        | 180-240   | 1000      |
| Peak        | 240-300   | 2000      |
| Burst       | 300-360   | 5000      |
| Sustained   | 360-420   | 2000*     |
| Recovery    | 420-480   | 100       |

\* backpressure-aware: BE turunkan rate jika FE minta throttle.

### 4. Membaca hasil
Target PASS:
- FPS avg >= 50 di fase <= 2000 msg/s
- FPS tidak drop < 30 sustained (jika drop, backpressure harus pulihkan < 5s)
- JS heap stabil < 80 MB (tidak monoton naik = memory leak)
- Long tasks < 30 per menit di fase <= 1000 msg/s

Jika FAIL: implementasikan strategi di bagian 2.2 (coalescing rAF,
virtualisasi, Web Worker, OffscreenCanvas).
