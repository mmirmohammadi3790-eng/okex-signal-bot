
import requests
from datetime import datetime, timezone

BASE = "https://api.bitpin.market"
TIMEOUT = 12
SYMBOL = "BTC_USDT"

# مسیرهای احتمالی؛ هیچ‌کدام از قبل تأییدشده نیستند.
CANDIDATES = [
    ("/api/v1/mkt/candles/", {"market": SYMBOL, "interval": "1h"}),
    ("/api/v1/mkt/candles/", {"symbol": SYMBOL, "interval": "1h"}),
    ("/api/v1/mkt/candles/", {"market_id": 2, "interval": "1h"}),
    ("/api/v1/mkt/ohlcv/", {"market": SYMBOL, "interval": "1h"}),
    ("/api/v1/mkt/ohlcv/", {"symbol": SYMBOL, "interval": "1h"}),
    ("/api/v1/mkt/klines/", {"symbol": SYMBOL, "interval": "1h"}),
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-ReadOnly-Diagnostic/1.0"
})

print("BITPIN CANDLE ROUTE TEST")
print("UTC:", datetime.now(timezone.utc).isoformat())
print("MODE: READ ONLY")
print("REAL ORDERS: OFF")

for path, params in CANDIDATES:
    url = BASE + path
    print("\n" + "=" * 45)
    print("PATH:", path)
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
                print("KEYS:", list(data.keys())[:25])
                print("SAMPLE:", str(data)[:600])
            elif isinstance(data, list):
                print("ITEM COUNT:", len(data))
                if data:
                    print("FIRST ITEM:", str(data[0])[:600])
            else:
                print("SAMPLE:", str(data)[:300])

        except ValueError:
            print("BODY:", response.text[:300])

    except requests.RequestException as error:
        print("REQUEST ERROR:", str(error)[:300])

print("\nTEST FINISHED")
print("No orders were sent.")
