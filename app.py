"""ZENVRA AI starter API.

Futures-only signals research scaffold. It does not place orders and does not
claim that any generated candidate is profitable.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "ZENVRA AI Signal Scanner"
    scan_interval_seconds: int = 60
    candidate_symbols: str = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT"
    min_24h_quote_volume_usdt: float = 25_000_000
    min_reward_risk: float = 2.0
    max_candle_age_seconds: int = 180
    binance_futures_base_url: str = "https://fapi.binance.com"

    @property
    def symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.candidate_symbols.split(",") if s.strip()]


settings = Settings()


class MarketSummary(BaseModel):
    symbol: str
    market: Literal["FUTURES"]
    price: float
    change_24h_pct: float
    quote_volume_24h: float
    observed_at: str
    source: str = "Public market-data API"


class CandidateSignal(BaseModel):
    symbol: str
    market: Literal["FUTURES"]
    direction: Literal["LONG", "SHORT", "WAIT"]
    status: Literal["CANDIDATE", "WAIT", "REJECTED"]
    reference_price: float | None = None
    entry_zone: list[float] | None = None
    stop_loss: float | None = None
    take_profits: list[float] | None = None
    reward_risk_estimate: float | None = None
    reasons: list[str]
    model_version: str = "rules-baseline-0.1.0"
    generated_at: str
    paper_only: bool = True


class Health(BaseModel):
    status: str
    service: str
    timestamp: str
    trading_execution_enabled: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(8.0), headers={"User-Agent": "ZENVRA-AI-Research/0.1"})
    yield
    await app.state.http.aclose()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return app.state.http


async def get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None) -> Any:
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        # Include the upstream status so deployment/network restrictions can be diagnosed.
        raise HTTPException(status_code=502, detail=f"Market data provider request failed: HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Market data provider request failed: {type(exc).__name__}") from exc


@app.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok", service=settings.app_name, timestamp=now_iso())


@app.get("/api/markets", response_model=list[MarketSummary])
async def markets(market: Literal["FUTURES"] = Query(default="FUTURES"), symbols: str | None = None) -> list[MarketSummary]:
    selected = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else settings.symbols
    if not selected or len(selected) > 100:
        raise HTTPException(status_code=400, detail="Provide 1–100 comma-separated symbols.")
    client = client_for(app)
    # Futures-only market data.
    data = await get_json(client, f"{settings.binance_futures_base_url}/fapi/v1/ticker/24hr")
    by_symbol = {str(row.get("symbol", "")).upper(): row for row in data if isinstance(row, dict)}
    output: list[MarketSummary] = []
    for symbol in selected:
        row = by_symbol.get(symbol)
        if not row:
            continue
        try:
            output.append(MarketSummary(
                symbol=symbol, market="FUTURES",
                price=float(row["lastPrice"]),
                change_24h_pct=float(row["priceChangePercent"]),
                quote_volume_24h=float(row["quoteVolume"]),
                observed_at=now_iso(), source="Binance Futures public REST API",
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return output

def evaluate_candles(symbol: str, market: Literal["FUTURES"], rows: list[list[Any]]) -> CandidateSignal:
    """Conservative baseline: detect directional momentum, otherwise WAIT.

    Not an ICT/SMC or trained-ML model. It purposely emits no entry/SL/TP unless
    the simple pattern passes; treat these as candidates for later validation.
    """
    generated = now_iso()
    if len(rows) < 30:
        return CandidateSignal(symbol=symbol, market=market, direction="WAIT", status="WAIT", reasons=["Insufficient candles; no signal issued."], generated_at=generated)
    try:
        candles = [{"open_time": int(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5]), "close_time": int(r[6])} for r in rows]
    except (TypeError, ValueError, IndexError):
        return CandidateSignal(symbol=symbol, market=market, direction="WAIT", status="WAIT", reasons=["Malformed candle data; no signal issued."], generated_at=generated)
    last = candles[-1]
    age = time.time() - last["close_time"] / 1000
    if age > settings.max_candle_age_seconds:
        return CandidateSignal(symbol=symbol, market=market, direction="WAIT", status="WAIT", reasons=["Latest candle is stale or still unavailable; no signal issued."], generated_at=generated)
    closes = [c["close"] for c in candles]
    recent = candles[-20:]
    avg_vol = sum(c["volume"] for c in recent[:-1]) / max(1, len(recent) - 1)
    if avg_vol <= 0:
        return CandidateSignal(symbol=symbol, market=market, direction="WAIT", status="WAIT", reasons=["Volume baseline invalid; no signal issued."], generated_at=generated)
    mean20 = sum(closes[-20:]) / 20
    mean50 = sum(closes[-min(50, len(closes)):]) / min(50, len(closes))
    vol_ratio = last["volume"] / avg_vol
    # Only a very basic trend/volume candidate filter. Do not label as high confidence.
    direction: Literal["LONG", "SHORT", "WAIT"] = "WAIT"
    reasons = [f"Close vs 20-candle mean: {'above' if last['close'] > mean20 else 'below'}.", f"Recent volume ratio: {vol_ratio:.2f}x.", "Baseline trend filter only; ICT/SMC, risk and out-of-sample validation are not yet implemented."]
    if last["close"] > mean20 > mean50 and vol_ratio >= 1.5:
        direction = "LONG"
    elif market == "FUTURES" and last["close"] < mean20 < mean50 and vol_ratio >= 1.5:
        direction = "SHORT"
    if direction == "WAIT":
        return CandidateSignal(symbol=symbol, market=market, direction="WAIT", status="WAIT", reference_price=last["close"], reasons=reasons + ["Strict baseline condition not met; no trade candidate."], generated_at=generated)
    return CandidateSignal(symbol=symbol, market=market, direction=direction, status="CANDIDATE", reference_price=last["close"], reasons=reasons + ["Research candidate only; do not treat as a validated trading signal."], generated_at=generated)


@app.get("/api/candidate/{symbol}", response_model=CandidateSignal)
async def candidate(symbol: str, market: Literal["FUTURES"] = Query(default="FUTURES"), interval: Literal["5m", "15m", "1h", "4h", "1d"] = Query(default="1h")) -> CandidateSignal:
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or len(symbol) > 24:
        raise HTTPException(status_code=400, detail="Invalid symbol format.")
    rows = await get_json(client_for(app), f"{settings.binance_futures_base_url}/fapi/v1/klines", params={"symbol": symbol, "interval": interval, "limit": 100})
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Market data response format was not recognized.")
    return evaluate_candles(symbol, market, rows)


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return {"service": settings.app_name, "markets": ["FUTURES"], "mode": "signals_only", "paper_only": True, "execution_enabled": False, "candidate_symbols": settings.symbols, "scan_interval_seconds": settings.scan_interval_seconds, "note": "Candidate engine is a simple baseline, not a validated AI trading strategy."}
