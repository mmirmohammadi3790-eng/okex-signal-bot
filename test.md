
import json
import time
import requests
from datetime import datetime, timezone

BASE = "https://api.bitpin.ir"
SYMBOL = "BTC_USDT"
TIMEFRAME = "15m"
MIN_CANDLES = 21
TIMEOUT = 12

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-History-Diagnostic/1.0",
    "Accept": "application/json",
})

# Diagnostic candidates only. HTTP 200 alone does not prove
# that an endpoint returns historical candles.
CANDIDATES = [
    (
        "/v1/mkt/market-candles/",
        {"symbol": SYMBOL, "resolution": TIMEFRAME, "limit": 50},
    ),
    (
        "/v1/mkt/candles/",
        {"symbol": SYMBOL, "resolution": TIMEFRAME, "limit": 50},
    ),
    (
        "/v1/mkt/market-candles/",
        {"market": SYMBOL, "interval": TIMEFRAME, "limit": 50},
    ),
    (
        "/v1/mkt/candles/",
        {"market": SYMBOL, "interval": TIMEFRAME, "limit": 50},
    ),
]

def inspect_payload(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in (
            "candles", "results", "data", "history", "items"
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in ("candles", "results", "items"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return nested

    return []

def candle_shape(item):
    if isinstance(item, dict):
        return list(item.keys())[:20]
    if isinstance(item, list):
        return f"list with {len(item)} fields"
    return type(item).__name__

def main():
    print("=" * 60)
    print("ETH WHALE | BITPIN HISTORY DIAGNOSTIC")
    print("Time:", datetime.now(timezone.utc).isoformat())
    print("Symbol:", SYMBOL)
    print("Timeframe:", TIMEFRAME)
    print("Target:", MIN_CANDLES, "closed candles")
    print("Real orders: DISABLED")
    print("=" * 60)

    found = False

    for path, params in CANDIDATES:
        url = BASE + path
        print("\nTesting:", url)
        print("Parameters:", params)

        try:
            response = session.get(
                url,
                params=params,
                timeout=TIMEOUT,
            )

            print("HTTP:", response.status_code)
            print("Final URL:", response.url)

            try:
                payload = response.json()
            except ValueError:
                print("Response is not JSON:")
                print(response.text[:500])
                continue

            print("Response type:", type(payload).__name__)

            candles = inspect_payload(payload)
            print("Recognized candle count:", len(candles))

            if candles:
                found = True
                print("First item structure:", candle_shape(candles[0]))
                print(
                    "Sample response:",
                    json.dumps(
                        candles[0],
                        ensure_ascii=False,
                    )[:700],
                )

                if len(candles) >= MIN_CANDLES:
                    print(
                        "Candidate returned at least 21 items. "
                        "Verify timestamps and OHLC fields before use."
                    )
                else:
                    print(
                        "Not enough items; this may not be a history endpoint."
                    )

            else:
                print(
                    "No recognized candle array. Response preview:"
                )
                print(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                    )[:700]
                )

        except requests.RequestException as exc:
            print("REQUEST ERROR:", repr(exc))

        time.sleep(0.5)

    print("\n" + "=" * 60)
    if found:
        print(
            "RESULT: At least one response contained a recognized list. "
            "This does NOT yet confirm valid historical candles."
        )
    else:
        print(
            "RESULT: No candidate returned a recognized candle list. "
            "Inspect the HTTP status and response bodies above."
        )
    print("No orders were placed.")

if __name__ == "__main__":
    main()
