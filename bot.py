
import requests
from datetime import datetime, timezone

BASE = "https://api.bitpin.ir"

tests = [
    ("/v1/mkt/candles/", {"market": "BTC_USDT", "interval": "1h"}),
    ("/v1/mkt/ohlcv/", {"market": "BTC_USDT", "interval": "1h"}),
    ("/api/v1/mkt/candles/", {"market": "BTC_USDT", "interval": "1h"}),
    ("/v1/mkt/candles/", {"symbol": "BTC_USDT", "interval": "1h"}),
    ("/v1/mkt/ohlcv/", {"symbol": "BTC_USDT", "interval": "1h"}),
]

print("BITPIN CANDLE API DIAGNOSTIC")
print(datetime.now(timezone.utc).isoformat())

for path, params in tests:
    print("\n" + "=" * 45)
    print("URL:", BASE + path)
    print("PARAMS:", params)

    try:
        response = requests.get(
            BASE + path,
            params=params,
            timeout=12,
            headers={"User-Agent": "Bitpin-API-Diagnostic/1.0"}
        )

        print("HTTP STATUS:", response.status_code)
        print("FINAL URL:", response.url)
        print("RESPONSE:", response.text[:1200])

    except requests.RequestException as exc:
        print("REQUEST ERROR:", repr(exc))

print("\nDIAGNOSTIC FINISHED")
print("No orders were placed.")
