
import requests
import json
from datetime import datetime, timezone, timedelta

BASE_URL = "https://api.bitpin.org"
SYMBOL = "BTC_USDT"

# فقط بررسی مسیرهای احتمالی؛ هیچ سفارشی ثبت نمی‌شود.
CANDIDATES = [
    (
        "/v1/mkt/market-candles/",
        {"symbol": SYMBOL, "resolution": "15m", "limit": 50},
    ),
    (
        "/v1/mkt/candles/",
        {"symbol": SYMBOL, "resolution": "15m", "limit": 50},
    ),
    (
        "/v1/mkt/market-candles/",
        {"market": SYMBOL, "interval": "15m", "limit": 50},
    ),
    (
        "/v1/mkt/candles/",
        {"market": SYMBOL, "interval": "15m", "limit": 50},
    ),
]

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/1.0",
    "Accept": "application/json",
})

print("=" * 60)
print("ETH WHALE - BITPIN CANDLE API DIAGNOSTIC")
print("Paper mode: ON | Real orders: OFF")
print("Time:", datetime.now(timezone.utc).isoformat())
print("=" * 60)

success = False

for path, params in CANDIDATES:
    url = BASE_URL + path
    print("\nTesting:", url)
    print("Params:", params)

    try:
        response = session.get(url, params=params, timeout=15)
        print("HTTP:", response.status_code)
        print("Final URL:", response.url)
        print("Content-Type:", response.headers.get("Content-Type"))

        try:
            data = response.json()
            if isinstance(data, dict):
                print("Response keys:", list(data.keys()))
            elif isinstance(data, list):
                print("Response type: list")
                print("List length:", len(data))
            else:
                print("Response type:", type(data).__name__)

            print("Sample response:")
            print(json.dumps(data, ensure_ascii=False)[:1800])

            if response.ok:
                print("HTTP request succeeded; endpoint still needs candle validation.")
                success = True
        except ValueError:
            print("Non-JSON response:")
            print(response.text[:800])

    except requests.RequestException as exc:
        print("REQUEST ERROR:", repr(exc))

print("\n" + "=" * 60)
print("Diagnostic finished.")
print("Any HTTP 200 response must still be checked for real OHLC candle data.")
print("No orders were submitted.")
print("=" * 60)
