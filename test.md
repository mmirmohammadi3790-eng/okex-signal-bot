
import json
import requests
from datetime import datetime, timezone

BASE_URL = "https://api.bitpin.org"
SYMBOL = "BTC_USDT"

CANDIDATES = [
    ("/v1/mkt/market-candles/", {
        "symbol": SYMBOL, "resolution": "15m", "limit": 50
    }),
    ("/v1/mkt/candles/", {
        "symbol": SYMBOL, "resolution": "15m", "limit": 50
    }),
    ("/v1/mkt/market-candles/", {
        "market": SYMBOL, "interval": "15m", "limit": 50
    }),
    ("/v1/mkt/candles/", {
        "market": SYMBOL, "interval": "15m", "limit": 50
    }),
]

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/1.0",
    "Accept": "application/json",
})

def print_json(data):
    try:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2500])
    except Exception:
        print(str(data)[:2500])

print("=" * 60)
print("BITPIN CANDLE API DIAGNOSTIC")
print("UTC:", datetime.now(timezone.utc).isoformat())
print("Symbol:", SYMBOL)
print("Paper mode: ON")
print("Real orders: OFF")
print("=" * 60)

for path, params in CANDIDATES:
    url = BASE_URL + path
    print("\n" + "-" * 60)
    print("URL:", url)
    print("PARAMS:", params)

    try:
        response = session.get(url, params=params, timeout=15)
        print("HTTP:", response.status_code)
        print("FINAL URL:", response.url)
        print("CONTENT TYPE:", response.headers.get("Content-Type"))

        try:
            data = response.json()
        except ValueError:
            print("RESPONSE TEXT:")
            print(response.text[:1000])
            continue

        print("RESPONSE TYPE:", type(data).__name__)

        if isinstance(data, dict):
            print("RESPONSE KEYS:", list(data.keys()))

        print("SAMPLE RESPONSE:")
        print_json(data)

        if response.ok:
            print("HTTP_SUCCESS: True")
        else:
            print("HTTP_SUCCESS: False")

    except requests.RequestException as exc:
        print("REQUEST ERROR:", repr(exc))

print("\nDIAGNOSTIC FINISHED")
print("No trades or orders were submitted.")
