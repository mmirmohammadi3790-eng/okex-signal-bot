import requests

BASE = "https://api.bitpin.ir"
s = requests.Session()
s.headers.update({"User-Agent": "ETH-WHALE-PAPER-TEST/1.0"})

# 1) دریافت قیمت از فهرست بازارها
r = s.get(BASE + "/v1/mkt/markets/", timeout=15)
print("MARKETS:", r.status_code)
r.raise_for_status()

markets = r.json().get("results", [])
m = next((x for x in markets if x.get("code") == "BTC_USDT"), None)

if m:
    print("BTC MARKET:", m.get("code"))
    print("PRICE:", m.get("price"))
    print("PRICE INFO:", m.get("price_info"))
else:
    print("BTC_USDT NOT FOUND")

# 2) دریافت دفتر سفارش
url = BASE + "/api/v1/mth/orderbook/BTC_USDT/"
r = s.get(url, timeout=15)
print("\nORDERBOOK:", r.status_code)
r.raise_for_status()

book = r.json()
print("BEST BID:", book.get("bids", [])[:1])
print("BEST ASK:", book.get("asks", [])[:1])
