
import os
import requests
from datetime import datetime, timezone

# ==========================================
# BITPIN CANDLE DIAGNOSTIC
# TEST ONLY - NO REAL ORDERS
# ==========================================

BASE = "https://api.bitpin.ir"
TIMEOUT = 12

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TESTS = [
    (
        "A",
        "/v1/mkt/candles/",
        {"market": "BTC_USDT", "interval": "1h"},
    ),
    (
        "B",
        "/v1/mkt/ohlcv/",
        {"market": "BTC_USDT", "interval": "1h"},
    ),
    (
        "C",
        "/api/v1/currencies/candles",
        {"symbol": "BTC_USDT", "tf": "1h"},
    ),
    (
        "D",
        "/api/v1/mkt/candles/",
        {"market": "BTC_USDT", "interval": "1h"},
    ),
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-Candle-Diagnostic/3.0",
    "Accept": "application/json",
})

report = []


def log(text):
    print(text, flush=True)
    report.append(str(text))


def test_route(name, path, params):
    url = BASE + path

    log("")
    log("-" * 45)
    log("TEST " + name)
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
        log("CONTENT TYPE: " + str(
            response.headers.get("Content-Type", "")
        ))

        if response.status_code == 200:
            try:
                data = response.json()
                log("JSON TYPE: " + type(data).__name__)
                log("JSON SAMPLE: " + repr(data)[:1000])
            except ValueError:
                log("BODY: " + response.text[:500])
        else:
            log("BODY: " + response.text[:300])

    except requests.RequestException as exc:
        log("REQUEST ERROR: " + repr(exc))


def send_report(message):
    if not TOKEN or not CHAT_ID:
        log("Telegram skipped: token or chat ID missing.")
        return

    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"

    # Split the report to stay within Telegram's message limit.
    chunks = [
        message[i:i + 3500]
        for i in range(0, len(message), 3500)
    ]

    for chunk in chunks:
        try:
            response = requests.post(
                url,
                data={"chat_id": CHAT_ID, "text": chunk},
                timeout=TIMEOUT,
            )
            print(
                "Telegram HTTP status:",
                response.status_code,
                flush=True,
            )
        except requests.RequestException as exc:
            print("Telegram error:", repr(exc), flush=True)


def main():
    log("BITPIN CANDLE API DIAGNOSTIC")
    log("UTC: " + datetime.now(timezone.utc).isoformat())
    log("Mode: TEST ONLY")
    log("Real orders: OFF")

    for name, path, params in TESTS:
        test_route(name, path, params)

    log("")
    log("=" * 45)
    log("DIAGNOSTIC FINISHED")
    log("No orders were placed.")

    session.close()
    send_report("\n".join(report))


if __name__ == "__main__":
    main()
