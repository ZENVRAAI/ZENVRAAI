"""Run one public-data-only ZENVRA Futures scan and write a Markdown report.

This is a scheduled research scan, not a permanent server or validated strategy.
Uses Bybit's public linear USDT perpetual market data; places no orders.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app import evaluate_candles, settings

BASE_URL = "https://api.bybit.com"
SYMBOLS = settings.symbols[:20]
INTERVAL = os.getenv("SCAN_INTERVAL", "1h")
BYBIT_INTERVALS = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720", "1d": "D", "1w": "W"}
INTERVAL_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000, "1w": 604_800_000}
REPORT_PATH = Path("scan-report.md")


async def scan_market(client: httpx.AsyncClient, symbol: str) -> dict:
    try:
        if INTERVAL not in BYBIT_INTERVALS:
            raise ValueError(f"Unsupported SCAN_INTERVAL: {INTERVAL}")
        response = await client.get(
            f"{BASE_URL}/v5/market/kline",
            params={"category": "linear", "symbol": symbol, "interval": BYBIT_INTERVALS[INTERVAL], "limit": 100},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("retCode") != 0:
            raise ValueError(f"Bybit API error: {payload.get('retMsg', 'unknown error')}")
        raw_rows = payload.get("result", {}).get("list", [])
        if not raw_rows:
            raise ValueError("No candle data returned")
        # Bybit returns newest candles first. Normalize to the engine's candle shape.
        interval_ms = INTERVAL_MS[INTERVAL]
        rows = []
        for candle in reversed(raw_rows):
            start_ms = int(candle[0])
            rows.append([start_ms, candle[1], candle[2], candle[3], candle[4], candle[5], start_ms + interval_ms - 1])
        result = evaluate_candles(symbol, "FUTURES", rows)
        return {"market": "FUTURES", "symbol": symbol, "direction": result.direction, "status": result.status, "price": result.reference_price, "reasons": result.reasons, "error": None}
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        return {"market": "FUTURES", "symbol": symbol, "direction": "WAIT", "status": "DATA_ERROR", "price": None, "reasons": [], "error": f"{type(exc).__name__}: {exc}"}


async def main() -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    timeout = httpx.Timeout(12.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "ZENVRA-AI-Research/0.2"}) as client:
        results = await asyncio.gather(*(scan_market(client, symbol) for symbol in SYMBOLS))

    lines = [
        "# ZENVRA AI — Scheduled Futures Scan Report", "",
        f"- Generated (UTC): {timestamp}",
        f"- Candle interval: {INTERVAL}",
        f"- Symbols checked: {len(SYMBOLS)} configured Futures symbols",
        "- Data source: Bybit public linear Futures API",
        "- Mode: signals-only research; no orders are placed",
        "- Model: simple baseline trend/volume filter, not validated ICT/SMC or trained AI", "",
        "| Market | Symbol | Direction | Status | Reference price |",
        "|---|---|---|---|---:|",
    ]
    for item in results:
        price = f'{item["price"]:.8g}' if item["price"] is not None else "—"
        lines.append(f'| {item["market"]} | {item["symbol"]} | {item["direction"]} | {item["status"]} | {price} |')
    lines += ["", "## Notes", ""]
    for item in results:
        if item["error"]:
            lines.append(f'- {item["market"]} {item["symbol"]}: data error ({item["error"]}).')
        elif item["reasons"]:
            lines.append(f'- {item["market"]} {item["symbol"]}: ' + " ".join(item["reasons"]))
    lines += ["", "This report is for software testing and research only. It is not financial advice.",
              "A CANDIDATE is not a validated trading signal. Confirm data quality and backtest before use."]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written to {REPORT_PATH}; checks={len(results)}; symbols={len(SYMBOLS)}")


if __name__ == "__main__":
    asyncio.run(main())
