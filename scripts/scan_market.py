"""Run one public-data-only ZENVRA scan and write a Markdown report.

This is a scheduled research scan, not a permanent server or validated strategy.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app import evaluate_candles, settings

SPOT_BASE = settings.binance_spot_base_url
FUTURES_BASE = settings.binance_futures_base_url
SYMBOLS = settings.symbols[:20]  # Keep the free scheduled job modest.
INTERVAL = os.getenv("SCAN_INTERVAL", "1h")
REPORT_PATH = Path("scan-report.md")


async def scan_market(client: httpx.AsyncClient, market: str, symbol: str) -> dict:
    base = SPOT_BASE if market == "SPOT" else FUTURES_BASE
    path = "/api/v3/klines" if market == "SPOT" else "/fapi/v1/klines"
    try:
        response = await client.get(
            f"{base}{path}",
            params={"symbol": symbol, "interval": INTERVAL, "limit": 100},
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Unexpected candle response")
        result = evaluate_candles(symbol, market, rows)
        return {
            "market": market,
            "symbol": symbol,
            "direction": result.direction,
            "status": result.status,
            "price": result.reference_price,
            "reasons": result.reasons,
            "error": None,
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {
            "market": market,
            "symbol": symbol,
            "direction": "WAIT",
            "status": "DATA_ERROR",
            "price": None,
            "reasons": [],
            "error": type(exc).__name__,
        }


async def main() -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    timeout = httpx.Timeout(12.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "ZENVRA-AI-Research/0.1"}) as client:
        tasks = [
            scan_market(client, market, symbol)
            for market in ("SPOT", "FUTURES")
            for symbol in SYMBOLS
        ]
        results = await asyncio.gather(*tasks)

    lines = [
        "# ZENVRA AI — Scheduled Scan Report",
        "",
        f"- Generated (UTC): {timestamp}",
        f"- Candle interval: {INTERVAL}",
        f"- Symbols checked: {len(SYMBOLS)} configured symbols, up to {len(results)} market checks",
        "- Mode: signals-only research; no orders are placed",
        "- Model: simple baseline trend/volume filter, not validated ICT/SMC or trained AI",
        "",
        "| Market | Symbol | Direction | Status | Reference price |",
        "|---|---|---|---|---:|",
    ]
    for item in results:
        price = f'{item["price"]:.8g}' if item["price"] is not None else "—"
        lines.append(
            f'| {item["market"]} | {item["symbol"]} | {item["direction"]} | {item["status"]} | {price} |'
        )
    lines += ["", "## Notes", ""]
    for item in results:
        if item["error"]:
            lines.append(f'- {item["market"]} {item["symbol"]}: data error ({item["error"]}).')
        elif item["reasons"]:
            lines.append(f'- {item["market"]} {item["symbol"]}: ' + " ".join(item["reasons"]))
    lines += [
        "",
        "This report is for software testing and research only. It is not financial advice.",
        "A CANDIDATE is not a validated trading signal. Confirm data quality and backtest before use.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written to {REPORT_PATH}; checks={len(results)}; symbols={len(SYMBOLS)}")


if __name__ == "__main__":
    asyncio.run(main())
