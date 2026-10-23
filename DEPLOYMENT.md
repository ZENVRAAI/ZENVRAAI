# ZENVRA AI — deployment notes

## Current repository layout

The Python service files are at the repository root:
- `app.py`
- `requirements.txt`
- `test_app.py`
- `test_api_safety.py`

There is no `robot/` directory in the current root listing. When creating a **separate Railway service** from this repository, set the service root directory to the repository root (usually leave the root directory blank or set it to `/` depending on Railway's UI), not `/robot`.

## Suggested Railway settings

- Build: Python auto-detection / install from `requirements.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Public market data requires no Binance API keys.
- Do not add exchange trading keys. This app is signals-only.
- After deploy, test `/health`, `/api/config`, and `/api/markets?market=SPOT`.

## Important limitations

- This service does not currently run a background scanner. `scan_interval_seconds` is configuration metadata only.
- It does not persist signals, trades, or outcomes in a database.
- The candidate engine is a basic moving-average/volume filter, not the planned ICT/SMC or three-sweep strategy.
- Confirm the deployment and live endpoints before considering it operational.
