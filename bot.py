
import os
import requests
from datetime import datetime, timezone

# ============================================
# BITPIN API BASE-URL DIAGNOSTIC
# TEST ONLY - NO REAL ORDERS
# ============================================

TIMEOUT = 12

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TESTS = [
    (
        "Original API - markets",
        "https://api.bitpin.ir/v1/mkt/markets/",
        {"page": 1},
    ),
    (
        "Alternative API - markets",
        "https://api.bitpin.market/api/v1/mkt/markets/",
        {},
    ),
    (
        "Alternative API - tickers",
        "https://api.bitpin.market/api/v1/mkt/tickers/",
        {},
    ),
    (
        "Alternative API - candles",
        "https://api.bitpin.market/api/v1/mkt/candles/",
        {"market": "BTC_USDT", "interval": "1h"},
    ),
    (
        "Alternative API - OHLCV",
        "https://api.bitpin.market/api/v1/mkt/ohlcv/",
        {"market": "BTC_USDT", "interval": "1h"},
    ),
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-API-Diagnostic/4.0",
    "Accept": "application/json",
})

report = []


def log(message):
    print(message, flush=True)
    report.append(str(message))


def run_test(name, url, params):
    log("")
    log("=" * 48)
    log("TEST: " + name)
    log("URL: " + url)
    log("PARAMS: " + str(params))

    try:
        response = session.get(
            url,
            params=params,
            timeout=TIMEOUT,
        )

        log("HTTP STATUS: " + str(response.status_code))
        log("FINAL URL: " + response.url)
        log(
            "CONTENT TYPE: "
            + str(response.headers.get("Content-Type", ""))
        )

        try:
            data = response.json()
            log("JSON TYPE: " + type(data).__name__)

            if isinstance(data, dict):
                log("JSON KEYS: " + str(list(data.keys())[:30]))

                results = data.get("results")
                if isinstance(results, list):
                    log("RESULT COUNT: " + str(len(results)))
                    if results:
                        log("FIRST RESULT: " + repr(results[0])[:700])

                if "data" in data:
                    log("DATA SAMPLE: " + repr(data["data"])[:700])

            elif isinstance(data, list):
                log("ITEM COUNT: " + str(len(data)))
                if data:
                    log("FIRST ITEM: " + repr(data[0])[:700])

            else:
                log("JSON SAMPLE: " + repr(data)[:700])

        except ValueError:
            log("BODY: " + response.text[:500])

    except requests.RequestException as exc:
        log("REQUEST ERROR: " + repr(exc))


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("Telegram skipped: credentials missing.")
        return

    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"

    # Telegram messages are limited in length.
    chunks = [
        message[i:i + 3500]
        for i in range(0, len(message), 3500)
    ]

    for chunk in chunks:
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": chunk,
                },
                timeout=TIMEOUT,
            )
            print(
                "Telegram HTTP STATUS:",
                response.status_code,
                flush=True,
            )
        except requests.RequestException as exc:
            print("Telegram ERROR:", repr(exc), flush=True)


def main():
    log("BITPIN API BASE-URL DIAGNOSTIC")
    log("UTC: " + datetime.now(timezone.utc).isoformat())
    log("Mode: TEST ONLY")
    log("Real orders: OFF")

    for name, url, params in TESTS:
        run_test(name, url, params)

    log("")
    log("=" * 48)
    log("DIAGNOSTIC FINISHED")
    log("No orders were placed.")

    session.close()
    send_telegram("\n".join(report))


if __name__ == "__main__":
    main()
