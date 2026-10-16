
import os
import time
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# ETH WHALE | BITPIN FUTURES SIGNAL SCANNER
# PAPER ONLY - NO REAL ORDERS
# ============================================================

BASE_URL = "https://api.bitpin.org"
CAPITAL_USDT = 48.0
LEVERAGE = 3
MARGIN_USDT = 8.0
MAX_SIGNALS = 3
MIN_SCORE = 75
CANDLE_COUNT = 150
TIMEOUT = 20

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

session = requests.Session()
session.headers.update({"User-Agent": "ETH-WHALE-PaperBot/1.0"})


def get_json(path, params=None):
    url = BASE_URL + path
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def telegram_send(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram secrets missing; report printed only.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": text},
        timeout=TIMEOUT
    )
    response.raise_for_status()

    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected message")


def as_float(value):
    try:
        result = float(value)
        if result == result and abs(result) != float("inf"):
            return result
    except (TypeError, ValueError):
        pass
    return None


def rows_from_response(data, keys=()):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

        for value in data.values():
            if isinstance(value, list):
                return value

    return []


def market_symbol(item):
    for key in ("symbol", "code", "market_symbol"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper().replace("-", "_")
    return ""


def market_type_text(item):
    keys = (
        "type", "market_type", "category", "instrument_type",
        "contract_type", "product_type", "market"
    )
    values = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, (str, int)):
            values.append(str(value).lower())
    return " ".join(values)


def explicitly_futures(item):
    """
    Fail closed: accept only metadata explicitly identifying
    a futures, perpetual, swap, or derivative instrument.
    Do not infer futures from a USDT symbol alone.
    """
    text = market_type_text(item)

    explicit_true_keys = (
        "is_futures", "is_future", "is_perpetual",
        "is_derivative", "futures_enabled"
    )

    for key in explicit_true_keys:
        if item.get(key) is True:
            return True

    if any(word in text for word in (
        "futures", "future", "perpetual", "derivative", "swap"
    )):
        return True

    return False


def load_markets():
    errors = []

    for path in (
        "/api/v1/mkt/markets/",
        "/v1/mkt/markets/"
    ):
        try:
            data = get_json(path)
            rows = rows_from_response(data, ("results", "markets"))

            if rows:
                logging.info("Loaded %s markets from %s", len(rows), path)
                return rows

            errors.append(f"{path}: empty/unrecognized response")

        except Exception as exc:
            errors.append(f"{path}: {exc}")

    raise RuntimeError("Could not load market list: " + " | ".join(errors))


def load_candles(symbol, resolution, count=CANDLE_COUNT):
    now = int(time.time())

    seconds_per_candle = {
        "15m": 15 * 60,
        "1h": 60 * 60
    }

    if resolution not in seconds_per_candle:
        raise ValueError("Unsupported timeframe: " + resolution)

    start = now - seconds_per_candle[resolution] * count

    data = get_json(
        "/api/v1/mkt/candles/",
        params={
            "symbol": symbol,
            "from": start,
            "to": now,
            "res": resolution
        }
    )

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected candles response for {symbol}")

    candles = []
    for item in data:
        if not isinstance(item, dict):
            continue

        try:
            candle = {
                "open": float(item["open"]),
                "close": float(item["close"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "volume": float(item["volume"]),
                "ts": float(item["ts"]),
                "resolution": str(item.get("resolution", ""))
            }
        except (KeyError, TypeError, ValueError):
            continue

        if candle["close"] > 0 and candle["high"] > 0:
            candles.append(candle)

    candles.sort(key=lambda x: x["ts"])

    # Verify API actually returned the requested resolution.
    if any(c["resolution"] and c["resolution"] != resolution
           for c in candles):
        raise RuntimeError(
            f"API returned an unexpected timeframe for {symbol}/{resolution}"
        )

    if len(candles) < 60:
        raise RuntimeError(
            f"Not enough candles for {symbol}/{resolution}: {len(candles)}"
        )

    # Exclude the currently forming candle from indicator calculations.
    return candles[:-1]


def ema(values, period):
    if len(values) < period:
        return None

    seed = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    result = seed

    for value in values[period:]:
        result = value * alpha + result * (1.0 - alpha)

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        true_ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close)
        ))

    return sum(true_ranges[-period:]) / period


def analyze_timeframe(candles):
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    fast = ema(closes, 20)
    slow = ema(closes, 50)
    current_rsi = rsi(closes, 14)
    current_atr = atr(candles, 14)

    if None in (fast, slow, current_rsi, current_atr):
        raise RuntimeError("Indicator calculation failed")

    recent_volume = sum(volumes[-5:]) / 5
    previous_volume = sum(volumes[-25:-5]) / 20
    volume_ratio = (
        recent_volume / previous_volume
        if previous_volume > 0 else 0
    )

    recent = candles[-20:]
    support = min(c["low"] for c in recent)
    resistance = max(c["high"] for c in recent)
    price = closes[-1]

    return {
        "price": price,
        "ema20": fast,
        "ema50": slow,
        "rsi": current_rsi,
        "atr": current_atr,
        "volume_ratio": volume_ratio,
        "support": support,
        "resistance": resistance,
        "trend": (
            "LONG" if fast > slow and price > fast
            else "SHORT" if fast < slow and price < fast
            else "NEUTRAL"
        )
    }


def analyze_symbol(symbol, btc_trend):
    candles15 = load_candles(symbol, "15m")
    candles1h = load_candles(symbol, "1h")

    a15 = analyze_timeframe(candles15)
    a1h = analyze_timeframe(candles1h)

    if a15["trend"] == "NEUTRAL" or a1h["trend"] == "NEUTRAL":
        return None

    if a15["trend"] != a1h["trend"]:
        return None

    direction = a15["trend"]

    # Conservative RSI and volume filters.
    if direction == "LONG":
        if not (50 <= a15["rsi"] <= 68):
            return None
        if not (48 <= a1h["rsi"] <= 70):
            return None
        if btc_trend == "SHORT":
            return None
    else:
        if not (32 <= a15["rsi"] <= 50):
            return None
        if not (30 <= a1h["rsi"] <= 52):
            return None
        if btc_trend == "LONG":
            return None

    if a15["volume_ratio"] < 1.15:
        return None

    price = a15["price"]
    volatility = a15["atr"]

    if volatility <= 0 or price <= 0:
        return None

    # Avoid entries too close to the opposing level.
    if direction == "LONG":
        if a15["resistance"] > price:
            room = a15["resistance"] - price
            if room < 1.5 * volatility:
                return None
        stop = max(a15["support"], price - 1.5 * volatility)
        risk = price - stop
        if risk <= 0:
            return None
        target1 = price + 2.0 * risk
        target2 = price + 3.0 * risk
    else:
        if a15["support"] < price:
            room = price - a15["support"]
            if room < 1.5 * volatility:
                return None
        stop = min(a15["resistance"], price + 1.5 * volatility)
        risk = stop - price
        if risk <= 0:
            return None
        target1 = price - 2.0 * risk
        target2 = price - 3.0 * risk

    score = 75

    if a15["volume_ratio"] >= 1.5:
        score += 5

    if direction == a1h["trend"]:
        score += 5

    # BTC alignment is required to pass; alignment adds confidence.
    if btc_trend == direction:
        score += 5

    if score < MIN_SCORE:
        return None

    # Educational risk estimate only; no exchange contract sizing here.
    assumed_notional = MARGIN_USDT * LEVERAGE
    assumed_quantity = assumed_notional / price
    risk_percent = abs(price - stop) / price * 100

    return {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "stop": stop,
        "target1": target1,
        "target2": target2,
        "score": score,
        "rsi15": a15["rsi"],
        "rsi1h": a1h["rsi"],
        "volume_ratio": a15["volume_ratio"],
        "support": a15["support"],
        "resistance": a15["resistance"],
        "btc_trend": btc_trend,
        "assumed_notional": assumed_notional,
        "assumed_quantity": assumed_quantity,
        "risk_percent": risk_percent
    }


def get_btc_trend():
    # BTC candles are used only as a market-direction filter.
    candidates = ("BTC_USDT", "BTC_USDT_PERPETUAL")

    for symbol in candidates:
        try:
            candles = load_candles(symbol, "1h")
            result = analyze_timeframe(candles)
            return result["trend"]
        except Exception as exc:
            logging.info("BTC reference unavailable for %s: %s", symbol, exc)

    return "UNKNOWN"


def format_signal(sig):
    direction_label = "🟢 LONG" if sig["direction"] == "LONG" else "🔴 SHORT"

    return "\n".join([
        f"📌 {sig['symbol']} — {direction_label}",
        f"⭐ امتیاز محافظه‌کارانه: {sig['score']}/100",
        f"💵 ورود مرجع: {sig['price']:.8g}",
        f"🛑 حد ضرر: {sig['stop']:.8g}",
        f"🎯 هدف ۱: {sig['target1']:.8g}",
        f"🎯 هدف ۲: {sig['target2']:.8g}",
        f"📉 فاصله حد ضرر: {sig['risk_percent']:.2f}%",
        f"📊 RSI 15m / 1h: {sig['rsi15']:.1f} / {sig['rsi1h']:.1f}",
        f"📦 نسبت حجم: {sig['volume_ratio']:.2f}x",
        f"🧱 حمایت: {sig['support']:.8g}",
        f"🧱 مقاومت: {sig['resistance']:.8g}",
        f"₿ روند BTC: {sig['btc_trend']}",
        f"🧪 ارزش اسمی فرضی: {sig['assumed_notional']:.2f} USDT",
        "━━━━━━━━━━━━━━━━━━"
    ])


def main():
    logging.info("Starting ETH WHALE paper futures scanner")

    markets = load_markets()
    futures_markets = [
        m for m in markets
        if isinstance(m, dict)
        and explicitly_futures(m)
        and market_symbol(m)
        and (
            market_symbol(m).endswith("_USDT")
            or "USDT" in market_symbol(m)
        )
    ]

    if not futures_markets:
        message = (
            "🐋 ETH WHALE\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚠️ سیگنال فیوچرز صادر نشد.\n"
            "فهرست عمومی بازارها، قراردادهای فیوچرز را به‌طور قابل‌تأیید مشخص نکرد.\n"
            "برای جلوگیری از اشتباه، بازار اسپات به‌عنوان فیوچرز استفاده نشد.\n"
            "لطفاً مستندات رسمی فهرست قراردادهای فیوچرز را بررسی کنیم.\n"
            "🧪 سفارش واقعی: خاموش"
        )
        print(message)
        telegram_send(message)
        return

    btc_trend = get_btc_trend()

    if btc_trend == "UNKNOWN":
        message = (
            "🐋 ETH WHALE\n"
            "⚠️ فیلتر روند BTC در دسترس نیست؛ اسکن محافظه‌کارانه متوقف شد.\n"
            "🧪 سفارش واقعی: خاموش"
        )
        print(message)
        telegram_send(message)
        return

    signals = []
    errors = []

    for market in futures_markets:
        symbol = market_symbol(market)
        try:
            signal = analyze_symbol(symbol, btc_trend)
            if signal:
                signals.append(signal)
        except Exception as exc:
            errors.append(f"{symbol}: {str(exc)[:120]}")
            logging.warning("Skipping %s: %s", symbol, exc)

    signals.sort(key=lambda x: x["score"], reverse=True)
    signals = signals[:MAX_SIGNALS]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "🐋 ETH WHALE",
        "━━━━━━━━━━━━━━━━━━",
        "📊 BITPIN FUTURES SIGNAL SCANNER",
        "🧪 PAPER ONLY — NO REAL ORDERS",
        f"🕒 {now}",
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT",
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x",
        f"💵 مارجین فرضی هر موقعیت: {MARGIN_USDT:.2f} USDT",
        f"📦 ارزش اسمی فرضی: {MARGIN_USDT * LEVERAGE:.2f} USDT",
        f"₿ روند مرجع BTC: {btc_trend}",
        f"🔎 قراردادهای شناسایی‌شده از متادیتا: {len(futures_markets)}",
        "━━━━━━━━━━━━━━━━━━"
    ]

    if signals:
        for sig in signals:
            lines.append(format_signal(sig))
    else:
        lines.append("⏸ با فیلترهای محافظه‌کارانه سیگنال تأییدشده‌ای پیدا نشد.")

    lines.extend([
        "⚠️ Funding Rate و Open Interest استفاده نشده‌اند؛ مسیر رسمی آن‌ها هنوز تأیید نشده است.",
        "⚠️ این کد اندازه قرارداد و حداقل مقدار سفارش فیوچرز را از صرافی تأیید نمی‌کند.",
        "🚫 هیچ سفارش واقعی ثبت نمی‌شود."
    ])

    report = "\n".join(lines)
    print(report)
    telegram_send(report)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("Fatal scanner error")
        message = (
            "🐋 ETH WHALE\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ اسکن کامل نشد.\n"
            f"علت: {type(exc).__name__}: {str(exc)[:500]}\n"
            "🧪 سفارش واقعی ثبت نشده است."
        )
        print(message)
        try:
            telegram_send(message)
        except Exception:
            logging.exception("Telegram error notification failed")
        raise
