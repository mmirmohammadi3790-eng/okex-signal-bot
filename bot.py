
import requests
from datetime import datetime, timezone

TIMEOUT = 12
SYMBOL = "BTC_USDT"

TESTS = [
    (
        "https://api.bitpin.market/api/v1/mkt/candles/",
        {"market": SYMBOL, "tf": "1h"},
    ),
    (
        "https://api.bitpin.market/api/v1/mkt/candles/",
        {"symbol": SYMBOL, "tf": "1h"},
    ),
    (
        "https://api.bitpin.market/api/v1/mkt/candles/",
        {"market_id": 2, "tf": "1h"},
    ),
    (
        "https://api.bitpin.market/api/v1/mkt/candles/",
        {"market": 2, "timeframe": "1h"},
    ),
    (
        "https://api.bitpin.market/api/v1/currencies/candles",
        {"symbol": SYMBOL, "tf": "1h"},
    ),
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-ReadOnly-Test/1.0"
})

print("BITPIN CANDLE PARAMETER TEST")
print("UTC:", datetime.now(timezone.utc).isoformat())
print("READ ONLY: YES")
print("REAL ORDERS: DISABLED")

for url, params in TESTS:
    print("\n" + "-" * 50)
    print("URL:", url)
    print("PARAMS:", params)

    try:
        response = session.get(
            url,
            params=params,
            timeout=TIMEOUT
        )

        print("HTTP:", response.status_code)
        print("FINAL URL:", response.url)

        try:
            data = response.json()
            print("JSON TYPE:", type(data).__name__)

            if isinstance(data, dict):
                print("KEYS:", list(data.keys())[:20])

                rows = data.get("data", data.get("results"))
                if isinstance(rows, list):
                    print("CANDLE COUNT:", len(rows))
                    if rows:
                        print("FIRST ROW:", str(rows[0])[:500])
                else:
                    print("SAMPLE:", str(data)[:500])

            elif isinstance(data, list):
                print("ROW COUNT:", len(data))
                if data:
                    print("FIRST ROW:", str(data[0])[:500])

            else:
                print("SAMPLE:", str(data)[:300])

        except ValueError:
            print("BODY:", response.text[:250])

    except requests.RequestException as error:
        print("REQUEST ERROR:", str(error)[:250])

print("\nTEST COMPLETE")
print("No trading orders were sent.")
