
import os
import time
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# ETH WHALE | BITPIN SIMPLE SIGNAL BOT
# PAPER / SIGNALS ONLY — NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
BASE_URL = "https://api.bitpin.ir"
CAPITAL_USDT = 48.0
MAX_SIGNALS = 3
MIN_CHANGE_PERCENT = 1.0
REQUEST_TIMEOUT = 25

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def get_json(url):
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_list(data, preferred_keys=()):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in preferred_keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

        for value in data.values():
            if isinstance(value, list):
                return value

    return []


def load_markets():
    errors = []

    for path in ("/v1/mkt/markets/", "/api/v1/mkt/markets/"):
        try:
            data = get_json(BASE_URL + path)
            markets = get_list(data, ("results", "markets"))

            if markets:
                return markets

            errors.append(path + ": no market list")

        except Exception as exc:
            errors.append(path + ": " + str(exc))

    raise RuntimeError("Markets API failed: " + " | ".join(errors))


def load_tickers():
    errors = []

    for path in ("/v1/mkt/tickers/", "/api/v1/mkt/tickers/"):
        try:
            data = get_json(BASE_URL + path)
            tickers = get_list(data, ("tickers", "results"))

            if tickers:
                return tickers

            if isinstance(data, dict) and data:
                # Some API responses use symbols as dictionary keys.
                if all(isinstance(v, dict) for v in data.values()):
                    return [
                        dict(value, symbol=value.get("symbol", key))
                        for key, value in data.items()
                    ]

            errors.append(path + ": no ticker list")

        except Exception as exc:
            errors.append(path + ": " + str(exc))

    raise RuntimeError("Tickers API failed: " + " | ".join(errors))


def number(value):
    try:
        result = float(value)
        if result == result and abs(result) != float("inf"):
            return result
    except (TypeError, ValueError):
        pass
    return None


def symbol_of(item):
    return str(
        item.get("symbol")
        or item.get("code")
        or item.get("market")
        or ""
    ).upper().replace("-", "_")


def price_of(item):
    for key in ("price", "last_price", "last", "lastPrice"):
        value = number(item.get(key))
        if value is not None and value > 0:
            return value
    return None


def change_percent_of(item):
    # Only use fields explicitly representing a percentage.
    for key in (
        "change_percent",
        "daily_change_percent",
        "price_change_percent",
        "changePercent",
        "daily_change"
    ):
        value = number(item.get(key))
        if value is not None:
            # Reject implausible percentage readings.
            if -100 <= value <= 100:
                return value

    # Do not treat daily_change_price as a percentage.
    return None


def telegram_send(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secret"
        )

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True
        },
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message")


def build_signals(markets, tickers):
    market_map = {}

    for market in markets:
        symbol = symbol_of(market)
        if symbol:
            market_map[symbol] = market

    signals = []

    for ticker in tickers:
        symbol = symbol_of(ticker)

        if not symbol:
            continue

        # Keep USDT-quoted crypto markets only.
        if not (
            symbol.endswith("_USDT")
            or symbol.endswith("USDT")
        ):
            continue

        market = market_map.get(symbol, {})
        if market and market.get("tradable") is False:
            continue

        price = price_of(ticker)
        change = change_percent_of(ticker)

        if price is None or change is None:
            continue

        # Simple momentum filter; not a guaranteed prediction.
        if change >= MIN_CHANGE_PERCENT:
            side = "🟢 BUY WATCH"
            entry = price
            stop = entry * 0.99
            target1 = entry * 1.02
            target2 = entry * 1.03
            score = min(90, 60 + int(change * 5))

        elif change <= -MIN_CHANGE_PERCENT:
            side = "🔴 SELL / AVOID BUYING"
            entry = price
            stop = entry * 1.01
            target1 = entry * 0.98
            target2 = entry * 0.97
            score = min(90, 60 + int(abs(change) * 5))

        else:
            continue

        signals.append({
            "symbol": symbol,
            "price": price,
            "change": change,
            "side": side,
            "stop": stop,
            "target1": target1,
            "target2": target2,
            "score": score
        })

    # Strongest absolute daily moves first.
    signals.sort(key=lambda x: abs(x["change"]), reverse=True)
    return signals[:MAX_SIGNALS]


def format_report(markets, tickers, signals):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "🐋 ETH WHALE",
        "━━━━━━━━━━━━━━━━━━",
        "📊 BITPIN SIMPLE SIGNALS",
        "🧪 SIGNALS ONLY — NO REAL ORDERS",
        "━━━━━━━━━━━━━━━━━━",
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT",
        f"📈 بازارها: {len(markets)}",
        f"💹 تیکرها: {len(tickers)}",
        f"🕒 زمان: {now}",
        ""
    ]

    if not signals:
        lines.extend([
            "⏸ سیگنال معتبر پیدا نشد.",
            "",
            "ممکن است API درصد تغییر روزانه را در فیلد دیگری ارائه کند.",
            "در این نسخه هیچ سیگنال ساختگی تولید نمی‌شود."
        ])
        return "\n".join(lines)

    for i, sig in enumerate(signals, 1):
        lines.extend([
            f"{i}. {sig['symbol']}",
            f"📌 وضعیت: {sig['side']}",
            f"💵 قیمت فعلی: {sig['price']:.8g}",
            f"📊 تغییر روزانه: {sig['change']:+.2f}%",
            f"🎯 هدف ۱: {sig['target1']:.8g}",
            f"🎯 هدف ۲: {sig['target2']:.8g}",
            f"🛑 حد ضرر آزمایشی: {sig['stop']:.8g}",
            f"⭐ امتیاز حرکت: {sig['score']}/100",
            "━━━━━━━━━━━━━━━━━━"
        ])

    lines.extend([
        "⚠️ سیگنال‌ها فقط بر اساس تغییر قیمت هستند.",
        "این نسخه کندل، EMA یا RSI را تحلیل نمی‌کند.",
        "SELL / AVOID به معنی ثبت سفارش فروش نیست."
    ])

    return "\n".join(lines)


def main():
    logging.info("Starting Bitpin signal bot")

    markets = load_markets()
    tickers = load_tickers()

    signals = build_signals(markets, tickers)
    report = format_report(markets, tickers, signals)

    print(report)
    telegram_send(report)

    logging.info("Report sent successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("Bot failed")

        # Try to report the error to Telegram.
        try:
            telegram_send(
                "🐋 ETH WHALE\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "❌ اسکن کامل نشد.\n"
                f"علت: {type(exc).__name__}: {str(exc)[:700]}\n"
                "🧪 سفارش واقعی ثبت نشده است."
            )
        except Exception:
            logging.exception("Could not send error to Telegram")

        raise
