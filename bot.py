import requests

BASE = "https://api.bitpin.ir"
s = requests.Session()
s.headers.update({"User-Agent": "ETH-WHALE-PAPER-TEST/1.0"})

try:
    r = s.get(BASE + "/v1/mkt/markets/", timeout=15)
    print("MARKETS:", r.status_code)
    r.raise_for_status()

    markets = r.json().get("results", [])
    market = next(
        (m for m in markets if m.get("code") == "BTC_USDT"),
        None
    )

    if not market:
        print("BTC_USDT NOT FOUND")
        raise SystemExit(0)

    market_id = market["id"]
    print("MARKET:", market["code"])
    print("ID:", market_id)

    url = f"{BASE}/api/v1/mth/matches/{market_id}/"
    r = s.get(url, timeout=15)

    print("TRADES URL:", url)
    print("TRADES STATUS:", r.status_code)
    print("TRADES BODY:", r.text[:1500])

except Exception as e:
    print("ERROR:", repr(e))
