
# -*- coding: utf-8 -*-
"""
ETH WHALE | BITPIN SMART MARKET WATCH
Paper signals only - NO REAL ORDERS
Designed for GitHub Actions
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone

import requests


# ============================================================
# CONFIGURATION
# ============================================================

BOT_NAME = "ETH WHALE"
BITPIN_BASE = "https://api.bitpin.ir"

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)
TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID", "").strip()
    or os.getenv("CHAT_ID", "").strip()
)

# Simulation settings
PAPER_MODE = True
REAL_ORDERS_ENABLED = False
CAPITAL_USDT = 48.0
LEVERAGE = 3
MAX_MARKETS = 250
MAX_SIGNALS = 5

# Balanced filters
MIN_SCORE = 65
STRONG_SCORE = 80
MIN_ABS_CHANGE = 0.40
MAX_ABS_CHANGE = 20.0

# Risk parameters
STOP_PERCENT = 1.5
TP1_PERCENT = 1.5
TP2_PERCENT = 3.0
TP3_PERCENT = 4.5

REQUEST_TIMEOUT = 15
MAX_MESSAGE_LENGTH = 3900

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("eth-whale")


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/1.0",
    "Accept": "application/json",
})


def http_get(url, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error(
            "Telegram credentials missing. "
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    chunks = [
        message[i:i + MAX_MESSAGE_LENGTH]
        for i in range(0, len(message), MAX_MESSAGE_LENGTH)
    ]

    success = True

    for chunk in chunks:
        try:
            response = SESSION.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()

            result = response.json()
            if not result.get("ok", False):
                log.error("Telegram rejected message: %s", result)
                success = False

        except requests.RequestException as exc:
            log.error("Telegram send failed: %s", exc)
            success = False

    return success


# ============================================================
# FLEXIBLE API RESPONSE PARSING
# ============================================================

def unwrap_list(data):
    """Extract a list from common API response structures."""
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "results",
            "data",
            "markets",
            "tickers",
            "list",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in ("results", "data", "list"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return nested

                # Ticker APIs may return a symbol-keyed dictionary.
                converted = []
                for symbol, item in value.items():
                    if isinstance(item, dict):
                        item = dict(item)
                        item.setdefault("symbol", symbol)
                        converted.append(item)

                if converted:
                    return converted

        # Some endpoints return symbol-keyed dictionaries directly.
        converted = []
        for symbol, value in data.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("symbol", symbol)
                converted.append(item)

        if converted:
            return converted

    return []


def to_float(value):
    try:
        if value is None or value == "":
            return None
        number = float(str(value).replace(",", ""))
        if number != number or abs(number) == float("inf"):
            return None
        return number
    except (TypeError, ValueError):
        return None


def first_number(item, keys):
    for key in keys:
        value = to_float(item.get(key))
        if value is not None:
            return value
    return None


def normalize_symbol(item):
    symbol = (
        item.get("symbol")
        or item.get("code")
        or item.get("market")
        or item.get("name")
        or ""
    )

    if isinstance(symbol, dict):
        symbol = (
            symbol.get("symbol")
            or symbol.get("code")
            or ""
        )

    symbol = str(symbol).upper().strip()
    symbol = symbol.replace("/", "_").replace("-", "_")

    return symbol


def normalize_ticker(item):
    symbol = normalize_symbol(item)

    # Only quote markets priced in USDT.
    if not symbol:
        return None

    if not (
        symbol.endswith("_USDT")
        or symbol.endswith("USDT")
    ):
        return None

    price = first_number(item, (
        "last",
        "last_price",
        "lastPrice",
        "price",
        "close",
        "c",
    ))

    change = first_number(item, (
        "change",
        "change_percent",
        "price_change_percent",
        "priceChangePercent",
        "change24h",
        "daily_change",
        "daily_change_percent",
        "percent_change",
    ))

    # Some APIs use a fraction rather than a percentage.
    if change is not None and abs(change) < 1:
        change *= 100

    volume = first_number(item, (
        "quote_volume",
        "quoteVolume",
        "volume_24h",
        "volume24h",
        "volume",
        "base_volume",
        "baseVolume",
    ))

    if price is None or price <= 0:
        return None

    return {
        "symbol": symbol.replace("_", "-"),
        "price": price,
        "change": change,
        "volume": volume,
    }


# ============================================================
# BITPIN PUBLIC MARKET DATA
# ============================================================

def get_tickers():
    """
    Try public Bitpin ticker endpoints.
    If an endpoint fails, try the next one.
    """

    endpoints = [
        f"{BITPIN_BASE}/api/v1/mkt/tickers/",
        f"{BITPIN_BASE}/api/v1/mkt/tickers",
    ]

    errors = []

    for url in endpoints:
        try:
            data = http_get(url)
            items = unwrap_list(data)

            tickers = []
            for item in items:
                ticker = normalize_ticker(item)
                if ticker:
                    tickers.append(ticker)

            if tickers:
                # Keep the most active markets when volume is available.
                tickers.sort(
                    key=lambda x: (
                        x["volume"] if x["volume"] is not None else -1
                    ),
                    reverse=True,
                )

                log.info(
                    "Ticker API online: %s USDT markets",
                    len(tickers),
                )
                return tickers[:MAX_MARKETS]

            errors.append(f"{url}: no usable USDT tickers")

        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError(
        "Could not retrieve Bitpin tickers. "
        + " | ".join(errors)
    )


def get_markets():
    """Check the public markets endpoint independently."""

    endpoints = [
        f"{BITPIN_BASE}/api/v1/mkt/markets/",
        f"{BITPIN_BASE}/api/v1/mkt/markets",
    ]

    for url in endpoints:
        try:
            data = http_get(url)
            markets = unwrap_list(data)

            if markets:
                log.info("Markets API online: %s records", len(markets))
                return markets

        except (requests.RequestException, ValueError) as exc:
            log.warning("Markets endpoint failed: %s", exc)

    return []


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(ticker):
    """
    This is a preliminary signal based on ticker data and
    reported percentage change. It is NOT candle-confirmed.
    """

    change = ticker["change"]
    price = ticker["price"]

    if change is None:
        return None

    if abs(change) < MIN_ABS_CHANGE:
        return None

    if abs(change) > MAX_ABS_CHANGE:
        return None

    side = "LONG" if change > 0 else "SHORT"

    # Base score rises with absolute reported daily movement.
    score = 55 + min(abs(change) * 2.5, 30)

    # Volume information is not reliable across all ticker APIs,
    # so it is not used to claim a confirmed volume signal.
    score = int(min(95, max(0, round(score))))

    if score < MIN_SCORE:
        return None

    if side == "LONG":
        entry = price
        stop = entry * (1 - STOP_PERCENT / 100)
        tp1 = entry * (1 + TP1_PERCENT / 100)
        tp2 = entry * (1 + TP2_PERCENT / 100)
        tp3 = entry * (1 + TP3_PERCENT / 100)
    else:
        entry = price
        stop = entry * (1 + STOP_PERCENT / 100)
        tp1 = entry * (1 - TP1_PERCENT / 100)
        tp2 = entry * (1 - TP2_PERCENT / 100)
        tp3 = entry * (1 - TP3_PERCENT / 100)

    return {
        **ticker,
        "side": side,
        "score": score,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "strength": (
            "🔥 قوی"
            if score >= STRONG_SCORE
            else "🟡 متوسط"
        ),
    }


# ============================================================
# FORMATTING
# ============================================================

def fmt_price(value):
    if value >= 1000:
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if value >= 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def fmt_change(value):
    if value is None:
        return "نامشخص"
    return f"{value:+.2f}%"


def make_header():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return (
        "🐋 ETH WHALE\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 BITPIN SMART MARKET WATCH\n"
        "🧪 PAPER SIGNALS ONLY\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 زمان بررسی: {now}\n"
        f"💰 سرمایه شبیه‌سازی: {CAPITAL_USDT:.2f} USDT\n"
        f"⚙️ اهرم فرضی: {LEVERAGE}x\n"
        "🔒 سفارش واقعی: غیرفعال\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )


def format_signal(signal, number):
    return (
        f"\n{'━' * 22}\n"
        f"{number}. {'🟢' if signal['side'] == 'LONG' else '🔴'} "
        f"{signal['symbol']}\n"
        f"📌 جهت: {signal['side']}\n"
        f"🏷 قیمت فعلی/ورود فرضی: "
        f"{fmt_price(signal['entry'])} USDT\n"
        f"📈 تغییر گزارش‌شده: {fmt_change(signal['change'])}\n"
        f"🎯 امتیاز: {signal['score']}/100 "
        f"({signal['strength']})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛑 حد ضرر: {fmt_price(signal['stop'])}\n"
        f"🥇 هدف ۱: {fmt_price(signal['tp1'])}\n"
        f"🥈 هدف ۲: {fmt_price(signal['tp2'])}\n"
        f"🥉 هدف ۳: {fmt_price(signal['tp3'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ سیگنال اولیه؛ بدون تأیید کندلی\n"
    )


def make_report(tickers, signals, markets_count):
    message = make_header()

    message += (
        f"🛰 بازارهای دارای قیمت معتبر: {len(tickers)}\n"
        f"📚 رکوردهای بازار: {markets_count}\n"
        f"🔎 سیگنال‌های واجد شرایط: {len(signals)}\n"
    )

    if not signals:
        message += (
            "\n⏳ در این نوبت سیگنال واجد شرایطی پیدا نشد.\n"
            "برای جلوگیری از سیگنال‌سازی اجباری، "
            "وضعیت بازار WAIT است.\n"
        )
    else:
        for index, signal in enumerate(signals, start=1):
            message += format_signal(signal, index)

    message += (
        "\n━━━━━━━━━━━━━━━━━━━━\n"
        "🧪 PAPER MODE: ON\n"
        "🚫 REAL ORDERS: OFF\n"
        "ℹ️ این پیام توصیه مالی نیست.\n"
        "⚠️ داده تغییرات بازار به‌تنهایی "
        "تأیید ورود محسوب نمی‌شود.\n"
        "🐋 ETH WHALE | Bitpin\n"
    )

    return message


# ============================================================
# MAIN
# ============================================================

def main():
    log.info("Starting %s", BOT_NAME)

    # Hard safety guard: this bot never submits exchange orders.
    if REAL_ORDERS_ENABLED or not PAPER_MODE:
        raise RuntimeError(
            "Safety check failed: paper mode must remain enabled."
        )

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error(
            "Missing Telegram secrets. Configure "
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "in GitHub repository secrets."
        )
        return 1

    try:
        # Verify that Bitpin responds before producing a report.
        markets = get_markets()
        tickers = get_tickers()

        candidates = []
        for ticker in tickers:
            signal = calculate_signal(ticker)
            if signal:
                candidates.append(signal)

        candidates.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        signals = candidates[:MAX_SIGNALS]

        report = make_report(
            tickers=tickers,
            signals=signals,
            markets_count=len(markets),
        )

        print(report)

        if not telegram_send(report):
            log.error("Report was not fully delivered to Telegram.")
            return 1

        log.info("Scan finished successfully.")
        return 0

    except Exception as exc:
        log.exception("Scan failed: %s", exc)

        # Send a short error notice when possible.
        telegram_send(
            "⚠️ ETH WHALE | BITPIN\n"
            "اسکن بازار با خطا مواجه شد.\n"
            f"نوع خطا: {type(exc).__name__}\n"
            "لطفاً گزارش GitHub Actions را بررسی کنید."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
