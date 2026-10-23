# ZENVRA AI Robot — Starter Module (v0.1)

This module is a **research-only, signals-only** starter for the ZENVRA app. It reads public Binance Spot/Futures market data and exposes health, market-summary, configuration, and baseline candidate endpoints.

> It is not a validated trading strategy, does not guarantee accuracy, and contains no order-placement or exchange trading-key functionality. Candidate results must not be treated as financial advice.

## Files

- `app.py` — FastAPI service, public market data, basic directional candidate filter.
- `requirements.txt` — dependencies.
- `.env.example` — safe configurable defaults; no secrets required for public market data.
- `test_app.py` — basic safety checks.

## Run locally

```bash
cd robot
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` to try endpoints.

## Endpoints

- `GET /health`
- `GET /api/config`
- `GET /api/markets?market=SPOT`
- `GET /api/markets?market=FUTURES&symbols=BTCUSDT,ETHUSDT`
- `GET /api/candidate/BTCUSDT?market=SPOT&interval=1h`
- `GET /api/candidate/BTCUSDT?market=FUTURES&interval=15m`

## Deploy as a separate Railway service

1. Add a new service from this repository and set the root directory to `/robot`.
2. Use start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`.
3. Add environment variables from `.env.example` as needed.
4. Confirm `/health` responds and test market endpoints before exposing them publicly.
5. Keep it as a separate service until reviewed; do not replace the existing web app's `index.html`.

## Current limitations / next work

1. This uses REST polling; build a WebSocket collector for efficient 24/7 streaming.
2. Add PostgreSQL persistence and signal outcome tracking.
3. Implement explicit ICT/SMC, multi-timeframe and three-sweep rules with tests.
4. Add a realistic backtesting engine including fees, slippage, funding and intrabar SL/TP ambiguity.
5. Train/evaluate ML models with strict chronological splits and walk-forward validation before using predictions.
6. Add Telegram notifications only after signal lifecycle and deduplication are reliable.
7. Add rate limiting, authentication for non-public endpoints, structured logs, metrics, alerting and recovery checks.

## Quality policy

When input is stale or malformed, return `WAIT`. The simple moving-average/volume filter included here is only a plumbing example for verifying live data; it is **not** a production signal-quality model. No claim of positive expectancy or win rate is made.
