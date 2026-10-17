
import requests
from datetime import datetime, timezone
from collections import defaultdict

# =========================================================
# ETH WHALE | BITPIN TRADE & CANDLE TEST
# PAPER ONLY - NO REAL ORDERS
# =========================================================

BASE_URL = "https://api.bitpin.ir"
SYMBOL = "BTC_USDT"
INTERVAL_SECONDS = 15 * 60
TIMEOUT = 20

HEADERS = {
    "User-Agent": "ETH-WHALE-PAPER-TEST/1.0",
    "Accept": "application/json",
}


def utc_time(timestamp):
    return datetime.fromtimestamp(
        timestamp, timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def fetch_trades():
    url = f"{BASE_URL}/api/v1/mth/matches/{SYMBOL}/"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
    )

    print("TRADES URL:", url)
    print("TRADES STATUS:", response.status_code)

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise ValueError(
            "Unexpected API response: expected a list of trades"
        )

    valid = []

    for item in data:
        try:
            timestamp = float(item["time"])
            price = float(item["price"])

            if timestamp <= 0 or price <= 0:
                continue

            valid.append({
                "time": timestamp,
                "price": price,
                "amount": float(item.get("base_amount", 0) or 0),
                "side": str(item.get("side", "unknown")),
            })

        except (KeyError, TypeError, ValueError):
            continue

    valid.sort(key=lambda x: x["time"])
    return valid


def build_candles(trades):
    buckets = defaultdict(list)

    for trade in trades:
        bucket = (
            int(trade["time"] // INTERVAL_SECONDS)
            * INTERVAL_SECONDS
        )
        buckets[bucket].append(trade)

    candles = []

    for timestamp in sorted(buckets):
        items = buckets[timestamp]
        prices = [x["price"] for x in items]

        candles.append({
            "timestamp": timestamp,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "trades": len(items),
            "volume": sum(x["amount"] for x in items),
        })

    return candles


def main():
    print("=" * 55)
    print("🐋 ETH WHALE - BITPIN DATA TEST")
    print("MODE: PAPER ONLY")
    print("REAL ORDERS: OFF")
    print("SYMBOL:", SYMBOL)
    print("=" * 55)

    try:
        trades = fetch_trades()

        print("VALID TRADES:", len(trades))

        if not trades:
            print("RESULT: No valid trades returned.")
            return

        first_time = trades[0]["time"]
        last_time = trades[-1]["time"]

        coverage = max(
            0,
            (last_time - first_time) / 60
        )

        print("OLDEST TRADE:", utc_time(first_time))
        print("NEWEST TRADE:", utc_time(last_time))
        print("COVERAGE MINUTES:", round(coverage, 2))
        print("OLDEST PRICE:", trades[0]["price"])
        print("NEWEST PRICE:", trades[-1]["price"])

        candles = build_candles(trades)

        now = datetime.now(timezone.utc).timestamp()

        # Only candles whose full 15-minute period has ended.
        closed_candles = [
            candle for candle in candles
            if candle["timestamp"] + INTERVAL_SECONDS <= now
        ]

        print("15M CANDLES FOUND:", len(candles))
        print("CLOSED CANDLES:", len(closed_candles))

        print("\n--- RECENT CANDLES (UTC) ---")

        for candle in candles[-10:]:
            candle_end = (
                candle["timestamp"] + INTERVAL_SECONDS
            )
            status = (
                "CLOSED"
                if candle_end <= now
                else "INCOMPLETE"
            )

            print(
                utc_time(candle["timestamp"]),
                "|", status,
                "| O:", round(candle["open"], 8),
                "| H:", round(candle["high"], 8),
                "| L:", round(candle["low"], 8),
                "| C:", round(candle["close"], 8),
                "| TRADES:", candle["trades"],
                "| VOLUME:", round(candle["volume"], 8),
            )

        if closed_candles:
            latest = closed_candles[-1]

            print("\n--- LATEST CLOSED CANDLE ---")
            print("TIME:", utc_time(latest["timestamp"]))
            print("OPEN:", latest["open"])
            print("HIGH:", latest["high"])
            print("LOW:", latest["low"])
            print("CLOSE:", latest["close"])
            print("TRADES:", latest["trades"])

        print("\n--- DATA QUALITY ---")

        if coverage < 15:
            print("WARNING: Coverage is shorter than 15 minutes.")
        else:
            print("Coverage spans at least 15 minutes.")

        if len(closed_candles) < 20:
            print(
                "WARNING: Fewer than 20 closed candles. "
                "Insufficient for robust trend/support analysis."
            )
        else:
            print("At least 20 closed candles are available.")

        print(
            "\nIMPORTANT: This uses only the returned recent trades. "
            "It cannot reconstruct missing historical trades."
        )
        print("TEST FINISHED. NO ORDERS WERE PLACED.")

    except requests.RequestException as exc:
        print("NETWORK/API ERROR:", repr(exc))

    except (ValueError, TypeError) as exc:
        print("DATA ERROR:", repr(exc))

    except Exception as exc:
        print("UNEXPECTED ERROR:", repr(exc))


if __name__ == "__main__":
    main()
