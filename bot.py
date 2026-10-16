
import requests
from datetime import datetime, timezone

BASE = "https://api.bitpin.market"
SYMBOLS = ["BTC_USDT", "ETH_USDT"]
TIMEOUT = 15

print("BITPIN RECENT TRADES TEST")
print("UTC:", datetime.now(timezone.utc).isoformat())
print("MODE: TEST ONLY")
print("REAL ORDERS: OFF")

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-ReadOnly-Diagnostic/1.0"
})

for symbol in SYMBOLS:
    url = f"{BASE}/api/v1/mth/matches/{symbol}/"

    print("\n" + "=" * 45)
    print("SYMBOL:", symbol)
    print("URL:", url)

    try:
        response = session.get(url, timeout=TIMEOUT)
        print("HTTP STATUS:", response.status_code)
        print("FINAL URL:", response.url)
        print("CONTENT TYPE:",
              response.headers.get("content-type", ""))

        try:
            data = response.json()
        except ValueError:
            print("RESPONSE:", response.text[:500])
            continue

        print("JSON TYPE:", type(data).__name__)

        if isinstance(data, list):
            print("TRADE COUNT:", len(data))
            if data:
                print("FIRST TRADE:", str(data[0])[:1000])
            else:
                print("EMPTY TRADE LIST")

        elif isinstance(data, dict):
            print("JSON KEYS:", list(data.keys())[:20])
            print("RESPONSE:", str(data)[:1000])

        else:
            print("RESPONSE:", str(data)[:500])

    except requests.RequestException as error:
        print("REQUEST ERROR:", str(error)[:500])

print("\nTEST FINISHED")
print("No trading orders were sent.")
