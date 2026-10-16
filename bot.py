
# ============================================================
# ETH WHALE - BITPIN SMART MARKET WATCH
# PAPER SIGNALS ONLY - NO REAL ORDERS
# Capital: 48 USDT | Simulated leverage: 3x
# Timeframes: 15m + 1h
# Indicators: EMA20, EMA50, RSI14, Volume, ATR
# ============================================================

import os
import re
import html
import time
import logging
from datetime import datetime, timezone

import requests


# ======================== CONFIG =============================

BOT_NAME = "🐋 ETH WHALE"

BITPIN_BASES = [
    "https://api.bitpin.ir",
    "https://api.bitpin.org",
]

MARKET_PATHS = [
    "/v1/mkt/markets/",
    "/api/v1/mkt/markets/",
    "/v1/mkt/markets",
    "/api/v1/mkt/markets",
]

TICKER_PATHS = [
    "/v1/mkt/tickers/",
    "/api/v1/mkt/tickers/",
    "/v1/mkt/tickers",
    "/api/v1/mkt/tickers",
]

BINANCE_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
]

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or ""
).strip()

CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
    or ""
).strip()

CAPITAL_USDT = 48.0
LEVERAGE = 3
MAX_SIGNALS = 3
MAX_MARKETS = 30

MIN_SCORE = 65
STRONG_SCORE = 80

MIN_VOLUME_RATIO = 1.10
MIN_ATR_PERCENT = 0.05
MAX_ATR_PERCENT = 5.0

CANDLE_LIMIT = 100
PAPER_ONLY = True

EXCLUDED_BASES = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD",
    "USDE", "USDS", "USDD", "USDP", "PYUSD",
    "BUSD", "EURC", "USD1", "UST", "USTC",
    "FRAX", "LUSD", "USDX", "USDK", "WBTC",
}

HEADERS = {
    "User-Agent": "ETH-WHALE-Paper-Market-Watch/1.0",
    "Accept": "application/json",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ======================== HELPERS ===========================

def safe_float(value, default=None):
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace(",", "").strip()

        result = float(value)

        if result != result:
            return default

        return result
    except (TypeError, ValueError):
        return default


def get_json(url, params=None, timeout=12):
    response = SESSION.get(
        url,
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def normalize_symbol(symbol):
    if not symbol:
        return ""

    if isinstance(symbol, dict):
        symbol = (
            symbol.get("symbol")
            or symbol.get("code")
            or symbol.get("name")
            or ""
        )

    return re.sub(r"[^A-Z0-9]", "", str(symbol).upper())


def currency_code(value):
    if isinstance(value, dict):
        for key in ("code", "symbol", "name", "currency"):
            if value.get(key):
                return str(value[key]).upper().strip()
        return ""

    if value is None:
        return ""

    return str(value).upper().strip()


def market_symbol(row):
    if not isinstance(row, dict):
        return ""

    for key in (
        "symbol", "market", "pair", "code",
        "market_symbol", "name",
    ):
        value = row.get(key)

        if isinstance(value, str) and value.strip():
            normalized = normalize_symbol(value)

            if normalized.endswith("USDT"):
                return normalized

    base = (
        row.get("base_currency")
        or row.get("base")
        or row.get("currency1")
        or row.get("baseAsset")
    )

    quote = (
        row.get("quote_currency")
        or row.get("quote")
        or row.get("currency2")
        or row.get("quoteAsset")
    )

    base = currency_code(base)
    quote = currency_code(quote)

    if base and quote:
        pair = normalize_symbol(base + quote)

        if pair.endswith("USDT"):
            return pair

    return ""


def flatten_records(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if not isinstance(data, dict):
        return []

    for key in (
        "data", "results", "markets", "tickers",
        "items", "result", "list",
    ):
        value = data.get(key)

        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

        if isinstance(value, dict):
            nested = flatten_records(value)

            if nested:
                return nested

    if any(
        key in data
        for key in (
            "last", "last_price", "price",
            "lastPrice", "base_currency", "currency1",
        )
    ):
        return [data]

    records = []

    for key, value in data.items():
        if isinstance(value, dict):
            row = dict(value)

            if not any(
                row.get(field)
                for field in ("symbol", "market", "pair", "code")
            ):
                row["symbol"] = key

            records.append(row)

    return records


# ======================== BITPIN API ========================

def fetch_bitpin_endpoint(paths):
    errors = []

    for base in BITPIN_BASES:
        for path in paths:
            url = base + path

            try:
                data = get_json(url)
                records = flatten_records(data)

                if records:
                    logging.info(
                        "Bitpin endpoint OK: %s (%s records)",
                        url,
                        len(records),
                    )
                    return records, url

                errors.append(f"{url}: empty response")

            except Exception as exc:
                errors.append(
                    f"{url}: {type(exc).__name__}"
                )

    logging.warning(
        "Bitpin API discovery failed: %s",
        " | ".join(errors[-6:]),
    )

    return [], ""


def get_bitpin_markets():
    records, source = fetch_bitpin_endpoint(MARKET_PATHS)
    markets = {}

    for row in records:
        symbol = market_symbol(row)

        if not symbol or not symbol.endswith("USDT"):
            continue

        base = symbol[:-4]

        if not base or base in EXCLUDED_BASES:
            continue

        markets[symbol] = {
            "symbol": symbol,
            "base": base,
            "source": source,
        }

    return list(markets.values())


def get_bitpin_tickers():
    records, source = fetch_bitpin_endpoint(TICKER_PATHS)
    tickers = {}

    for row in records:
        symbol = market_symbol(row)

        if not symbol:
            symbol = normalize_symbol(
                row.get("symbol")
                or row.get("market")
                or row.get("pair")
                or row.get("code")
            )

        if not symbol or not symbol.endswith("USDT"):
            continue

        base = symbol[:-4]

        if base in EXCLUDED_BASES:
            continue

        price = None

        for key in (
            "last", "last_price", "lastPrice",
            "price", "close", "lastPriceDecimal",
        ):
            price = safe_float(row.get(key))

            if price is not None and price > 0:
                break

        if price is None or price <= 0:
            continue

        volume = None

        for key in (
            "quote_volume", "quoteVolume",
            "volume", "quote_volume_24h",
            "volume_24h", "volume24h",
        ):
            volume = safe_float(row.get(key))

            if volume is not None and volume >= 0:
                break

        tickers[symbol] = {
            "price": price,
            "volume": volume,
            "source": source,
        }

    return tickers


# ======================== BINANCE CANDLES ===================

def fetch_candles(symbol, interval):
    last_error = None

    for base in BINANCE_BASES:
        url = base + "/api/v3/klines"

        try:
            data = get_json(
                url,
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "limit": CANDLE_LIMIT,
                },
                timeout=15,
            )

            if not isinstance(data, list) or len(data) < 55:
                raise ValueError("Not enough candles")

            candles = []

            for item in data:
                if not isinstance(item, list) or len(item) < 6:
                    continue

                candles.append({
                    "open": safe_float(item[1], 0.0),
                    "high": safe_float(item[2], 0.0),
                    "low": safe_float(item[3], 0.0),
                    "close": safe_float(item[4], 0.0),
                    "volume": safe_float(item[5], 0.0),
                })

            if len(candles) < 55:
                raise ValueError("Not enough valid candles")

            return candles

        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        f"Candles unavailable for {symbol}/{interval}: "
        f"{last_error}"
    )


# ======================== INDICATORS ========================

def ema_series(values, period):
    if len(values) < period:
        return []

    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    result = [current]

    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
        result.append(current)

    return result


def calculate_rsi(values, period=14):
    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    true_ranges = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )

    if len(true_ranges) < period:
        return 0.0

    return sum(true_ranges[-period:]) / period


def analyze_timeframe(candles):
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    ema20_values = ema_series(closes, 20)
    ema50_values = ema_series(closes, 50)

    if not ema20_values or not ema50_values:
        raise ValueError("EMA calculation failed")

    ema20 = ema20_values[-1]
    ema50 = ema50_values[-1]
    close = closes[-1]

    rsi = calculate_rsi(closes, 14)
    atr = calculate_atr(candles, 14)

    previous_volumes = volumes[-21:-1]
    average_volume = (
        sum(previous_volumes) / len(previous_volumes)
        if previous_volumes else 0.0
    )

    current_volume = volumes[-1]

    volume_ratio = (
        current_volume / average_volume
        if average_volume > 0 else 0.0
    )

    if close > ema20 > ema50:
        trend = "LONG"
    elif close < ema20 < ema50:
        trend = "SHORT"
    else:
        trend = "WAIT"

    atr_percent = atr / close * 100.0 if close > 0 else 0.0

    return {
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "atr_percent": atr_percent,
        "volume_ratio": volume_ratio,
        "trend": trend,
    }


# ======================== SIGNAL ENGINE ====================

def evaluate_market(symbol, bitpin_price):
    candles_15m = fetch_candles(symbol, "15m")
    candles_1h = fetch_candles(symbol, "1h")

    a15 = analyze_timeframe(candles_15m)
    a1h = analyze_timeframe(candles_1h)

    if bitpin_price <= 0:
        return None, "invalid_price"

    direction = a15["trend"]

    if direction == "WAIT" or a1h["trend"] != direction:
        return None, "trend_mismatch"

    rsi15 = a15["rsi"]
    rsi1h = a1h["rsi"]

    if direction == "LONG":
        if not 45 <= rsi15 <= 70:
            return None, "rsi15_out_of_range"

        if not 40 <= rsi1h <= 75:
            return None, "rsi1h_out_of_range"

    else:
        if not 30 <= rsi15 <= 55:
            return None, "rsi15_out_of_range"

        if not 25 <= rsi1h <= 60:
            return None, "rsi1h_out_of_range"

    volume_ratio = a15["volume_ratio"]

    if volume_ratio < MIN_VOLUME_RATIO:
        return None, "low_volume"

    atr = a15["atr"]
    atr_percent = a15["atr_percent"]

    if atr <= 0:
        return None, "invalid_atr"

    if not MIN_ATR_PERCENT <= atr_percent <= MAX_ATR_PERCENT:
        return None, "atr_out_of_range"

    score = 30

    if direction == "LONG":
        if 50 <= rsi15 <= 65:
            score += 15
        elif 45 <= rsi15 < 50 or 65 < rsi15 <= 70:
            score += 8

        if 50 <= rsi1h <= 65:
            score += 15
        elif 40 <= rsi1h < 50 or 65 < rsi1h <= 75:
            score += 8

    else:
        if 35 <= rsi15 <= 50:
            score += 15
        elif 30 <= rsi15 < 35 or 50 < rsi15 <= 55:
            score += 8

        if 35 <= rsi1h <= 50:
            score += 15
        elif 25 <= rsi1h < 35 or 50 < rsi1h <= 60:
            score += 8

    if volume_ratio >= 1.8:
        score += 20
    elif volume_ratio >= 1.4:
        score += 15
    elif volume_ratio >= 1.1:
        score += 10

    separation = abs(a15["ema20"] - a15["ema50"]) / bitpin_price

    if separation >= 0.003:
        score += 10
    elif separation >= 0.001:
        score += 5

    if score < MIN_SCORE:
        return None, "score_too_low"

    entry = bitpin_price

    stop_distance = max(
        atr * 1.5,
        entry * 0.004,
    )

    stop_distance = min(
        stop_distance,
        entry * 0.025,
    )

    if direction == "LONG":
        sl = entry - stop_distance
        tp1 = entry + stop_distance
        tp2 = entry + stop_distance * 1.7
        tp3 = entry + stop_distance * 2.5
    else:
        sl = entry + stop_distance
        tp1 = entry - stop_distance
        tp2 = entry - stop_distance * 1.7
        tp3 = entry - stop_distance * 2.5

    margin = CAPITAL_USDT / MAX_SIGNALS
    notional = margin * LEVERAGE
    quantity = notional / entry

    estimated_loss = quantity * abs(entry - sl)
    profit_tp1 = quantity * abs(tp1 - entry)
    profit_tp2 = quantity * abs(tp2 - entry)
    profit_tp3 = quantity * abs(tp3 - entry)

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "volume_ratio": volume_ratio,
        "atr_percent": atr_percent,
        "margin": margin,
        "notional": notional,
        "quantity": quantity,
        "estimated_loss": estimated_loss,
        "profit_tp1": profit_tp1,
        "profit_tp2": profit_tp2,
        "profit_tp3": profit_tp3,
        "strong": score >= STRONG_SCORE,
    }, "signal"


# ======================== TELEGRAM ==========================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram credentials missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = SESSION.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        if response.status_code != 200:
            logging.error(
                "Telegram error %s: %s",
                response.status_code,
                response.text[:300],
            )
            return False

        result = response.json()

        if not result.get("ok"):
            logging.error("Telegram rejected message.")
            return False

        return True

    except Exception:
        logging.exception("Telegram send failed.")
        return False


def format_price(value):
    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")

    return f"{value:.8f}".rstrip("0").rstrip(".")


def format_signal(signal, number):
    direction = signal["direction"]
    icon = "🟢" if direction == "LONG" else "🔴"
    strength = "🔥 قوی" if signal["strong"] else "⚖️ متعادل"

    return (
        f"\n<b>{number}. {icon} "
        f"{html.escape(signal['symbol'])} {direction}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⭐ امتیاز: <b>{signal['score']}/100</b> | {strength}\n"
        f"💵 ورود: <code>{format_price(signal['entry'])}</code>\n"
        f"🛑 حد ضرر: <code>{format_price(signal['sl'])}</code>\n"
        f"🎯 هدف ۱: <code>{format_price(signal['tp1'])}</code>\n"
        f"🎯 هدف ۲: <code>{format_price(signal['tp2'])}</code>\n"
        f"🎯 هدف ۳: <code>{format_price(signal['tp3'])}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI 15m: {signal['rsi15']:.1f} | "
        f"RSI 1h: {signal['rsi1h']:.1f}\n"
        f"📈 نسبت حجم: {signal['volume_ratio']:.2f}x\n"
        f"🌊 ATR: {signal['atr_percent']:.2f}%\n"
        f"💰 مارجین فرضی: {signal['margin']:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"📦 ارزش فرضی موقعیت: {signal['notional']:.2f} USDT\n"
        f"🔢 مقدار فرضی: {signal['quantity']:.8f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📉 زیان تخمینی تا SL: "
        f"<b>{signal['estimated_loss']:.3f} USDT</b>\n"
        f"✅ سود تخمینی هدف ۱: +{signal['profit_tp1']:.3f} USDT\n"
        f"✅ سود تخمینی هدف ۲: +{signal['profit_tp2']:.3f} USDT\n"
        f"✅ سود تخمینی هدف ۳: +{signal['profit_tp3']:.3f} USDT\n"
        f"<i>بدون احتساب کارمزد، اسپرد و لغزش قیمت</i>\n"
    )


def send_report(
    signals,
    market_count,
    analyzed_count,
    stats,
    missing_examples,
    errors,
):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = (
        f"<b>{BOT_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>BITPIN SMART MARKET WATCH</b>\n"
        f"🧪 <b>PAPER SIGNALS ONLY</b>\n"
        f"🚫 Real Orders: <b>OFF</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"💵 مارجین فرضی هر موقعیت: "
        f"{CAPITAL_USDT / MAX_SIGNALS:.2f} USDT\n"
        f"📦 ارزش فرضی هر موقعیت: "
        f"{CAPITAL_USDT / MAX_SIGNALS * LEVERAGE:.2f} USDT\n"
        f"⏱ تایم‌فریم‌ها: 15m + 1h\n"
        f"📈 قیمت ورود: Bitpin\n"
        f"📊 کندل‌ها: Binance public API\n"
        f"🧹 استیبل‌کوین‌ها: حذف از سیگنال\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔎 بازارهای انتخاب‌شده: {market_count}\n"
        f"✅ بازارهای تحلیل‌شده: {analyzed_count}\n"
        f"🎯 سیگنال‌های معتبر: {len(signals)}\n"
        f"🕒 زمان: {now}\n"
    )

    if signals:
        for i, signal in enumerate(signals, start=1):
            message += format_signal(signal, i)
    else:
        message += (
            "\n⏸️ <b>فعلاً سیگنال معتبری پیدا نشد.</b>\n"
            "فیلترها برای جلوگیری از سیگنال ضعیف فعال هستند.\n"
        )

    message += "\n━━━━━━━━━━━━━━━━━━\n<b>📋 آمار فیلترها</b>\n"

    for reason, count in sorted(
        stats.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        message += f"• {html.escape(reason)}: {count}\n"

    if missing_examples:
        message += (
            "\n⚠️ <b>نمونه نمادهای بدون تیکر متناظر</b>\n"
            + ", ".join(
                html.escape(x) for x in missing_examples[:8]
            )
            + "\n"
        )

    if errors:
        message += f"\n⚠️ خطاهای کندل/تحلیل: {errors}\n"

    message += (
        "\n<i>این پیام فقط تحلیل آزمایشی است؛ "
        "قیمت و سود تضمین‌شده نیستند.</i>"
    )

    telegram_send(message)


# ======================== MAIN SCAN =========================

def main():
    logging.info("Starting ETH WHALE paper scan.")

    if not PAPER_ONLY:
        raise RuntimeError(
            "Safety check failed: bot must remain paper-only."
        )

    markets = get_bitpin_markets()
    tickers = get_bitpin_tickers()

    if not markets:
        telegram_send(
            "🐋 <b>ETH WHALE</b>\n"
            "❌ دریافت فهرست بازارهای بیت‌پین ناموفق بود.\n"
            "لطفاً لاگ GitHub Actions را بررسی کن."
        )
        raise RuntimeError("No Bitpin markets discovered.")

    if not tickers:
        telegram_send(
            "🐋 <b>ETH WHALE</b>\n"
            "❌ دریافت تیکرهای بیت‌پین ناموفق بود."
        )
        raise RuntimeError("No Bitpin tickers discovered.")

    matched = []
    missing_examples = []

    ticker_symbols = set(tickers.keys())

    for market in markets:
        symbol = market["symbol"]

        if symbol in ticker_symbols:
            matched.append(market)
        elif len(missing_examples) < 12:
            missing_examples.append(symbol)

    matched.sort(
        key=lambda market: (
            tickers[market["symbol"]]["volume"]
            if tickers[market["symbol"]]["volume"] is not None
            else -1
        ),
        reverse=True,
    )

    selected = matched[:MAX_MARKETS]

    stats = {
        "missing_ticker": len(markets) - len(matched),
        "low_volume": 0,
        "trend_mismatch": 0,
        "rsi_filter": 0,
        "atr_filter": 0,
        "score_too_low": 0,
        "signal": 0,
        "candle_or_analysis_error": 0,
        "invalid_price": 0,
    }

    signals = []
    analyzed_count = 0
    errors = 0

    for market in selected:
        symbol = market["symbol"]
        ticker = tickers.get(symbol)

        if not ticker:
            continue

        try:
            signal, reason = evaluate_market(
                symbol,
                ticker["price"],
            )
            analyzed_count += 1

            if signal:
                signals.append(signal)
                stats["signal"] += 1
            elif reason == "low_volume":
                stats["low_volume"] += 1
            elif reason == "trend_mismatch":
                stats["trend_mismatch"] += 1
            elif reason in (
                "rsi15_out_of_range",
                "rsi1h_out_of_range",
            ):
                stats["rsi_filter"] += 1
            elif reason == "atr_out_of_range":
                stats["atr_filter"] += 1
            elif reason == "score_too_low":
                stats["score_too_low"] += 1
            elif reason == "invalid_price":
                stats["invalid_price"] += 1

        except Exception as exc:
            errors += 1
            stats["candle_or_analysis_error"] += 1

            logging.warning(
                "Analysis failed for %s: %s",
                symbol,
                exc,
            )

        time.sleep(0.15)

    signals.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    signals = signals[:MAX_SIGNALS]

    send_report(
        signals=signals,
        market_count=len(selected),
        analyzed_count=analyzed_count,
        stats=stats,
        missing_examples=missing_examples,
        errors=errors,
    )

    logging.info(
        "Scan complete: markets=%s analyzed=%s signals=%s errors=%s",
        len(selected),
        analyzed_count,
        len(signals),
        errors,
    )


if __name__ == "__main__":
    main()
