# Production Deployment Guide

## Astronacci Quant Trading System — IDX

### Prerequisites

- Python 3.12+
- PostgreSQL 15+
- NVIDIA GPU (optional, for DL models)
- Ollama (for LLM agents)
- Node.js 18+ (for frontend)

### 1. Database Setup

```bash
# Create database
createdb quant

# Run migrations
alembic upgrade head

# Create paper trading tables
psql -d quant -f scripts/create_paper_trading_tables.sql
```

### 2. Environment Configuration

Create `.env` file:

```env
DATABASE_URL=postgresql://user:pass@localhost:5432/quant
LLM_PROVIDER=ollama
LLM_MODEL=deepseek-r1:1.5b
LLM_BASE_URL=http://localhost:11434
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 3. Data Ingestion

```bash
# Daily data fetch (run after market close)
./scripts/run_daily_fetch.sh

# RSS news fetch
python -c "from quant.data.rss_adapter import RSSFeedAdapter; a=RSSFeedAdapter(); a.store(a.fetch_all()); a.close()"

# IndoBERT sentiment scoring
python -c "from quant.ai.indobert_scorer import score_existing_news; score_existing_news(limit=1000)"
```

### 4. Model Training

```bash
# Train DL models (VAE, LSTM, XGBoost+LightGBM)
python scripts/train_dl_models.py --limit 50

# Models saved to models/ directory
```

### 5. Daily Pipeline

```bash
# Causality computation (run before pipeline — 17:15 WIB)
python -c "
from quant.pipeline.scheduler_tasks import run_causality_computation
run_causality_computation()
"

# Full pipeline: ingest → screen → analyze → signal → portfolio → execute
python scripts/run_pipeline.py 50

# Paper trading with state persistence
python scripts/run_paper_trading.py --universe 50

# IC evaluation
python -c "
from datetime import date
from quant.pipeline.orchestrator import PipelineOrchestrator
from quant.core.db import get_db
session = get_db()
orch = PipelineOrchestrator(session=session)
orch.evaluate_ic(date.today(), horizon=5)
session.close()
"
```

### 6. Backtesting

```bash
# Walk-forward backtest with DSR + PBO
python scripts/run_backtest.py --limit 10

# Results saved to models/backtest_results/
```

### 7. Monitoring

```bash
# Drift detection (run weekly)
python -c "
from quant.monitoring.drift import DriftDetector
import numpy as np
detector = DriftDetector()
detector.set_baseline_metrics({'sharpe': 1.5, 'max_dd': -0.10})
detector.set_baseline_predictions(np.random.normal(0.02, 0.01, 1000))
report = detector.assess(
    current_metrics={'sharpe': 1.2, 'max_dd': -0.12},
    current_predictions=np.random.normal(0.015, 0.012, 500),
)
print(f'Drifted: {report.is_drifted}')
"

# Model retirement check (run weekly)
python -c "
from quant.monitoring.retirement import ModelRetirementManager
from quant.core.db import get_db
session = get_db()
mgr = ModelRetirementManager(session=session)
for v in mgr.evaluate_all():
    print(f'{v.engine_name:20s} {v.verdict:6s} score={v.score:.2f}')
session.close()
"
```

### 8. Frontend

```bash
cd frontend
npm install
npm run build
npm start
```

Access at `http://localhost:3000`. Pages:
- `/` — Main dashboard (NAV, movers, signals, portfolio)
- `/pipeline` — Pipeline status dashboard
- `/signals` — Signal feed
- `/screener` — Stock screener
- `/portfolio` — Portfolio positions
- `/backtest` — Backtest results
- `/scheduler` — Task scheduler
- `/data` — Data sources
- `/reports` — Trade reports

### 9. API Server

```bash
# Start API
python -m quant.api.app
# Default: http://localhost:8000
```

Key endpoints:
- `GET /api/pipeline/dashboard` — Full pipeline status
- `GET /api/pipeline/status` — Pipeline state
- `GET /api/signals/attribution` — Latest signals
- `GET /api/portfolio` — Portfolio weights
- `GET /api/advisory` — Stock screener
- `GET /api/evaluation/engines` — Engine performance

### 10. Scheduling (cron)

```cron
# Daily data fetch at 17:00 WIB
0 17 * * 1-5 /home/petrick/projects/quant/scripts/run_daily_fetch.sh

# Causality computation at 17:15 WIB (before daily pipeline)
15 17 * * 1-5 cd /home/petrick/projects/quant && .venv/bin/python -c "from quant.pipeline.scheduler_tasks import run_causality_computation; run_causality_computation()"

# Daily pipeline at 17:30 WIB
30 17 * * 1-5 cd /home/petrick/projects/quant && .venv/bin/python scripts/run_paper_trading.py --universe 50

# Weekly backtest on Saturday
0 10 * * 6 cd /home/petrick/projects/quant && .venv/bin/python scripts/run_backtest.py --limit 10

# RSS news fetch every 2 hours
0 */2 * * * cd /home/petrick/projects/quant && .venv/bin/python -c "from quant.data.rss_adapter import RSSFeedAdapter; a=RSSFeedAdapter(); a.store(a.fetch_all()); a.close()"
```

### 11. Telegram Alerts

Set environment variables:
```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF
TELEGRAM_CHAT_ID=@your_channel
```

Alerts sent for:
- Daily trading summary
- Risk gate violations
- Portfolio halt
- Model retirement verdicts

### 12. GPU Configuration

- VAE + LSTM training: `cuda:1` (secondary GPU)
- IndoBERT inference: `cuda:1`
- Frontend + API: CPU only

### 13. Backup

```bash
# Database backup
pg_dump quant > backups/quant_$(date +%Y%m%d).sql

# Model backup
tar -czf backups/models_$(date +%Y%m%d).tar.gz models/
```
