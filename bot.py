import requests

BASE = "https://api.bitpin.ir"
s = requests.Session()
s.headers.update({"User-Agent": "ETH-WHALE-PAPER-TEST/1.0"})

try:
    r = s.get(
        BASE + "/v1/mkt/markets/",
        params={"page": 1},
        timeout=15
    )
    print("MARKETS STATUS:", r.status_code)
    r.raise_for_status()
    data = r.json()

    markets = data.get("results", [])
    market = next(
        (m for m in markets if m.get("code") == "BTC_USDT"),
        None
    )

    if not market:
        print("BTC_USDT NOT FOUND ON PAGE 1")
        print("NEXT PAGE:", data.get("next"))
    else:
        print("MARKET ID:", market.get("id"))
        print("MARKET CODE:", market.get("code"))
        print("PRICE:", market.get("price"))
        print("PRICE INFO:", market.get("price_info"))

        mid = market["id"]

        paths = [
            f"/api/v2/mth/orderbook/{mid}/buy/",
            f"/api/v2/mth/orderbook/{mid}/sell/",
            f"/api/v1/mth/orderbook/{market['code']}/",
        ]

        for path in paths:
            try:
                x = s.get(BASE + path, timeout=10)
                print("\nPATH:", path)
                print("STATUS:", x.status_code)
                print("BODY:", x.text[:300])
            except Exception as e:
                print("ERROR:", path, str(e)[:150])

except Exception as e:
    print("TEST ERROR:", repr(e))
