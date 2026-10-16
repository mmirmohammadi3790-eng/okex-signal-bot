
# ============================================================
# ETH WHALE | BITPIN SMART MARKET WATCH
# PAPER SIGNALS ONLY - NO REAL ORDERS
# Capital: 48 USDT | Simulated leverage: 3x
# Timeframes: 15m + 1h
# Indicators: EMA20 / EMA50 / RSI14 / Volume / ATR
# ============================================================

import os
import time
import logging
from datetime import datetime, timezone

import requests


# ---------------------- CONFIGURATION -----------------------

BOT_NAME = "🐋 ETH WHALE"

BITPIN_BASE = "https://api.bitpin.org"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

CAPITAL = 48.0
LEVERAGE = 3
PAPER_MODE = True

MAX_MARKETS = 30
MAX_SIGNALS = 3
MIN_SCORE = 55
STRONG_SCORE = 72

CANDLE_LIMIT = 100
TIMEFRAMES = ("15m", "1h")

REQUEST_TIMEOUT = 12
REQUEST_PAUSE = 0.15

BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
]

HEADERS = {
    "User-Agent": "ETH-WHALE-PaperBot/3.0",
    "Accept": "application/json",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

session = requests.Session()
session.headers.update(HEADERS)


# ---------------------- HTTP HELPERS ------------------------

def get_json(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def first_value(data, keys, default=None):
    if not isinstance(data, dict):
        return default

    for key in keys:
        value = data.get(key)
        if value is not None:
            return value

    return default


# ---------------------- BITPIN MARKETS ----------------------

def fetch_markets():
    endpoints = [
        f"{BITPIN_BASE}/v1/mkt/markets/",
        f"{BITPIN_BASE}/api/v1/mkt/markets/",
    ]

    last_error = None

    for url in endpoints:
        try:
            data = get_json(url)

            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get("results")
                if not isinstance(rows, list):
                    rows = data.get("markets")
                if not isinstance(rows, list):
                    rows = data.get("data")
            else:
                rows = None

            if isinstance(rows, list) and rows:
                logging.info("Bitpin markets loaded: %s", len(rows))
                return rows

            last_error = f"Unexpected market response: {str(data)[:200]}"

        except Exception as exc:
            last_error = f"{url}: {exc}"
            logging.warning("Markets endpoint failed: %s", last_error)

    raise RuntimeError(
        "Could not fetch Bitpin markets. " + str(last_error)
    )


# ---------------------- BITPIN TICKERS ----------------------

def fetch_tickers():
    endpoints = [
        f"{BITPIN_BASE}/v1/mkt/tickers/",
        f"{BITPIN_BASE}/api/v1/mkt/tickers/",
    ]

    last_error = None

    for url in endpoints:
        try:
            data = get_json(url)

            if isinstance(data, list):
                return data

            if isinstance(data, dict):
                for key in ("tickers", "results", "data"):
                    rows = data.get(key)
                    if isinstance(rows, list):
                        return rows
                    if isinstance(rows, dict):
                        return [
                            dict(value, symbol=value.get("symbol", key))
                            if isinstance(value, dict)
                            else {"symbol": key, "price": value}
                            for key, value in rows.items()
                        ]

            last_error = f"Unexpected ticker response: {str(data)[:200]}"

        except Exception as exc:
            last_error = f"{url}: {exc}"
            logging.warning("Ticker endpoint failed: %s", last_error)

    raise RuntimeError(
        "Could not fetch Bitpin tickers. " + str(last_error)
    )


def market_symbol(row):
    if not isinstance(row, dict):
        return ""

    symbol = first_value(
        row,
        ("symbol", "code", "market", "name"),
        "",
    )

    return str(symbol).upper().strip()


def is_usdt_market(symbol):
    symbol = symbol.upper().replace("-", "_")
    return symbol.endswith("_USDT") or symbol.endswith("USDT")


def market_is_tradable(row):
    if not isinstance(row, dict):
        return False

    for key in ("tradable", "is_active", "active", "is_trading"):
        if key in row and row[key] is False:
            return False

    return True


def normalize_tickers(rows):
    result = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        symbol = market_symbol(row)
        price = first_value(
            row,
            ("price", "last", "last_price", "close", "lastPrice"),
        )

        try:
            price = float(price)
        except (TypeError, ValueError):
            continue

        if symbol and price > 0:
            result[symbol.replace("-", "_")] = {
                "price": price,
                "raw": row,
            }

    return result


def get_market_price(symbol, ticker_map):
    normalized = symbol.replace("-", "_").upper()

    if normalized in ticker_map:
        return ticker_map[normalized]["price"]

    compact = normalized.replace("_", "")

    for key, value in ticker_map.items():
        if key.replace("_", "") == compact:
            return value["price"]

    return None


# ---------------------- CANDLE DATA -------------------------
# Historical candles are retrieved from Binance public API.
# The bot uses Bitpin for current market prices.
# A candle-source failure is logged and never treated as a signal.

def to_binance_symbol(symbol):
    return (
        str(symbol)
        .upper()
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
        .strip()
    )


def fetch_candles(symbol, timeframe):
    binance_symbol = to_binance_symbol(symbol)
    errors = []

    for host in BINANCE_HOSTS:
        url = host + "/api/v3/klines"

        try:
            response = session.get(
                url,
                params={
                    "symbol": binance_symbol,
                    "interval": timeframe,
                    "limit": CANDLE_LIMIT,
                },
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                errors.append(
                    f"{host}: HTTP {response.status_code} "
                    f"{response.text[:120]}"
                )
                continue

            data = response.json()

            if not isinstance(data, list):
                errors.append(f"{host}: unexpected response format")
                continue

            candles = []

            for row in data:
                if not isinstance(row, list) or len(row) < 6:
                    continue

                try:
                    candles.append({
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    })
                except (TypeError, ValueError):
                    continue

            if len(candles) >= 52:
                logging.info(
                    "CANDLES OK | %s | %s | count=%s | host=%s",
                    symbol,
                    timeframe,
                    len(candles),
                    host,
                )
                return candles[-CANDLE_LIMIT:]

            errors.append(
                f"{host}: only {len(candles)} valid candles"
            )

        except Exception as exc:
            errors.append(f"{host}: {repr(exc)}")

    logging.error(
        "CANDLES FAILED | symbol=%s | timeframe=%s | %s",
        symbol,
        timeframe,
        " || ".join(errors)[:700],
    )

    return []


# ---------------------- INDICATORS --------------------------

def ema_series(values, period):
    if len(values) < period:
        return []

    multiplier = 2.0 / (period + 1.0)
    result = [None] * (period - 1)

    current = sum(values[:period]) / period
    result.append(current)

    for value in values[period:]:
        current = value * multiplier + current * (1 - multiplier)
        result.append(current)

    return result


def rsi_value(closes, period=14):
    if len(closes) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr_value(candles, period=14):
    if len(candles) <= period:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close),
        )

        true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[:period]) / period

    for value in true_ranges[period:]:
        atr = (atr * (period - 1) + value) / period

    return atr


def analyze_timeframe(candles):
    if len(candles) < 52:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    ema20 = ema_series(closes, 20)
    ema50 = ema_series(closes, 50)
    rsi = rsi_value(closes)
    atr = atr_value(candles)

    if (
        not ema20
        or not ema50
        or rsi is None
        or atr is None
        or ema20[-1] is None
        or ema50[-1] is None
    ):
        return None

    avg_volume = sum(volumes[-21:-1]) / 20.0
    current_volume = volumes[-1]

    volume_ratio = (
        current_volume / avg_volume if avg_volume > 0 else 0.0
    )

    close = closes[-1]

    if ema20[-1] > ema50[-1] and close > ema20[-1]:
        trend = "LONG"
    elif ema20[-1] < ema50[-1] and close < ema20[-1]:
        trend = "SHORT"
    else:
        trend = "NEUTRAL"

    return {
        "close": close,
        "ema20": ema20[-1],
        "ema50": ema50[-1],
        "rsi": rsi,
        "atr": atr,
        "volume_ratio": volume_ratio,
        "trend": trend,
    }


# ---------------------- SIGNAL ENGINE ----------------------

def create_signal(symbol, price, analysis15, analysis1h):
    if not analysis15 or not analysis1h or price <= 0:
        return None

    score_long = 0
    score_short = 0
    reasons_long = []
    reasons_short = []

    # 15-minute trend
    if analysis15["trend"] == "LONG":
        score_long += 25
        reasons_long.append("روند ۱۵دقیقه صعودی")

    elif analysis15["trend"] == "SHORT":
        score_short += 25
        reasons_short.append("روند ۱۵دقیقه نزولی")

    # 1-hour trend
    if analysis1h["trend"] == "LONG":
        score_long += 30
        reasons_long.append("روند ۱ساعته صعودی")

    elif analysis1h["trend"] == "SHORT":
        score_short += 30
        reasons_short.append("روند ۱ساعته نزولی")

    # RSI confirmation
    rsi15 = analysis15["rsi"]
    rsi1h = analysis1h["rsi"]

    if 50 <= rsi15 <= 68:
        score_long += 15
        reasons_long.append("RSI تایید خرید")

    if 32 <= rsi15 <= 50:
        score_short += 15
        reasons_short.append("RSI تایید فروش")

    if rsi1h > 50:
        score_long += 10

    elif rsi1h < 50:
        score_short += 10

    # Volume confirmation
    volume_ratio = analysis15["volume_ratio"]

    if volume_ratio >= 1.15:
        if score_long > score_short:
            score_long += 15
            reasons_long.append("حجم بالاتر از میانگین")
        elif score_short > score_long:
            score_short += 15
            reasons_short.append("حجم بالاتر از میانگین")

    # Candle direction confirmation
    if analysis15["close"] > analysis15["ema20"]:
        score_long += 5
    elif analysis15["close"] < analysis15["ema20"]:
        score_short += 5

    if score_long >= score_short:
        direction = "LONG"
        score = score_long
        reasons = reasons_long
        atr = analysis15["atr"]
    else:
        direction = "SHORT"
        score = score_short
        reasons = reasons_short
        atr = analysis15["atr"]

    # Require agreement between timeframes.
    if analysis15["trend"] != direction:
        return None

    if analysis1h["trend"] != direction:
        return None

    # Avoid buying an overbought market or selling an oversold market.
    if direction == "LONG" and rsi15 >= 70:
        return None

    if direction == "SHORT" and rsi15 <= 30:
        return None

    if score < MIN_SCORE or atr <= 0:
        return None

    # Paper-only entry/stop/targets. No orders are sent.
    stop_distance = 1.5 * atr
    tp1_distance = 1.5 * atr
    tp2_distance = 2.2 * atr
    tp3_distance = 3.0 * atr

    if direction == "LONG":
        stop = price - stop_distance
        tp1 = price + tp1_distance
        tp2 = price + tp2_distance
        tp3 = price + tp3_distance
    else:
        stop = price + stop_distance
        tp1 = price - tp1_distance
        tp2 = price - tp2_distance
        tp3 = price - tp3_distance

    # Simulated exposure only; this does not place an exchange order.
    position_notional = CAPITAL * LEVERAGE / max(1, MAX_SIGNALS)
    estimated_quantity = position_notional / price
    risk_estimate = estimated_quantity * stop_distance

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "price": price,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "volume_ratio": volume_ratio,
        "position_notional": position_notional,
        "risk_estimate": risk_estimate,
        "reasons": reasons,
        "strong": score >= STRONG_SCORE,
    }


# ---------------------- FORMATTING -------------------------

def fmt_price(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def fmt_score(value):
    return f"{int(value)}/100"


def build_message(markets_count, analyzed, errors, signals, run_time):
    lines = [
        "🐋 <b>ETH WHALE</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>BITPIN SMART MARKET WATCH</b>",
        "🧪 PAPER SIGNALS ONLY",
        "⛔ Real Orders: <b>OFF</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 سرمایه آزمایشی: <b>{CAPITAL:.2f} USDT</b>",
        f"⚙️ اهرم شبیه‌سازی: <b>{LEVERAGE}x</b>",
        f"📦 ارزش فرضی کل: <b>{CAPITAL * LEVERAGE:.2f} USDT</b>",
        "⏱ تایم‌فریم: <b>15m + 1h</b>",
        "📈 قیمت لحظه‌ای: Bitpin",
        "🕯 کندل‌ها: Binance public API",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔎 بازارهای انتخاب‌شده: <b>{markets_count}</b>",
        f"✅ تحلیل موفق: <b>{analyzed}</b>",
        f"⚠️ بازارهای دارای خطای کندل: <b>{errors}</b>",
        f"🎯 سیگنال معتبر: <b>{len(signals)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if analyzed == 0:
        lines.extend([
            "🚨 <b>تحلیل انجام نشد</b>",
            "داده کندل دریافت نشده است؛ سیگنال صادر نمی‌شود.",
            "برای رفع مشکل، گزارش CANDLES FAILED را در GitHub Actions بررسی کنید.",
        ])

    elif not signals:
        lines.append("🔍 در این اسکن سیگنال منطبق با فیلترها پیدا نشد.")
        lines.append("برای جلوگیری از سیگنال ضعیف، فیلترها عمداً حفظ شده‌اند.")

    for index, signal in enumerate(signals, start=1):
        direction_emoji = "🟢" if signal["direction"] == "LONG" else "🔴"
        quality = "⭐ قوی" if signal["strong"] else "🔹 متعادل"

        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            f"{direction_emoji} <b>سیگنال {index}: {signal['symbol']}</b>",
            f"📍 جهت: <b>{signal['direction']}</b> | {quality}",
            f"🧠 امتیاز: <b>{fmt_score(signal['score'])}</b>",
            f"💵 ورود فرضی: <code>{fmt_price(signal['price'])}</code>",
            f"🛑 حد ضرر: <code>{fmt_price(signal['stop'])}</code>",
            f"🎯 TP1: <code>{fmt_price(signal['tp1'])}</code>",
            f"🎯 TP2: <code>{fmt_price(signal['tp2'])}</code>",
            f"🎯 TP3: <code>{fmt_price(signal['tp3'])}</code>",
            f"📊 RSI 15m: {signal['rsi15']:.1f}",
            f"📊 RSI 1h: {signal['rsi1h']:.1f}",
            f"🔊 حجم نسبت به میانگین: {signal['volume_ratio']:.2f}x",
            f"📦 سهم فرضی هر سیگنال: {signal['position_notional']:.2f} USDT",
            f"⚠️ زیان تخمینی تا SL: {signal['risk_estimate']:.3f} USDT",
            "📝 دلایل: " + "، ".join(signal["reasons"]),
            "⚠️ سیگنال آزمایشی است؛ سود تضمین‌شده نیست.",
        ])

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🕒 زمان اجرا: {run_time}",
        "🛡️ هیچ سفارش واقعی ثبت نشده است.",
    ])

    return "\n".join(lines)


# ---------------------- TELEGRAM ---------------------------

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning(
            "Telegram disabled: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"
        )
        print(message)
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    # Telegram message limit is 4096 characters.
    chunks = []

    while len(message) > 3800:
        cut = message.rfind("\n", 0, 3800)
        if cut < 1:
            cut = 3800
        chunks.append(message[:cut])
        message = message[cut:].lstrip("\n")

    chunks.append(message)

    success = True

    for chunk in chunks:
        try:
            response = session.post(
                url,
                json={
                    "chat_id": CHAT_ID,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                logging.error(
                    "Telegram HTTP %s: %s",
                    response.status_code,
                    response.text[:300],
                )
                success = False
            elif not response.json().get("ok", False):
                logging.error("Telegram API rejected message: %s", response.text[:300])
                success = False
            else:
                logging.info("Telegram message sent")

        except Exception as exc:
            logging.error("Telegram send error: %s", repr(exc))
            success = False

        time.sleep(0.3)

    return success


# ---------------------- MAIN SCAN --------------------------

def run_scan():
    logging.info("Starting ETH WHALE paper scan")

    markets = fetch_markets()
    ticker_rows = fetch_tickers()
    ticker_map = normalize_tickers(ticker_rows)

    candidates = []

    for row in markets:
        symbol = market_symbol(row)

        if not symbol or not is_usdt_market(symbol):
            continue

        if not market_is_tradable(row):
            continue

        price = get_market_price(symbol, ticker_map)

        if price is None or price <= 0:
            logging.warning("No Bitpin ticker for %s", symbol)
            continue

        candidates.append((symbol, price))

    # Sort by ticker volume when available, then use market order as fallback.
    def ticker_volume(item):
        symbol = item[0].replace("-", "_").upper()
        ticker = ticker_map.get(symbol, {}).get("raw", {})
        volume = first_value(
            ticker,
            ("quote_volume", "quoteVolume", "volume", "base_volume"),
            0,
        )

        try:
            return float(volume)
        except (TypeError, ValueError):
            return 0.0

    candidates.sort(key=ticker_volume, reverse=True)
    candidates = candidates[:MAX_MARKETS]

    analyzed = 0
    failed_candles = 0
    signals = []

    for symbol, price in candidates:
        try:
            candles15 = fetch_candles(symbol, "15m")
            candles1h = fetch_candles(symbol, "1h")

            if not candles15 or not candles1h:
                failed_candles += 1
                continue

            analysis15 = analyze_timeframe(candles15)
            analysis1h = analyze_timeframe(candles1h)

            if not analysis15 or not analysis1h:
                failed_candles += 1
                continue

            analyzed += 1

            signal = create_signal(
                symbol,
                price,
                analysis15,
                analysis1h,
            )

            if signal:
                signals.append(signal)

        except Exception:
            failed_candles += 1
            logging.exception("Market analysis failed: %s", symbol)

        time.sleep(REQUEST_PAUSE)

    signals.sort(key=lambda item: item["score"], reverse=True)
    signals = signals[:MAX_SIGNALS]

    run_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = build_message(
        markets_count=len(candidates),
        analyzed=analyzed,
        errors=failed_candles,
        signals=signals,
        run_time=run_time,
    )

    print(message)
    send_telegram(message)

    logging.info(
        "SCAN FINISHED | candidates=%d | analyzed=%d | candle_errors=%d | signals=%d",
        len(candidates),
        analyzed,
        failed_candles,
        len(signals),
    )

    # A scan with zero analyzed markets must not be reported as successful.
    if candidates and analyzed == 0:
        raise RuntimeError(
            "No markets were analyzed because candle data failed. "
            "Check CANDLES FAILED logs above."
        )


# ---------------------- ENTRY POINT ------------------------

if __name__ == "__main__":
    try:
        if not PAPER_MODE:
            raise RuntimeError(
                "Safety check failed: this bot is intended for paper mode only."
            )

        run_scan()

    except Exception as exc:
        logging.exception("BOT FAILED: %s", repr(exc))

        # Try to notify Telegram without hiding the original failure.
        send_telegram(
            "🐋 <b>ETH WHALE — خطای اجرا</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "❌ اسکن کامل نشد.\n"
            "⛔ هیچ سفارش واقعی ارسال نشده است.\n"
            f"🔎 خطا: <code>{str(exc)[:800]}</code>"
        )

        raise
