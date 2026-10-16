
import requests
from datetime import datetime, timezone

BASE = "https://api.bitpin.ir"
TIMEOUT = 12

print("BITPIN MARKET DISCOVERY TEST")
print("UTC:", datetime.now(timezone.utc).isoformat())
print("MODE: READ ONLY")
print("REAL ORDERS: OFF")

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-ReadOnly-Diagnostic/1.0"
})

# 1. Find BTC_USDT market ID
print("\n=== 1. MARKET LOOKUP ===")

try:
    url = BASE + "/v1/mkt/markets/"
    response = session.get(
        url,
        params={"page": 1},
        timeout=TIMEOUT
    )
    print("MARKETS HTTP:", response.status_code)

    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict):
        markets = payload.get("results", [])
    elif isinstance(payload, list):
        markets = payload
    else:
        markets = []

    print("MARKETS RECEIVED:", len(markets))

    found = False
    for market in markets:
        code = market.get("code") or market.get("symbol")
        if code == "BTC_USDT":
            found = True
            print("BTC_USDT FOUND")
            print("MARKET ID:", market.get("id"))
            print("MARKET CODE:", code)
            print("MARKET NAME:", market.get("title"))
            print("MARKET FIELDS:", list(market.keys()))
            print("MARKET SAMPLE:", str(market)[:1200])
            break

    if not found:
        print("BTC_USDT NOT FOUND ON PAGE 1")

except Exception as error:
    print("MARKET ERROR:", repr(error)[:500])

# 2. Look for API documentation/schema
print("\n=== 2. API DOCUMENTATION DISCOVERY ===")

paths = [
    "/openapi.json",
    "/swagger.json",
    "/api/schema/",
    "/schema/",
    "/swagger/",
    "/api/docs/",
    "/docs/",
]

for path in paths:
    url = BASE + path
    try:
        response = session.get(url, timeout=TIMEOUT)
        content_type = response.headers.get(
            "content-type", ""
        )
        print("\nPATH:", path)
        print("HTTP:", response.status_code)
        print("CONTENT TYPE:", content_type)

        if response.status_code == 200:
            try:
                data = response.json()
                if isinstance(data, dict):
                    print("KEYS:", list(data.keys())[:20])
                    paths_data = data.get("paths")
                    if isinstance(paths_data, dict):
                        matches = [
                            p for p in paths_data
                            if any(word in p.lower()
                                   for word in (
                                       "candle", "ohlc",
                                       "chart", "kline"
                                   ))
                        ]
                        print("CHART PATHS:", matches[:30])
                else:
                    print("JSON TYPE:", type(data).__name__)
            except ValueError:
                print("BODY SAMPLE:", response.text[:250])

    except requests.RequestException as error:
        print("REQUEST ERROR:", str(error)[:250])

print("\nTEST FINISHED")
print("No trading orders were sent.")
