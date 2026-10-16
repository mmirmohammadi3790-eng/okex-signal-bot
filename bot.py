
import os
import sys
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# IRAN STOCK WHALE - CONNECTION DIAGNOSTIC
# ONLY TESTS CONNECTIONS - NO TRADING
# ============================================================

BOT_NAME = "IRAN STOCK WHALE DIAGNOSTIC"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; MarketDiagnostic/1.0)",
    "Accept": "*/*",
})

def telegram_send(message):
    if not TOKEN or not CHAT_ID:
        logging.error("Telegram secrets are missing.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        logging.info("Telegram HTTP status: %s", response.status_code)
        response.raise_for_status()

        data = response.json()
        return bool(data.get("ok"))

    except Exception as exc:
        logging.error("Telegram failed: %s", str(exc)[:300])
        return False


def test_url(name, url, params=None):
    logging.info("Testing %s", name)

    try:
        response = session.get(
            url,
            params=params,
            timeout=(6, 12),
            allow_redirects=True,
        )

        content_type = response.headers.get(
            "Content-Type", "unknown"
        )

        result = (
            f"✅ {name}\n"
            f"HTTP: {response.status_code}\n"
            f"Final URL: {response.url[:180]}\n"
            f"Content-Type: {content_type}\n"
            f"Bytes: {len(response.content)}"
        )

        logging.info(
            "%s | HTTP=%s | type=%s | bytes=%s",
            name,
            response.status_code,
            content_type,
            len(response.content),
        )

        if response.status_code >= 400:
            result = result.replace("✅", "⚠️")

        if response.content:
            preview = response.text[:100].replace("\n", " ")
            logging.info("%s preview: %s", name, preview)

        return result

    except requests.exceptions.ConnectTimeout:
        result = f"❌ {name}\nConnection timeout"
    except requests.exceptions.ReadTimeout:
        result = f"❌ {name}\nRead timeout"
    except requests.exceptions.SSLError as exc:
        result = f"❌ {name}\nSSL error: {str(exc)[:150]}"
    except requests.exceptions.RequestException as exc:
        result = f"❌ {name}\n{type(exc).__name__}: {str(exc)[:180]}"
    except Exception as exc:
        result = f"❌ {name}\n{type(exc).__name__}: {str(exc)[:180]}"

    logging.warning("%s", result.replace("\n", " | "))
    return result


def main():
    logging.info("Starting %s", BOT_NAME)

    results = []
    results.append(
        "🐋 IRAN STOCK WHALE\n"
        "🧪 تست اتصال منابع داده\n"
        "🚫 سفارش واقعی: غیرفعال"
    )

    # Test the Telegram API independently.
    telegram_url = "https://api.telegram.org"
    results.append(
        test_url("Telegram API reachability", telegram_url)
    )

    market_params = {
        "market": 0,
        "withBestLimits": "false",
        "hEven": 0,
        "RefID": 0,
    }

    for i in range(9):
        market_params[f"paperTypes[{i}]"] = i + 1

    # Test the existing market-watch API.
    results.append(
        test_url(
            "TSETMC CDN API",
            "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch",
            params=market_params,
        )
    )

    # Test the alternative CDN hostname.
    results.append(
        test_url(
            "TSETMC CDN10 API",
            "https://cdn10.tsetmc.com/api/ClosingPrice/GetMarketWatch",
            params=market_params,
        )
    )

    # Test the legacy market-watch Excel endpoint.
    results.append(
        test_url(
            "TSETMC legacy Excel",
            "https://old.tsetmc.com/tsev2/excel/MarketWatchPlus.aspx",
            params={"d": 0},
        )
    )

    # Test the main TSETMC website separately.
    results.append(
        test_url(
            "TSETMC website",
            "https://www.tsetmc.com/",
        )
    )

    # Test the TSE website separately.
    results.append(
        test_url(
            "TSE website",
            "https://www.tse.ir/",
        )
    )

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = (
        "🐋 IRAN STOCK WHALE\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧪 گزارش تست اتصال\n"
        f"🕒 {timestamp}\n"
        "🚫 سفارش واقعی: خاموش\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(results)
    )

    # Keep Telegram messages within safe size limits.
    for start in range(0, len(message), 3500):
        telegram_send(message[start:start + 3500])

    print("\n" + message)
    logging.info("Diagnostic completed.")


if __name__ == "__main__":
    main()
