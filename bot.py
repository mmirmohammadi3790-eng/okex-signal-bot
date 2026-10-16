
import os
import requests
from datetime import datetime, timezone

# ============================================================
# BITPIN API DIAGNOSTIC
# PAPER / TEST ONLY
# NO ORDERS - NO API KEYS REQUIRED
# ============================================================

BASE = "https://api.bitpin.ir"
TIMEOUT = 15

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-Diagnostic/2.0",
    "Accept": "application/json",
})

report = []


def log(message):
    print(message)
    report.append(str(message))


def test_get(label, path, params=None):
    url = BASE + path

    log("\n" + "=" * 50)
    log("TEST: " + label)
    log("URL: " + url)
    log("PARAMS: " + str(params or {}))

    try:
        response = session.get(
            url,
            params=params or {},
            timeout=TIMEOUT,
        )

        log("HTTP STATUS: " + str(response.status_code))
        log("FINAL URL: " + response.url)
        log("CONTENT TYPE: " + str(
            response.headers.get("Content-Type", "")
        ))

        body = response.text[:1800]
        log("RESPONSE PREVIEW: " + body)

        if response.status_code == 200:
            try:
                data = response.json()
                log("JSON TYPE: " + type(data).__name__)

                if isinstance(data, dict):
                    log("JSON KEYS: " + str(list(data.keys())[:40]))

                    results = data.get("results")
                    if isinstance(results, list):
                        log("RESULT COUNT: " + str(len(results)))

                        for item in results[:3]:
                            if isinstance(item, dict):
                                log("SAMPLE ITEM: " + str({
                                    key: item.get(key)
                                    for key in (
                                        "id", "code", "symbol",
                                        "title", "price"
                                    )
                                    if key in item
                                }))

                elif isinstance(data, list):
                    log("ITEM COUNT: " + str(len(data)))
                    if data:
                        log("FIRST ITEM: " + str(data[0])[:1000])

            except ValueError:
                log("WARNING: HTTP 200 but response is not JSON.")

        return response.status_code

    except requests.RequestException as exc:
        log("REQUEST ERROR: " + repr(exc))
        return None


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("\nTelegram skipped: credentials missing.")
        return

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4000],
            },
            timeout=TIMEOUT,
        )

        print("Telegram status:", response.status_code)

    except requests.RequestException as exc:
        print("Telegram error:", repr(exc))


def main():
    log("BITPIN API DIAGNOSTIC")
    log("UTC: " + datetime.now(timezone.utc).isoformat())
    log("Mode: TEST ONLY")
    log("Real orders: OFF")

    # Known public market-list endpoint from Bitpin API examples
    test_get(
        "Public markets",
        "/v1/mkt/markets/",
        {"page": 1},
    )

    # Previously tested candle routes
    test_get(
        "Candle route A",
        "/v1/mkt/candles/",
        {"market": "BTC_USDT", "interval": "1h"},
    )

    test_get(
        "Candle route B",
        "/v1/mkt/ohlcv/",
        {"market": "BTC_USDT", "interval": "1h"},
    )

    test_get(
        "Candle route C",
        "/api/v1/currencies/candles",
        {"symbol": "BTC_USDT", "tf": "1h"},
    )

    test_get(
        "Candle route D",
        "/api/v1/mkt/candles/",
        {"market": "BTC_USDT", "interval": "1h"},
    )

    log("\n" + "=" * 50)
    log("DIAGNOSTIC FINISHED")
    log("No orders were placed.")
    log("Do not use candle signals until valid candle data is confirmed.")

    session.close()
    send_telegram("\n".join(report))


if __name__ == "__main__":
    main()
