from app import CandidateSignal, evaluate_candles


def make_rows(n=100, slope=1.0, volume=100.0, start=1_700_000_000_000):
    rows = []
    for i in range(n):
        close = 100.0 + i * slope
        # Binance kline shape: open time, open, high, low, close, volume, close time, ...
        rows.append([start + i * 3_600_000, str(close - .2), str(close + .8), str(close - .8), str(close), str(volume), start + (i + 1) * 3_600_000 - 1])
    return rows


def test_insufficient_candles_waits():
    result = evaluate_candles("BTCUSDT", "SPOT", make_rows(10))
    assert result.direction == "WAIT"
    assert result.status == "WAIT"


def test_bad_data_waits():
    result = evaluate_candles("BTCUSDT", "SPOT", [["bad"]] * 40)
    assert isinstance(result, CandidateSignal)
    assert result.direction == "WAIT"


def test_stale_data_never_generates_candidate():
    rows = make_rows(100, start=1_600_000_000_000)
    result = evaluate_candles("BTCUSDT", "SPOT", rows)
    assert result.direction == "WAIT"
    assert "stale" in result.reasons[0].lower()
