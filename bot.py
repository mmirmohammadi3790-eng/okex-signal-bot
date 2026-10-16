
import os
import sys
import html
import logging
import requests
from datetime import datetime, timezone

# =====================================================
# 🐋 ETH WHALE | BITPIN TELEGRAM DESIGN & CONNECTION TEST
# PAPER ONLY — NO REAL ORDERS
# =====================================================

BITPIN_BASE = "https://api.bitpin.ir"

CAPITAL_USDT = 100.0
LEVERAGE = 3
POSITION_USDT = CAPITAL_USDT * LEVERAGE
PAPER_MODE = True

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEOUT = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("eth-whale")

session = requests.Session()
session.headers.update({"User-Agent": "EthWhale-PaperBot/4.0"})


def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe(value):
    return html.escape(str(value), quote=False)


def telegram_send(text):
    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN is missing.")
        return False

    if not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_CHAT_ID is missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = session.post(url, json=payload, timeout=TIMEOUT)
        log.info("Telegram HTTP status: %s", response.status_code)

        try:
            data = response.json()
        except ValueError:
            data = {}

        if not response.ok or not data.get("ok"):
            description = data.get("description", response.text[:500])
            log.error("Telegram send failed: %s", description)
            return False

        log.info("Telegram message sent successfully.")
        return True

    except requests.RequestException as exc:
        log.exception("Telegram connection failed: %s", exc)
        return False


def get_me():
    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN is missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe"

    try:
        response = session.get(url, timeout=TIMEOUT)
        log.info("Telegram getMe HTTP status: %s", response.status_code)

        if not response.ok:
            log.error("Telegram getMe failed: %s", response.text[:500])
            return False

        data = response.json()

        if not data.get("ok"):
            log.error("Telegram API rejected the token.")
            return False

        bot = data.get("result", {})
        log.info("Telegram bot verified: @%s", bot.get("username", "unknown"))
        return True

    except requests.RequestException as exc:
        log.exception("Telegram getMe connection failed: %s", exc)
        return False


def welcome_message():
    return (
        "🐋 <b>ETH WHALE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ <b>ربات سیگنال بیت‌پین</b>\n"
        "<i>Smart Market Watch • Paper Trading</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 <b>وضعیت اتصال: موفق</b>\n"
        "🧪 <b>حالت معاملات: آزمایشی</b>\n"
        "🔒 سفارش واقعی: <b>خاموش</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💼 <b>مدیریت سرمایه</b>\n"
        f"💵 سرمایه فرضی: <b>{CAPITAL_USDT:.2f} USDT</b>\n"
        f"⚡ اهرم فرضی: <b>{LEVERAGE}x</b>\n"
        f"📊 ارزش موقعیت فرضی: <b>{POSITION_USDT:.2f} USDT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📡 اتصال تلگرام: <b>فعال</b>\n"
        f"🕒 زمان تست: <code>{now_text()}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ این پیام فقط تست اتصال است.\n"
        "این نسخه به‌تنهایی سیگنال تولید نمی‌کند.\n"
        "🐋 <i>ETH WHALE • PAPER ONLY</i>"
    )


def main():
    if not PAPER_MODE:
        log.error("Safety check failed: PAPER_MODE must remain True.")
        sys.exit(1)

    log.info("Starting Eth Whale Telegram connection test.")
    log.info("Capital=%.2f | Leverage=%sx | Notional=%.2f",
             CAPITAL_USDT, LEVERAGE, POSITION_USDT)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error(
            "Missing secrets. Configure TELEGRAM_BOT_TOKEN "
            "and TELEGRAM_CHAT_ID in GitHub Actions Secrets."
        )
        sys.exit(1)

    if not get_me():
        log.error("Bot verification failed. Check the token.")
        sys.exit(1)

    if not telegram_send(welcome_message()):
        log.error(
            "Message delivery failed. Check chat ID, bot access, "
            "and Telegram API error above."
        )
        sys.exit(1)

    log.info("SUCCESS: Telegram welcome message delivered.")


if __name__ == "__main__":
    main()
