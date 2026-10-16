
# -*- coding: utf-8 -*-
"""
ETH WHALE - BITPIN SMART SIGNAL BOT
Balanced multi-timeframe analysis:
EMA20 / EMA50 / RSI / Volume
15m + 1h | PAPER ONLY | NO REAL ORDERS
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone

import requests


# ============================================================
# 1. CONFIGURATION
# ============================================================

BOT_NAME = "ETH WHALE"

# Bitpin API host
BASE_URL = "https://api.bitpin.org"

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)

TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID", "").strip()
    or os.getenv("CHAT_ID", "").strip()
)

# Safety: this bot never submits trading orders.
PAPER_MODE = True
REAL_ORDERS_ENABLED = False

CAPITAL_USDT = 48.0
LEVERAGE = 3
POSITION_VALUE = CAPITAL_USDT * LEVERAGE

MAX_MARKETS = 50
MAX_SIGNALS = 5

MIN_SCORE = 65
STRONG_SCORE = 80

CANDLE_LIMIT = 100
MIN_CANDLES = 55

REQUEST_TIMEOUT = 12
REQUEST_PAUSE = 0.10

# Balanced filters
MIN_VOLUME_RATIO = 0.65
MAX_VOLUME_RATIO = 0.0  # 0 = no upper limit

# Hypothetical risk/targets; percentages from entry price.
STOP_PERCENT = 1.5
TP1_PERCENT = 1.5
TP2_PERCENT = 3.0
TP3_PERCENT = 4.5

# Prevent excessively long repeated API attempts.
MAX_CANDLE_ENDPOINTS = 4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("eth-whale")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Bitpin-PaperBot/4.0",
    "Accept": "application/json",
})


# ============================================================
# 2. HTTP AND DATA HELPERS
# ============================================================

def get_json(url, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


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


def first_number(row, keys):
    if not isinstance(row, dict):
        return None

    for key in keys:
        value = to_float(row.get(key))
        if value is not None:
            return value

    return None


def unwrap_list(payload):
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    for key in (
        "results", "data", "markets", "tickers",
        "list", "coins", "items",
    ):
        value = payload.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            for nested_key in (
                "results", "data", "list", "items",
            ):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested

            converted = []
            for symbol, item in value.items():
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("symbol", symbol)
                    converted.append(row)

            if converted:
                return converted

    converted = []
    for symbol, item in payload.items():
        if isinstance(item, dict):
            row = dict(item)
            row.setdefault("symbol", symbol)
            converted.append(row)

    return converted


def normalize_symbol(raw_symbol):
    symbol = str(raw_symbol or "").upper().strip()
    symbol = symbol.replace("/", "-").replace("_", "-")

    if symbol.endswith("-USDT"):
        return symbol

    if symbol.endswith("USDT") and len(symbol) > 4:
        return symbol[:-4] + "-USDT"

    return ""


def api_symbol_candidates(symbol):
    """
    Generate common symbol spellings without changing
    the underlying market identity.
    """
    clean = normalize_symbol(symbol)

    if not clean:
        return []

    base = clean.replace("-USDT", "")

    return list(dict.fromkeys([
        clean,
        clean.replace("-", "_"),
        base + "USDT",
    ]))


# ============================================================
# 3. MARKET TICKERS
# ============================================================

def get_tickers():
    endpoints = [
        f"{BASE_URL}/api/v1/mkt/tickers/",
        f"{BASE_URL}/api/v1/mkt/tickers",
    ]

    errors = []

    for url in endpoints:
        try:
            payload = get_json(url)
            rows = unwrap_list(payload)
            tickers = []
            seen = set()

            for row in rows:
                if not isinstance(row, dict):
                    continue

                raw_symbol = (
                    row.get("symbol")
                    or row.get("code")
                    or row.get("market")
                    or row.get("pair")
                    or row.get("currency_pair")
                    or ""
                )

                symbol = normalize_symbol(raw_symbol)

                if not symbol or not symbol.endswith("-USDT"):
                    continue

                if symbol in seen:
                    continue

                price = first_number(
                    row,
                    (
                        "last", "last_price", "lastPrice",
                        "price", "close", "last_trade_price",
                    ),
                )

                volume = first_number(
                    row,
                    (
                        "quote_volume", "quoteVolume",
                        "volume_24h", "volume24h",
                        "quote_volume_24h", "base_volume",
                        "baseVolume", "volume",
                    ),
                )

                if price is None or price <= 0:
                    continue

                seen.add(symbol)

                tickers.append({
                    "symbol": symbol,
                    "api_symbol": symbol,
                    "price": price,
                    "volume": max(0.0, volume or 0.0),
                })

            if tickers:
                tickers.sort(
                    key=lambda item: item["volume"],
                    reverse=True,
                )

                log.info(
                    "Valid USDT tickers: %d",
                    len(tickers),
                )
                return tickers

            errors.append(f"{url}: no valid USDT tickers")

        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError(
        "Ticker API failed: " + " | ".join(errors)
    )


# ============================================================
# 4. CANDLE PARSING
# ============================================================

def parse_candle(row):
    if isinstance(row, dict):
        return {
            "open": first_number(row, ("open", "o")),
            "high": first_number(row, ("high", "max", "h")),
            "low": first_number(row, ("low", "min", "l")),
            "close": first_number(row, ("close", "price", "c")),
            "volume": first_number(row, ("volume", "vol", "v")),
        }

    if isinstance(row, (list, tuple)) and len(row) >= 6:
        # Common OHLCV format:
        # timestamp, open, high, low, close, volume
        return {
            "open": to_float(row[1]),
            "high": to_float(row[2]),
            "low": to_float(row[3]),
            "close": to_float(row[4]),
            "volume": to_float(row[5]),
        }

    return None


def normalize_candles(payload):
    rows = None

    if isinstance(payload, list):
        rows = payload

    elif isinstance(payload, dict):
        for key in (
            "results", "data", "candles",
            "ohlcv", "history", "items",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                rows = value
                break

            if isinstance(value, dict):
                for nested in value.values():
                    if isinstance(nested, list):
                        rows = nested
                        break

            if rows is not None:
                break

    if not isinstance(rows, list):
        return []

    candles = []

    for row in rows:
        candle = parse_candle(row)

        if candle is None:
            continue

        required = ("open", "high", "low", "close")

        if any(candle[key] is None for key in required):
            continue

        if any(candle[key] <= 0 for key in required):
            continue

        if candle["high"] < candle["low"]:
            continue

        candle["volume"] = max(0.0, candle["volume"] or 0.0)
        candles.append(candle)

    return candles


def get_candles(symbol, timeframe):
    """
    Try common public OHLCV URL and parameter patterns.
    No synthetic or fabricated candles are ever created.

    If Bitpin changes its public candle API, update the
    endpoint patterns after checking the actual API response.
    """

    interval_candidates = {
        "15m": ("15m", "15", "15min"),
        "1h": ("1h", "60", "1H"),
    }

    intervals = interval_candidates.get(
        timeframe, (timeframe,)
    )

    endpoints = []

    for api_symbol in api_symbol_candidates(symbol):
        for interval in intervals:
            endpoints.extend([
                (
                    f"{BASE_URL}/api/v1/mkt/ohlcv/{api_symbol}/",
                    {"interval": interval, "limit": CANDLE_LIMIT},
                ),
                (
                    f"{BASE_URL}/api/v1/mkt/ohlcv/",
                    {
                        "symbol": api_symbol,
                        "interval": interval,
                        "limit": CANDLE_LIMIT,
                    },
                ),
                (
                    f"{BASE_URL}/api/v1/mkt/candles/{api_symbol}/",
                    {"interval": interval, "limit": CANDLE_LIMIT},
                ),
                (
                    f"{BASE_URL}/api/v1/mkt/candles/",
                    {
                        "symbol": api_symbol,
                        "interval": interval,
                        "limit": CANDLE_LIMIT,
                    },
                ),
            ])

    tried = set()

    for url, params in endpoints[:MAX_CANDLE_ENDPOINTS * len(intervals)]:
        signature = (url, tuple(sorted(params.items())))

        if signature in tried:
            continue

        tried.add(signature)

        try:
            payload = get_json(url, params)
            candles = normalize_candles(payload)

            if len(candles) >= MIN_CANDLES:
                log.info(
                    "Candles OK: %s %s count=%d",
                    symbol, timeframe, len(candles),
                )
                return candles[-CANDLE_LIMIT:]

        except (requests.RequestException, ValueError) as exc:
            log.debug(
                "Candle API error %s %s: %s",
                symbol, timeframe, exc,
            )

        time.sleep(REQUEST_PAUSE)

    log.warning(
        "Candle data unavailable: %s %s",
        symbol, timeframe,
    )
    return []


# ============================================================
# 5. TECHNICAL INDICATORS
# ============================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    ema = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)

    for value in values[period:]:
        ema = alpha * value + (1.0 - alpha) * ema

    return ema


def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for index in range(period, len(changes)):
        avg_gain = (
            avg_gain * (period - 1) + gains[index]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[index]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def analyze_candles(candles):
    if len(candles) < MIN_CANDLES:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes, 14)

    if ema20 is None or ema50 is None or rsi is None:
        return None

    # Compare the latest candle volume with the previous
    # 20 candles. If history volume is zero, do not assume
    # volume confirmation.
    previous_volumes = volumes[-21:-1]

    average_volume = (
        sum(previous_volumes) / len(previous_volumes)
        if previous_volumes else 0.0
    )

    latest_volume = volumes[-1]

    volume_ratio = (
        latest_volume / average_volume
        if average_volume > 0 else None
    )

    return {
        "price": closes[-1],
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "volume": latest_volume,
        "average_volume": average_volume,
        "volume_ratio": volume_ratio,
    }


# ============================================================
# 6. SIGNAL SCORING
# ============================================================

def generate_signal(ticker, candles15, candles1h):
    a15 = analyze_candles(candles15)
    a1h = analyze_candles(candles1h)

    if not a15 or not a1h:
        return None

    price = a15["price"]
    rsi15 = a15["rsi"]
    rsi1h = a1h["rsi"]
    volume_ratio = a15["volume_ratio"]

    if price <= 0 or volume_ratio is None:
        return None

    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    if MAX_VOLUME_RATIO > 0 and volume_ratio > MAX_VOLUME_RATIO:
        return None

    bullish15 = a15["ema20"] > a15["ema50"]
    bullish1h = a1h["ema20"] > a1h["ema50"]
    bearish15 = a15["ema20"] < a15["ema50"]
    bearish1h = a1h["ema20"] < a1h["ema50"]

    # Both timeframes must agree on the direction.
    if bullish15 and bullish1h:
        side = "LONG"

        # Avoid buying an excessively overbought move.
        if not 48 <= rsi15 <= 72:
            return None

        if not 42 <= rsi1h <= 75:
            return None

    elif bearish15 and bearish1h:
        side = "SHORT"

        if not 28 <= rsi15 <= 52:
            return None

        if not 25 <= rsi1h <= 58:
            return None

    else:
        return None

    # Transparent score out of 100.
    score = 50

    # Trend alignment
    score += 15

    # Price position relative to short EMA
    if side == "LONG" and price >= a15["ema20"]:
        score += 5
    elif side == "SHORT" and price <= a15["ema20"]:
        score += 5

    # RSI momentum quality
    if side == "LONG" and 52 <= rsi15 <= 66:
        score += 10
    elif side == "SHORT" and 34 <= rsi15 <= 48:
        score += 10
    else:
        score += 5

    # Volume confirmation
    if volume_ratio >= 1.5:
        score += 15
    elif volume_ratio >= 1.0:
        score += 10
    else:
        score += 5

    # One-hour RSI should not contradict the direction.
    if side == "LONG" and rsi1h >= 50:
        score += 5
    elif side == "SHORT" and rsi1h <= 50:
        score += 5

    score = min(100, score)

    if score < MIN_SCORE:
        return None

    entry = price

    if side == "LONG":
        stop = entry * (1 - STOP_PERCENT / 100)
        tp1 = entry * (1 + TP1_PERCENT / 100)
        tp2 = entry * (1 + TP2_PERCENT / 100)
        tp3 = entry * (1 + TP3_PERCENT / 100)
    else:
        stop = entry * (1 + STOP_PERCENT / 100)
        tp1 = entry * (1 - TP1_PERCENT / 100)
        tp2 = entry * (1 - TP2_PERCENT / 100)
        tp3 = entry * (1 - TP3_PERCENT / 100)

    quantity = POSITION_VALUE / entry

    def estimate_pnl(target):
        if side == "LONG":
            return (target - entry) * quantity
        return (entry - target) * quantity

    return {
        "symbol": ticker["symbol"],
        "side": side,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "score": score,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "ema20_15": a15["ema20"],
        "ema50_15": a15["ema50"],
        "ema20_1h": a1h["ema20"],
        "ema50_1h": a1h["ema50"],
        "volume_ratio": volume_ratio,
        "position_value": POSITION_VALUE,
        "pnl_tp1": estimate_pnl(tp1),
        "pnl_tp2": estimate_pnl(tp2),
        "pnl_tp3": estimate_pnl(tp3),
        "pnl_stop": estimate_pnl(stop),
    }


# ============================================================
# 7. TELEGRAM FORMAT
# ============================================================

def format_price(value):
    if value is None:
        return "N/A"

    if abs(value) >= 1000:
        return f"{value:,.4f}".rstrip("0").rstrip(".")

    if abs(value) >= 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    return f"{value:.8f}".rstrip("0").rstrip(".")


def format_signal(signal, index):
    emoji = "🟢" if signal["side"] == "LONG" else "🔴"

    strength = (
        "🔥 قوی"
        if signal["score"] >= STRONG_SCORE
        else "🟡 متعادل"
    )

    return (
        "\n━━━━━━━━━━━━━━━━━━━━\n"
        f"{index}️⃣ {emoji} {signal['symbol']}\n"
        f"📌 جهت: {signal['side']} | امتیاز: "
        f"{signal['score']}/100 {strength}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 ورود فرضی: {format_price(signal['entry'])}\n"
        f"🛑 حد ضرر: {format_price(signal['stop'])}\n"
        f"🥇 هدف اول: {format_price(signal['tp1'])}\n"
        f"🥈 هدف دوم: {format_price(signal['tp2'])}\n"
        f"🥉 هدف سوم: {format_price(signal['tp3'])}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI 15m: {signal['rsi15']:.1f}\n"
        f"📊 RSI 1h: {signal['rsi1h']:.1f}\n"
        f"📈 EMA20/50 15m: "
        f"{format_price(signal['ema20_15'])} / "
        f"{format_price(signal['ema50_15'])}\n"
        f"📈 EMA20/50 1h: "
        f"{format_price(signal['ema20_1h'])} / "
        f"{format_price(signal['ema50_1h'])}\n"
        f"📦 نسبت حجم: {signal['volume_ratio']:.2f}x\n"
        f"💰 ارزش فرضی موقعیت: "
        f"{signal['position_value']:.2f} USDT\n"
        "🧮 سود ناخالص فرضی:\n"
        f"   هدف اول: {signal['pnl_tp1']:+.2f} USDT\n"
        f"   هدف دوم: {signal['pnl_tp2']:+.2f} USDT\n"
        f"   هدف سوم: {signal['pnl_tp3']:+.2f} USDT\n"
        f"   حد ضرر: {signal['pnl_stop']:+.2f} USDT\n"
        "⚠️ ارقام قبل از کارمزد و لغزش قیمت هستند.\n"
    )


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID."
        )

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    # Telegram message limit is 4096 characters.
    chunks = []

    while len(message) > 3900:
        split_at = message.rfind("\n", 0, 3900)

        if split_at < 100:
            split_at = 3900

        chunks.append(message[:split_at])
        message = message[split_at:].lstrip("\n")

    chunks.append(message)

    for chunk in chunks:
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
            raise RuntimeError(
                "Telegram rejected message: "
                + str(result.get("description", "unknown error"))
            )


# ============================================================
# 8. MAIN SCAN
# ============================================================

def main():
    if PAPER_MODE is not True or REAL_ORDERS_ENABLED is not False:
        raise RuntimeError(
            "Safety check failed: real trading must remain disabled."
        )

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "in GitHub Actions Secrets."
        )
        return 1

    try:
        tickers = get_tickers()
        selected = tickers[:MAX_MARKETS]

        log.info(
            "Available=%d | selected=%d",
            len(tickers), len(selected),
        )

        signals = []
        analyzed = 0
        candle_errors = 0
        rejected = 0

        for index, ticker in enumerate(selected, start=1):
            symbol = ticker["api_symbol"]

            log.info(
                "Scanning %d/%d: %s",
                index, len(selected), symbol,
            )

            candles15 = get_candles(symbol, "15m")
            candles1h = get_candles(symbol, "1h")

            if not candles15 or not candles1h:
                candle_errors += 1
                continue

            analyzed += 1

            signal = generate_signal(
                ticker, candles15, candles1h
            )

            if signal:
                signals.append(signal)
                log.info(
                    "Candidate: %s %s score=%d",
                    signal["symbol"],
                    signal["side"],
                    signal["score"],
                )
            else:
                rejected += 1

            time.sleep(REQUEST_PAUSE)

        signals.sort(
            key=lambda item: item["score"],
            reverse=True,
        )
        signals = signals[:MAX_SIGNALS]

        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")

        message = (
            "🐋 ETH WHALE\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📊 BITPIN SMART MARKET WATCH\n"
            "🧠 EMA20 • EMA50 • RSI • VOLUME\n"
            "⏱ تایم‌فریم: 15 دقیقه + 1 ساعت\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 زمان بررسی: {timestamp}\n"
            f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
            f"⚙️ اهرم فرضی: {LEVERAGE}x\n"
            f"💵 ارزش فرضی موقعیت: {POSITION_VALUE:.2f} USDT\n"
            "🔒 سفارش واقعی: غیرفعال\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 بازارهای دارای قیمت معتبر: {len(tickers)}\n"
            f"🔎 بازارهای انتخاب‌شده: {len(selected)}\n"
            f"✅ بازارهای تحلیل‌شده: {analyzed}\n"
            f"⚠️ خطا یا کمبود کندل: {candle_errors}\n"
            f"⏳ بازارهای بدون سیگنال: {rejected}\n"
            f"🎯 سیگنال‌های واجد شرایط: {len(signals)}\n"
        )

        if signals:
            for index, signal in enumerate(signals, start=1):
                message += format_signal(signal, index)
        else:
            message += (
                "\n⏳ وضعیت بازار: WAIT\n"
                "هیچ بازار بررسی‌شده‌ای تمام شرایط ورود را "
                "هم‌زمان تأیید نکرد.\n"
                "اگر خطای کندل زیاد باشد، ابتدا اتصال API "
                "و قالب داده‌های کندل باید بررسی شود.\n"
            )

        message += (
            "\n━━━━━━━━━━━━━━━━━━━━\n"
            "🧪 PAPER MODE: ON\n"
            "🚫 REAL ORDERS: OFF\n"
            "📌 تحلیل تکنیکال تضمین سود نیست.\n"
            "ℹ️ سود و زیان تخمینی، ناخالص و فرضی است.\n"
            "🐋 ETH WHALE | BITPIN\n"
        )

        print(message)
        send_telegram(message)

        log.info("Scan completed successfully.")
        return 0

    except Exception as exc:
        log.exception("Bot execution failed")

        try:
            send_telegram(
                "⚠️ ETH WHALE | BITPIN\n"
                "خطا هنگام اسکن بازار رخ داد.\n"
                f"نوع خطا: {type(exc).__name__}\n"
                "لطفاً گزارش GitHub Actions را بررسی کن.\n"
                "🚫 سفارش واقعی ثبت نشده است."
            )
        except Exception:
            log.exception("Telegram error notification failed")

        return 1


if __name__ == "__main__":
    sys.exit(main())
