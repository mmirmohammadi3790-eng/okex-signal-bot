
import requests
from datetime import datetime, timezone

BASE = "https://api.bitpin.ir"
SYMBOL = "BTC_USDT"
INTERVAL = 15 * 60

try:
    r = requests.get(
        f"{BASE}/api/v1/mth/matches/{SYMBOL}/",
        timeout=15,
        headers={"User-Agent": "ETH-WHALE-PAPER-TEST/1.0"},
    )
    print("STATUS:", r.status_code)
    r.raise_for_status()

    trades = r.json()
    trades = [
        t for t in trades
        if t.get("time") is not None
        and t.get("price") is not None
    ]
    trades.sort(key=lambda t: float(t["time"]))

    if not trades:
        print("NO VALID TRADES")
        raise SystemExit(0)

    first = float(trades[0]["time"])
    last = float(trades[-1]["time"])

    print("SYMBOL:", SYMBOL)
    print("VALID TRADES:", len(trades))
    print("OLDEST UTC:", datetime.fromtimestamp(
        first, timezone.utc
    ).isoformat())
    print("NEWEST UTC:", datetime.fromtimestamp(
        last, timezone.utc
    ).isoformat())
    print("COVERAGE MINUTES:", round((last - first) / 60, 2))

    candles = {}

    for t in trades:
        ts = float(t["time"])
        price = float(t["price"])
        bucket = int(ts // INTERVAL) * INTERVAL

        if bucket not in candles:
            candles[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "trades": 0,
            }

        c = candles[bucket]
        c["high"] = max(c["high"], price)
        c["low"] = min(c["low"], price)
        c["close"] = price
        c["trades"] += 1

    now = datetime.now(timezone.utc).timestamp()
    closed = [
        (ts, c) for ts, c in sorted(candles.items())
        if ts + INTERVAL <= now
    ]

    print("15M CANDLES FOUND:", len(candles))
    print("CLOSED CANDLES:", len(closed))

    for ts, c in sorted(candles.items())[-10:]:
        print(
            datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            c
        )

    if closed:
        ts, c = closed[-1]
        print("LATEST CLOSED CANDLE:", datetime.fromtimestamp(
            ts, timezone.utc
        ).isoformat(), c)

    if (last - first) < INTERVAL:
        print("WARNING: Trades do not cover a full 15-minute interval.")
    if len(closed) < 20:
        print("WARNING: Not enough closed candles for robust analysis.")

except Exception as e:
    print("TEST ERROR:", repr(e))
