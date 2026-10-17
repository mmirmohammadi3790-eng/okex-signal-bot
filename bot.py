import requests

BASE = "https://api.bitpin.ir"
s = requests.Session()
s.headers.update({"User-Agent": "ETH-WHALE-PAPER-TEST/1.0"})

try:
    url = BASE + "/api/v1/mth/matches/BTC_USDT/"
    r = s.get(url, timeout=15)

    print("TRADES URL:", url)
    print("TRADES STATUS:", r.status_code)
    print("TRADES BODY:", r.text[:2000])

    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            print("TRADE COUNT:", len(data))
            if data:
                print("LATEST TRADE:", data[0])
        elif isinstance(data, dict):
            print("RESPONSE KEYS:", list(data.keys()))
            print("DATA SAMPLE:", str(data)[:1000])

except Exception as e:
    print("TEST ERROR:", repr(e))
