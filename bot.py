
import os
import requests
from datetime import datetime, timezone

# ============================================================
# BITPIN CANDLE API DIAGNOSTIC
# TEST ONLY - NO REAL ORDERS
# ============================================================

BITPIN_BASE = "https://api.bitpin.ir"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEOUT = 15

TESTS = [
    (
        "/api/v1/currencies/candles",
        {"symbol": "BTC_USDT", "tf": "1h"},
    ),
    (
        "/api/v1/currencies/candles/",
        {"symbol": "BTC_USDT", "tf": "1h"},
    ),
    (
        "/api/v1/currencies/candles",
        {"symbol": "BTC_IRT", "tf": "1h"},
    ),
]


def send_telegram(message):
    """Send diagnostic report to Telegram; no trading actions."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram skipped: credentials are missing.")
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

        print("Telegram HTTP status:", response.status_code)

        if response.status_code != 200:
            print("Telegram response:", response.text[:500])

    except requests.RequestException as exc:
        print("Telegram error:", repr(exc))


def main():
    print("=" * 55)
    print("BITPIN CANDLE API DIAGNOSTIC")
    print("UTC:", datetime.now(timezone.utc).isoformat())
    print("Mode: TEST ONLY")
    print("Real orders: OFF")
    print("=" * 55)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Bitpin-API-Diagnostic/1.0",
        "Accept": "application/json",
    })

    report = [
        "BITPIN CANDLE API DIAGNOSTIC",
        "Mode: TEST ONLY",
        "Real orders: OFF",
        "UTC: " + datetime.now(timezone.utc).isoformat(),
        "",
    ]

    successful_responses = 0

    for number, (path, params) in enumerate(TESTS, start=1):
        url = BITPIN_BASE + path

        print("\n" + "=" * 55)
        print("TEST:", number)
        print("URL:", url)
        print("PARAMS:", params)

        report.append("TEST " + str(number))
        report.append("URL: " + url)
        report.append("PARAMS: " + str(params))

        try:
            response = session.get(
                url,
                params=params,
                timeout=TIMEOUT,
            )

            print("HTTP STATUS:", response.status_code)
            print("FINAL URL:", response.url)
            print("RESPONSE:", response.text[:1200])

            report.append("HTTP STATUS: " + str(response.status_code))
            report.append("FINAL URL: " + response.url)
            report.append("RESPONSE: " + response.text[:700])

            if response.status_code == 200:
                successful_responses += 1

                try:
                    data = response.json()
                    print("JSON TYPE:", type(data).__name__)
                    print("JSON PREVIEW:", repr(data)[:1200])
                    report.append("JSON TYPE: " + type(data).__name__)
                    report.append("JSON PREVIEW: " + repr(data)[:500])

                except ValueError:
                    print("Response is not valid JSON.")
                    report.append("Response is not valid JSON.")

        except requests.RequestException as exc:
            error = repr(exc)
            print("REQUEST ERROR:", error)
            report.append("REQUEST ERROR: " + error)

    session.close()

    report.append("")
    report.append(
        "HTTP 200 responses: "
        + str(successful_responses)
        + " of "
        + str(len(TESTS))
    )
    report.append("Real orders: OFF")
    report.append("Diagnostic finished.")

    final_report = "\n".join(report)

    print("\n" + "=" * 55)
    print(final_report)
    print("=" * 55)

    send_telegram(final_report)


if __name__ == "__main__":
    main()
