
import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# BITPIN PAPER SIGNAL BOT
# PAPER TRADING ONLY - NO REAL ORDERS
# ============================================================

BITPIN_BASE = "https://api.bitpin.ir"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Simulated trading settings
CAPITAL_USDT = 100.0
LEVERAGE = 3
POSITION_USDT = CAPITAL_USDT * LEVERAGE
PAPER_MODE = True

# Signal settings
MAX_SIGNALS_PER_RUN = 3
MAX_WORKERS = 6
REQUEST_TIMEOUT = 12
TRADES_TO_ANALYZE = 30

MIN_CHANGE_PERCENT = 0.15
MIN_DIRECTIONAL_CONSISTENCY = 60.0

STOP_PERCENT = 0.80
TP1_PERCENT = 0.80
TP2_PERCENT = 1.60
TP3_PERCENT = 2.40

# Scan all markets quoted in USDT.
# Set to a positive number to limit the scan if necessary.
MAX_MARKETS = 0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Bitpin-Paper-Signal-Bot/1.0",
    "Accept": "application/json",
})


# ============================================================
# HTTP HELPERS
# ============================================================

def get_json(url, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def extract_list(data):
    """Handle common list response formats."""
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "results",
            "data",
            "markets",
            "trades",
            "matches",
            "tickers",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in ("results", "data", "items"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return nested

                # Some APIs return a symbol-keyed ticker dictionary.
                if key == "tickers":
                    return [
                        dict(item, symbol=item.get("symbol", symbol))
                        if isinstance(item, dict)
                        else item
                        for symbol, item in value.items()
                    ]

    return []


def as_float(value):
    try:
        result = float(value)
        if result > 0:
            return result
    except (TypeError, ValueError):
        pass

    return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_usdt_markets():
    url = f"{BITPIN_BASE}/v1/mkt/markets/"
    data = get_json(url)
    raw_markets = extract_list(data)

    markets = []
    seen = set()

    for market in raw_markets:
        if not isinstance(market, dict):
            continue

        symbol = str(
            market.get("symbol")
            or market.get("code")
            or market.get("name")
            or ""
        ).strip().upper()

        base = str(
            market.get("base_currency")
            or market.get("base")
            or ""
        ).strip().upper()

        quote = str(
            market.get("quote_currency")
            or market.get("quote")
            or ""
        ).strip().upper()

        if not symbol:
            continue

        # Common Bitpin market symbol format: BTC_USDT
        is_usdt = (
            symbol.endswith("_USDT")
            or symbol.endswith("-USDT")
            or quote == "USDT"
        )

        if not is_usdt:
            continue

        if symbol in seen:
            continue

        seen.add(symbol)

        # Normalize the symbol for the recent-trades endpoint.
        symbol = symbol.replace("-", "_")

        markets.append({
            "symbol": symbol,
            "base": base,
            "quote": quote or "USDT",
        })

    if MAX_MARKETS > 0:
        markets = markets[:MAX_MARKETS]

    return markets


# ============================================================
# RECENT TRADES
# ============================================================

def get_recent_trades(symbol):
    url = (
        f"{BITPIN_BASE}/api/v1/mth/"
        f"matches/{symbol}/"
    )

    data = get_json(url)
    rows = extract_list(data)

    trades = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        price = as_float(row.get("price"))
        if price is None:
            continue

        timestamp = (
            row.get("time")
            or row.get("timestamp")
            or row.get("created_at")
            or row.get("id")
            or 0
        )

        trades.append({
            "price": price,
            "time": str(timestamp),
        })

    # Order trades chronologically when the API returns
    # sortable timestamps or IDs.
    trades.sort(key=lambda item: item["time"])

    return trades[-TRADES_TO_ANALYZE:]


# ============================================================
# PAPER SIGNAL CALCULATION
# ============================================================

def analyze_market(market):
    symbol = market["symbol"]

    try:
        trades = get_recent_trades(symbol)

        if len(trades) < 10:
            return None

        prices = [trade["price"] for trade in trades]

        first_price = prices[0]
        last_price = prices[-1]

        if first_price <= 0 or last_price <= 0:
            return None

        change_pct = (
            (last_price - first_price) / first_price
        ) * 100.0

        if abs(change_pct) < MIN_CHANGE_PERCENT:
            return None

        if last_price > first_price:
            direction = "LONG"
            favorable_steps = sum(
                1 for a, b in zip(prices, prices[1:])
                if b > a
            )
        elif last_price < first_price:
            direction = "SHORT"
            favorable_steps = sum(
                1 for a, b in zip(prices, prices[1:])
                if b < a
            )
        else:
            return None

        total_steps = len(prices) - 1

        if total_steps <= 0:
            return None

        consistency = (
            favorable_steps / total_steps
        ) * 100.0

        if consistency < MIN_DIRECTIONAL_CONSISTENCY:
            return None

        # A simple heuristic score, not a probability of profit.
        movement_score = min(
            abs(change_pct) / 0.50,
            1.0
        ) * 40.0

        score = round(
            consistency * 0.60 + movement_score,
            1
        )

        entry = last_price

        if direction == "LONG":
            stop = entry * (1 - STOP_PERCENT / 100)
            tp1 = entry * (1 + TP1_PERCENT / 100)
            tp2 = entry * (1 + TP2_PERCENT / 100)
            tp3 = entry * (1 + TP3_PERCENT / 100)
        else:
            stop = entry * (1 + STOP_PERCENT / 100)
            tp1 = entry * (1 - TP1_PERCENT / 100)
            tp2 = entry * (1 - TP2_PERCENT / 100)
            tp3 = entry * (1 - TP3_PERCENT / 100)

        return {
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "change_pct": change_pct,
            "consistency": consistency,
            "score": score,
            "trades_count": len(trades),
        }

    except Exception as exc:
        logging.warning("%s skipped: %s", symbol, exc)
        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error(
            "Telegram configuration missing. "
            "Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            logging.error("Telegram API rejected the message.")
            return False

        logging.info("Telegram message sent.")
        return True

    except Exception as exc:
        logging.error("Telegram send failed: %s", exc)
        return False


def format_price(value):
    if value >= 100:
        return f"{value:.4f}"
    if value >= 1:
        return f"{value:.6f}"
    return f"{value:.8f}"


def format_signal(signal, number):
    direction_fa = (
        "خرید آزمایشی LONG"
        if signal["direction"] == "LONG"
        else "فروش آزمایشی SHORT"
    )

    # Gross P/L estimates on the full simulated position.
    tp1_pnl = POSITION_USDT * TP1_PERCENT / 100
    tp2_pnl = POSITION_USDT * TP2_PERCENT / 100
    tp3_pnl = POSITION_USDT * TP3_PERCENT / 100
    stop_pnl = -POSITION_USDT * STOP_PERCENT / 100

    return (
        f"📊 BITPIN PAPER SIGNAL #{number}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"جفت‌ارز: {signal['symbol']}\n"
        f"جهت: {direction_fa}\n"
        f"امتیاز الگوریتم: {signal['score']}/100\n"
        f"تغییر قیمت معاملات اخیر: "
        f"{signal['change_pct']:+.3f}%\n"
        f"هم‌جهتی حرکت‌ها: "
        f"{signal['consistency']:.1f}%\n"
        f"تعداد معاملات بررسی‌شده: "
        f"{signal['trades_count']}\n"
        f"\n"
        f"ورود فرضی: {format_price(signal['entry'])}\n"
        f"حد ضرر: {format_price(signal['stop'])}\n"
        f"TP1: {format_price(signal['tp1'])}\n"
        f"TP2: {format_price(signal['tp2'])}\n"
        f"TP3: {format_price(signal['tp3'])}\n"
        f"\n"
        f"سرمایه مجازی: {CAPITAL_USDT:.2f} USDT\n"
        f"اهرم شبیه‌سازی: {LEVERAGE}x\n"
        f"ارزش اسمی موقعیت: {POSITION_USDT:.2f} USDT\n"
        f"\n"
        f"سود ناخالص فرضی TP1: +{tp1_pnl:.2f} USDT\n"
        f"سود ناخالص فرضی TP2: +{tp2_pnl:.2f} USDT\n"
        f"سود ناخالص فرضی TP3: +{tp3_pnl:.2f} USDT\n"
        f"زیان ناخالص فرضی SL: {stop_pnl:.2f} USDT\n"
        f"\n"
        f"⚠️ PAPER ONLY — سفارش واقعی ثبت نمی‌شود.\n"
        f"این سیگنال بر اساس معاملات اخیر است، نه تأیید "
        f"کندلی یا تضمین سود.\n"
        f"کارمزد، لغزش قیمت و فاندینگ محاسبه نشده‌اند."
    )


# ============================================================
# MAIN
# ============================================================

def main():
    logging.info("Starting Bitpin paper signal bot.")
    logging.info(
        "Capital=%.2f USDT | Leverage=%sx | Notional=%.2f USDT",
        CAPITAL_USDT,
        LEVERAGE,
        POSITION_USDT,
    )

    if not PAPER_MODE:
        raise RuntimeError(
            "Safety check failed: this bot must remain paper-only."
        )

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secret."
        )

    try:
        markets = get_usdt_markets()
    except Exception as exc:
        logging.error("Could not load Bitpin markets: %s", exc)
        raise

    logging.info("USDT markets discovered: %s", len(markets))

    if not markets:
        raise RuntimeError(
            "No USDT markets found. Check the Bitpin markets response."
        )

    signals = []
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(analyze_market, market): market
            for market in markets
        }

        for future in as_completed(futures):
            completed += 1

            try:
                signal = future.result()
                if signal:
                    signals.append(signal)
            except Exception as exc:
                market = futures[future]
                logging.warning(
                    "Market analysis failed for %s: %s",
                    market.get("symbol", "UNKNOWN"),
                    exc,
                )

    signals.sort(
        key=lambda item: (
            item["score"],
            item["consistency"],
            abs(item["change_pct"]),
        ),
        reverse=True,
    )

    selected = signals[:MAX_SIGNALS_PER_RUN]

    logging.info(
        "Scan complete: %s markets checked, %s candidates found.",
        completed,
        len(signals),
    )

    if not selected:
        message = (
            "🔎 BITPIN PAPER BOT\n"
            "بررسی بازار تمام شد.\n"
            f"بازارهای USDT: {len(markets)}\n"
            "در این اجرا سیگنالی با شرایط تعیین‌شده پیدا نشد.\n"
            "سفارش واقعی: خاموش"
        )
        send_telegram(message)
        return

    for index, signal in enumerate(selected, start=1):
        send_telegram(format_signal(signal, index))
        time.sleep(1)

    logging.info("Bot finished. Real orders were not placed.")


if __name__ == "__main__":
    main()
