
import requests

BASE = "https://api.bitpin.ir"
paths = [
    "/v1/mkt/markets/",
    "/v1/mkt/tickers/",
    "/v1/mkt/ohlc/",
    "/v1/mkt/candles/",
]

for path in paths:
    try:
        r = requests.get(
            BASE + path,
            params={"symbol": "BTC_USDT", "interval": "15"},
            timeout=10,
        )
        print("\nPATH:", path)
        print("STATUS:", r.status_code)
        print("BODY:", r.text[:350])
    except Exception as e:
        print(path, "ERROR:", str(e)[:200])
