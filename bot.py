import requests

BASE = "https://api.bitpin.ir"

tests = [
    ("/v1/mkt/tickers/", {}),
    ("/v1/mkt/tickers", {}),
    ("/v1/mkt/markets/", {}),
    ("/v1/mth/orderbook/BTC_USDT/", {}),
]

for path, params in tests:
    try:
        r = requests.get(BASE + path, params=params, timeout=12)
        print("\nPATH:", r.url)
        print("STATUS:", r.status_code)
        print("BODY:", r.text[:500].replace("\n", " "))
    except Exception as e:
        print("\nERROR:", path, str(e)[:250])
