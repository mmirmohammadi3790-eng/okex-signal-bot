import requests
from datetime import datetime, timezone

BASE = "https://api.bitpin.market"
TIMEOUT = 10

print("BITPIN CANDLE API TEST")
print("UTC:", datetime.now(timezone.utc).isoformat())
print("MODE: DIAGNOSTIC ONLY")
print("REAL ORDERS: OFF")

tests = [
    ("candles market 1h", "/api/v1/mkt/candles/",
     {"market": "BTC_USDT", "interval": "1h"}),
    ("candles symbol 1h", "/api/v1/mkt/candles/",
     {"symbol": "BTC_USDT", "interval": "1h"}),
    ("candles market 60", "/api/v1/mkt/candles/",
     {"market": "BTC_USDT", "interval": "60"}),
    ("candles symbol 60", "/api/v1/mkt/candles/",
     {"symbol": "BTC_USDT", "interval": "60"}),
    ("ohlcv market 1h", "/api/v1/mkt/ohlcv/",
     {"market": "BTC_USDT", "interval": "1h"}),
    ("ohlcv symbol 1h", "/api/v1/mkt/ohlcv/",
     {"symbol": "BTC_USDT", "interval": "1h"}),
]

session = requests.Session()
session.headers.update({"User-Agent": "Bitpin-Candle-Diagnostic/1.0"})

for name, path, params in tests:
    url = BASE + path
    print("\n---", name, "---")
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
        print("CONTENT TYPE:",
              response.headers.get("content-type", ""))

        try:
            data = response.json()
            print("JSON TYPE:", type(data).__name__)

            if isinstance(data, dict):
                print("KEYS:", list(data.keys())[:15])
                for key, value in data.items():
                    if isinstance(value, list):
                        print("LIST FIELD:", key)
                        print("ITEM COUNT:", len(value))
                        if value:
                            print("SAMPLE:", str(value[0])[:500])
                        break
                else:
                    print("BODY:", str(data)[:500])

            elif isinstance(data, list):
                print("ITEM COUNT:", len(data))
                if data:
                    print("SAMPLE:", str(data[0])[:500])
            else:
                print("BODY:", str(data)[:300])

        except ValueError:
            print("BODY:", response.text[:300])

    except requests.RequestException as error:
        print("REQUEST ERROR:", str(error)[:300])

print("\nTEST FINISHED")
print("No trading orders were sent.")
