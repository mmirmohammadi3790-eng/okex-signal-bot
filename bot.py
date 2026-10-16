
# -*- coding: utf-8 -*-
"""
ETH WHALE - BITPIN SMART SIGNAL BOT
Balanced multi-timeframe technical analysis
EMA20 / EMA50 / RSI / Volume
PAPER TRADING ONLY - NO REAL ORDERS
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone

import requests


# ============================================================
# 1. SETTINGS
# ============================================================

BOT_NAME = "ETH WHALE"
BASE_URL = "https://api.bitpin.ir"

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)

TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID", "").strip()
    or os.getenv("CHAT_ID", "").strip()
)

PAPER_MODE = True
REAL_ORDERS_ENABLED = False

CAPITAL_USDT = 48.0
LEVERAGE = 3
POSITION_VALUE = CAPITAL_USDT * LEVERAGE

MAX_MARKETS = 35
MAX_SIGNALS = 5
MIN_SCORE = 65
STRONG_SCORE = 80

CANDLE_LIMIT = 100
REQUEST_TIMEOUT = 15
REQUEST_PAUSE = 0.15

STOP_PERCENT = 1.5
TP1_PERCENT = 1.5
TP2_PERCENT = 3.0
TP3_PERCENT = 4.5

MIN_VOLUME_RATIO = 0.80

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("eth-whale")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Bitpin-PaperBot/3.0",
    "Accept": "application/json",
})


# ============================================================
# 2. HTTP HELPERS
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

        result = float(str(value).replace(",", ""))

        if result != result or abs(result) == float("inf"):
            return None

        return result

    except (TypeError, ValueError):
        return None


def get_first_number(row, keys):
    for key in keys:
        result = to_float(row.get(key))
        if result is not None:
            return result

    return None


def unwrap_list(data):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

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
            for nested_key in (
                "results",
                "data",
                "list",
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

    for symbol, item in data.items():
        if isinstance(item, dict):
            row = dict(item)
            row.setdefault("symbol", symbol)
            converted.append(row)

    return converted


# ============================================================
# 3. BITPIN TICKERS
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

            for row in rows:
                raw_symbol = (
                    row.get("symbol")
                    or row.get("code")
                    or row.get("market")
                    or ""
                )

                symbol = str(raw_symbol).upper().strip()
                symbol = symbol.replace("-", "_")
                symbol = symbol.replace("/", "_")

                if not (
                    symbol.endswith("_USDT")
                    or symbol.endswith("USDT")
                ):
                    continue

                price = get_first_number(
                    row,
                    (
                        "last",
                        "last_price",
                        "lastPrice",
                        "price",
                        "close",
                    ),
                )

                volume = get_first_number(
                    row,
                    (
                        "quote_volume",
                        "quoteVolume",
                        "volume_24h",
                        "volume24h",
                        "base_volume",
                        "baseVolume",
                        "volume",
                    ),
                )

                if price is None or price <= 0:
                    continue

                tickers.append({
                    "symbol": symbol.replace("_", "-"),
                    "api_symbol": symbol,
                    "price": price,
                    "volume": (
                        volume if volume is not None else 0.0
                    ),
                })

            if tickers:
                tickers.sort(
                    key=lambda item: item["volume"],
                    reverse=True,
                )

                log.info(
                    "USDT markets found: %s",
                    len(tickers),
                )

                return tickers

            errors.append(f"{url}: no valid tickers")

        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError(
        "Bitpin ticker API failed: " + " | ".join(errors)
    )


# ============================================================
# 4. CANDLE DATA
# ============================================================

def parse_candle(row):
    if isinstance(row, dict):
        return {
            "open": to_float(row.get("open")),
            "high": to_float(
                row.get("high", row.get("max"))
            ),
            "low": to_float(
                row.get("low", row.get("min"))
            ),
            "close": to_float(
                row.get("close", row.get("price"))
            ),
            "volume": to_float(
                row.get("volume", row.get("vol"))
            ),
        }

    if isinstance(row, (list, tuple)) and len(row) >= 6:
        # Expected order:
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
    rows = payload

    if isinstance(payload, dict):
        rows = None

        for key in (
            "results",
            "data",
            "candles",
            "ohlcv",
            "history",
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

        required = (
            "open",
            "high",
            "low",
            "close",
        )

        if any(
            candle[key] is None
            for key in required
        ):
            continue

        if any(
            candle[key] <= 0
            for key in required
        ):
            continue

        candle["volume"] = max(
            0.0,
            candle["volume"] or 0.0,
        )

        candles.append(candle)

    return candles


def get_candles(symbol, timeframe):
    """
    Try common public candle API patterns.

    The current Bitpin API route and parameter format must
    be verified against actual API responses. No synthetic
    candle data is generated if requests fail.
    """

    endpoints = [
        (
            f"{BASE_URL}/api/v1/mkt/ohlcv/{symbol}/",
            {
                "interval": timeframe,
                "limit": CANDLE_LIMIT,
            },
        ),
        (
            f"{BASE_URL}/api/v1/mkt/ohlcv/",
            {
                "symbol": symbol,
                "interval": timeframe,
                "limit": CANDLE_LIMIT,
            },
        ),
        (
            f"{BASE_URL}/api/v1/mkt/candles/{symbol}/",
            {
                "interval": timeframe,
                "limit": CANDLE_LIMIT,
            },
        ),
        (
            f"{BASE_URL}/api/v1/mkt/candles/",
            {
                "symbol": symbol,
                "interval": timeframe,
                "limit": CANDLE_LIMIT,
            },
        ),
    ]

    for url, params in endpoints:
        try:
            payload = get_json(url, params)
            candles = normalize_candles(payload)

            if len(candles) >= 55:
                log.info(
                    "%s candles received for %s: %d",
                    timeframe,
                    symbol,
                    len(candles),
                )

                return candles[-CANDLE_LIMIT:]

        except (requests.RequestException, ValueError) as exc:
            log.debug(
                "Candle request failed %s %s: %s",
                symbol,
                timeframe,
                exc,
            )

        time.sleep(REQUEST_PAUSE)

    log.warning(
        "No valid candles for %s timeframe %s",
        symbol,
        timeframe,
    )

    return []


# ============================================================
# 5. EMA
# ============================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    current = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)

    for value in values[period:]:
        current = (
            alpha * value
            + (1.0 - alpha) * current
        )

    return current


# ============================================================
# 6. RSI
# ============================================================

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
            avg_gain * (period - 1)
            + gains[index]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[index]
        ) / period

    if avg_loss == 0:
        if avg_gain == 0:
            return 50.0
        return 100.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


# ============================================================
# 7. TECHNICAL ANALYSIS
# ============================================================

def analyze_candles(candles):
    if len(candles) < 55:
        return None

    closes = [candle["close"] for candle in candles]
    volumes = [candle["volume"] for candle in candles]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi14 = calculate_rsi(closes, 14)

    if (
        ema20 is None
        or ema50 is None
        or rsi14 is None
    ):
        return None

    previous_volumes = volumes[-21:-1]

    average_volume = (
        sum(previous_volumes) / len(previous_volumes)
        if previous_volumes
        else 0.0
    )

    latest_volume = volumes[-1]

    volume_ratio = (
        latest_volume / average_volume
        if average_volume > 0
        else None
    )

    return {
        "price": closes[-1],
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "volume": latest_volume,
        "average_volume": average_volume,
        "volume_ratio": volume_ratio,
    }


# ============================================================
# 8. SIGNAL ENGINE
# ============================================================

def generate_signal(ticker, candles15, candles1h):
    analysis15 = analyze_candles(candles15)
    analysis1h = analyze_candles(candles1h)

    if not analysis15 or not analysis1h:
        return None

    volume_ratio = analysis15["volume_ratio"]

    if volume_ratio is None:
        return None

    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    long_trend = (
        analysis15["ema20"] > analysis15["ema50"]
        and analysis1h["ema20"] > analysis1h["ema50"]
    )

    short_trend = (
        analysis15["ema20"] < analysis15["ema50"]
        and analysis1h["ema20"] < analysis1h["ema50"]
    )

    rsi15 = analysis15["rsi"]
    rsi1h = analysis1h["rsi"]

    if long_trend:
        if not 50 <= rsi15 <= 70:
            return None

        if not 45 <= rsi1h <= 72:
            return None

        side = "LONG"

    elif short_trend:
        if not 30 <= rsi15 <= 50:
            return None

        if not 28 <= rsi1h <= 55:
            return None

        side = "SHORT"

    else:
        return None

    score = 60

    # EMA trend agreement
    score += 10

    # Volume confirmation
    if 1.0 <= volume_ratio < 1.5:
        score += 5
    elif volume_ratio >= 1.5:
        score += 10

    # RSI quality
    if side == "LONG" and 52 <= rsi15 <= 65:
        score += 5

    if side == "SHORT" and 35 <= rsi15 <= 48:
        score += 5

    score = min(score, 95)

    if score < MIN_SCORE:
        return None

    entry = analysis15["price"]

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

    # The following figures are hypothetical only.
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
        "ema20_15": analysis15["ema20"],
        "ema50_15": analysis15["ema50"],
        "ema20_1h": analysis1h["ema20"],
        "ema50_1h": analysis1h["ema50"],
        "volume_ratio": volume_ratio,
        "position_value": POSITION_VALUE,
        "pnl_tp1": estimate_pnl(tp1),
        "pnl_tp2": estimate_pnl(tp2),
        "pnl_tp3": estimate_pnl(tp3),
        "pnl_stop": estimate_pnl(stop),
    }


# ============================================================
# 9. TELEGRAM MESSAGE FORMAT
# ============================================================

def format_price(value):
    if value >= 1000:
        return f"{value:,.4f}".rstrip("0").rstrip(".")

    if value >= 1:
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
        f"\n━━━━━━━━━━━━━━━━━━━━\n"
        f"{index}. {emoji} {signal['symbol']}\n"
        f"📌 جهت: {signal['side']}\n"
        f"⭐ امتیاز: {signal['score']}/100 {strength}\n"
        f"💵 ورود فرضی: {format_price(signal['entry'])}\n"
        f"🛑 حد ضرر: {format_price(signal['stop'])}\n"
        f"🥇 هدف ۱: {format_price(signal['tp1'])}\n"
        f"🥈 هدف ۲: {format_price(signal['tp2'])}\n"
        f"🥉 هدف ۳: {format_price(signal['tp3'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
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
        f"🧮 سود فرضی هدف ۱: "
        f"{signal['pnl_tp1']:+.2f} USDT\n"
        f"🧮 سود فرضی هدف ۲: "
        f"{signal['pnl_tp2']:+.2f} USDT\n"
        f"🧮 سود فرضی هدف ۳: "
        f"{signal['pnl_tp3']:+.2f} USDT\n"
        f"🧮 زیان فرضی حد ضرر: "
        f"{signal['pnl_stop']:+.2f} USDT\n"
    )


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Missing Telegram token or chat ID."
        )

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

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
                f"Telegram API returned an error: {result}"
            )


# ============================================================
# 10. MAIN
# ============================================================

def main():
    if PAPER_MODE is not True or REAL_ORDERS_ENABLED is not False:
        raise RuntimeError(
            "Safety check failed. Real trading is prohibited."
        )

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "in GitHub Actions secrets."
        )
        return 1

    try:
        tickers = get_tickers()

        selected = tickers[:MAX_MARKETS]

        log.info(
            "Markets available=%d, selected=%d",
            len(tickers),
            len(selected),
        )

        signals = []
        analyzed = 0
        candle_errors = 0

        for index, ticker in enumerate(selected, start=1):
            symbol = ticker["api_symbol"]

            log.info(
                "Analyzing %d/%d: %s",
                index,
                len(selected),
                symbol,
            )

            candles15 = get_candles(symbol, "15m")
            candles1h = get_candles(symbol, "1h")

            if not candles15 or not candles1h:
                candle_errors += 1
                continue

            analyzed += 1

            signal = generate_signal(
                ticker,
                candles15,
                candles1h,
            )

            if signal:
                signals.append(signal)

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
            "📊 BITPIN SMART SIGNALS\n"
            "🧠 EMA20 + EMA50 + RSI + VOLUME\n"
            "⏱ تایم‌فریم: 15m + 1h\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 زمان بررسی: {timestamp}\n"
            f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
            f"⚙️ اهرم فرضی: {LEVERAGE}x\n"
            f"💵 ارزش فرضی موقعیت: "
            f"{POSITION_VALUE:.2f} USDT\n"
            "🔒 سفارش واقعی: غیرفعال\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 بازارهای USDT: {len(tickers)}\n"
            f"🔎 بازارهای انتخاب‌شده: {len(selected)}\n"
            f"✅ بازارهای تحلیل‌شده: {analyzed}\n"
            f"⚠️ خطا یا کمبود کندل: {candle_errors}\n"
            f"🎯 سیگنال‌های معتبر: {len(signals)}\n"
        )

        if signals:
            for index, signal in enumerate(signals, start=1):
                message += format_signal(signal, index)
        else:
            message += (
                "\n⏳ وضعیت بازار: WAIT\n"
                "هیچ بازاری تمام فیلترهای روند، RSI و حجم "
                "را هم‌زمان تأیید نکرد.\n"
            )

        message += (
            "\n━━━━━━━━━━━━━━━━━━━━\n"
            "🧪 PAPER MODE: ON\n"
            "🚫 REAL ORDERS: OFF\n"
            "ℹ️ سود و زیان فرضی است؛ کارمزد، لغزش قیمت "
            "و احتمال اجرا لحاظ نشده‌اند.\n"
            "⚠️ سیگنال تضمین سود نیست.\n"
            "🐋 ETH WHALE | BITPIN\n"
        )

        print(message)
        send_telegram(message)

        log.info("Bot completed successfully.")
        return 0

    except Exception as exc:
        log.exception("Bot execution failed")

        try:
            send_telegram(
                "⚠️ ETH WHALE | BITPIN\n"
                "خطا در اسکن بازار رخ داد.\n"
                f"نوع خطا: {type(exc).__name__}\n"
                "گزارش GitHub Actions را بررسی کن.\n"
                "سفارش واقعی ثبت نشده است."
            )
        except Exception:
            log.exception("Telegram error notification failed")

        return 1


if __name__ == "__main__":
    sys.exit(main())
