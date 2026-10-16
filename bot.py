
import os
import time
import math
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# 🐋 ETH WHALE — BALANCED TREND WATCH + TP1/TP2/TP3
# PAPER ANALYSIS ONLY — NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
BINANCE_BASE = "https://data-api.binance.vision"
BYBIT_BASE = "https://api.bybit.com"

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or ""
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or ""

MAX_MARKETS = 25
CANDLE_LIMIT = 100
REQUEST_TIMEOUT = 15
PAUSE_BETWEEN_MARKETS = 0.15

EXCLUDED_BASES = {
    "USDC", "USDP", "FDUSD", "TUSD", "BUSD",
    "DAI", "USDE", "USDD", "UST", "USTC",
    "EUR", "EURC", "PAXG"
}

LEVERAGED_ENDINGS = (
    "UP", "DOWN", "BULL", "BEAR", "2L", "2S",
    "3L", "3S", "5L", "5S"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Balanced-Paper-Analyzer/2.0"
})


# -------------------- HTTP --------------------

def get_json(url, params=None):
    response = SESSION.get(
        url, params=params, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID secrets."
        )

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    response = SESSION.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram API returned ok=false.")


# -------------------- INDICATORS --------------------

def ema(values, period):
    if len(values) < period:
        return None

    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period

    for item in values[period:]:
        value = alpha * item + (1.0 - alpha) * value

    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        trs.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close)
        ))

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period

    return value


# -------------------- MARKET DATA --------------------

def get_binance_markets():
    tickers = get_json(
        BINANCE_BASE + "/api/v3/ticker/24hr"
    )
    info = get_json(
        BINANCE_BASE + "/api/v3/exchangeInfo"
    )

    allowed = set()

    for item in info.get("symbols", []):
        if (
            item.get("status") != "TRADING"
            or item.get("quoteAsset") != "USDT"
            or not item.get("isSpotTradingAllowed", True)
        ):
            continue

        symbol = item.get("symbol", "")
        base = item.get("baseAsset", "")

        if base in EXCLUDED_BASES:
            continue

        if base.endswith(LEVERAGED_ENDINGS):
            continue

        allowed.add(symbol)

    markets = []

    for item in tickers:
        symbol = item.get("symbol", "")

        if symbol not in allowed:
            continue

        try:
            price = float(item.get("lastPrice", 0))
            volume = float(item.get("quoteVolume", 0))

            if price > 0 and volume > 0:
                markets.append({
                    "symbol": symbol,
                    "price": price,
                    "volume": volume
                })
        except (TypeError, ValueError):
            continue

    markets.sort(key=lambda x: x["volume"], reverse=True)
    return markets[:MAX_MARKETS]


def get_binance_candles(symbol, interval):
    raw = get_json(
        BINANCE_BASE + "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": CANDLE_LIMIT
        }
    )

    candles = []

    for item in raw:
        candles.append({
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5])
        })

    # Remove the latest candle because it may still be open.
    return candles[:-1]


def get_bybit_markets():
    data = get_json(
        BYBIT_BASE + "/v5/market/tickers",
        {"category": "linear"}
    )

    markets = []

    for item in data.get("result", {}).get("list", []):
        symbol = item.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        base = symbol[:-4]

        if base in EXCLUDED_BASES:
            continue

        if base.endswith(LEVERAGED_ENDINGS):
            continue

        try:
            price = float(item.get("lastPrice", 0))
            volume = float(item.get("turnover24h", 0))

            if price > 0 and volume > 0:
                markets.append({
                    "symbol": symbol,
                    "price": price,
                    "volume": volume
                })
        except (TypeError, ValueError):
            continue

    markets.sort(key=lambda x: x["volume"], reverse=True)
    return markets[:MAX_MARKETS]


def get_bybit_candles(symbol, interval):
    data = get_json(
        BYBIT_BASE + "/v5/market/kline",
        {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": CANDLE_LIMIT
        }
    )

    raw = data.get("result", {}).get("list", [])
    raw = list(reversed(raw))
    candles = []

    for item in raw:
        candles.append({
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5])
        })

    return candles[:-1]


def load_markets():
    try:
        markets = get_binance_markets()

        if markets:
            return "Binance Spot", markets, get_binance_candles

    except Exception as exc:
        logging.warning("Binance unavailable: %s", exc)

    markets = get_bybit_markets()

    if markets:
        return "Bybit Linear", markets, get_bybit_candles

    raise RuntimeError("Unable to load markets from Binance or Bybit.")


# -------------------- SUPPORT / RESISTANCE --------------------

def find_levels(candles, price):
    recent = candles[-40:]

    below = [c["low"] for c in recent if c["low"] < price]
    above = [c["high"] for c in recent if c["high"] > price]

    support = max(below) if below else min(c["low"] for c in recent)
    resistance = min(above) if above else max(c["high"] for c in recent)

    if support >= price:
        support = min(c["low"] for c in recent)

    if resistance <= price:
        resistance = max(c["high"] for c in recent)

    return support, resistance


def price_text(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    if value >= 0.01:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


# -------------------- BALANCED ANALYSIS --------------------

def analyze_market(market, candle_fetcher):
    symbol = market["symbol"]

    candles15 = candle_fetcher(symbol, "15m")
    candles1h = candle_fetcher(symbol, "1h")

    if len(candles15) < 55 or len(candles1h) < 55:
        return None, "کمبود کندل"

    closes15 = [c["close"] for c in candles15]
    closes1h = [c["close"] for c in candles1h]
    price = closes15[-1]

    e20_15 = ema(closes15, 20)
    e50_15 = ema(closes15, 50)
    e20_1h = ema(closes1h, 20)
    e50_1h = ema(closes1h, 50)
    r15 = rsi(closes15)
    r1h = rsi(closes1h)
    a15 = atr(candles15)

    values = [e20_15, e50_15, e20_1h, e50_1h, r15, r1h, a15]
    if any(x is None for x in values) or price <= 0:
        return None, "اندیکاتور ناقص"

    support, resistance = find_levels(candles15, price)

    if support >= price or resistance <= price:
        return None, "سطوح نامعتبر"

    support_pct = (price - support) / price * 100
    resistance_pct = (resistance - price) / price * 100

    gap15 = abs(e20_15 - e50_15) / price * 100
    gap1h = abs(e20_1h - e50_1h) / price * 100

    # Flexible RSI filters: still require both timeframes to agree.
    bullish = (
        e20_15 > e50_15
        and e20_1h > e50_1h
        and price > e20_15
        and 43 <= r15 <= 70
        and 38 <= r1h <= 72
    )

    bearish = (
        e20_15 < e50_15
        and e20_1h < e50_1h
        and price < e20_15
        and 30 <= r15 <= 57
        and 28 <= r1h <= 62
    )

    if not bullish and not bearish:
        return None, "عدم تأیید روند دو تایم‌فریمی"

    direction = "LONG" if bullish else "SHORT"
    room_pct = resistance_pct if bullish else support_pct

    # Softer filters than the previous version.
    if gap15 < 0.01 or gap1h < 0.01:
        return None, "قدرت EMA کم"

    if room_pct < 0.30:
        return None, "فاصله کم تا مانع قیمتی"

    # TP1/TP2 are staged before the nearest obstacle.
    # TP3 is the nearest estimated support/resistance.
    if direction == "LONG":
        tp1 = price + (resistance - price) * 0.30
        tp2 = price + (resistance - price) * 0.65
        tp3 = resistance
        rsi_quality = 1.0 - abs(r15 - 55) / 30
    else:
        tp1 = price - (price - support) * 0.30
        tp2 = price - (price - support) * 0.65
        tp3 = support
        rsi_quality = 1.0 - abs(r15 - 45) / 30

    rsi_quality = max(0.0, min(1.0, rsi_quality))

    # Normalize 24h volume so one huge market does not dominate.
    volume_score = min(
        1.0,
        max(0.0, math.log10(max(market["volume"], 1)) / 10)
    )

    trend_score = min(20.0, gap15 * 8) + min(20.0, gap1h * 8)
    room_score = min(20.0, room_pct * 4)
    score = trend_score + room_score + rsi_quality * 20 + volume_score * 20
    score = max(0.0, min(100.0, score))

    return {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "volume": market["volume"],
        "rsi15": r15,
        "rsi1h": r1h,
        "ema20_15": e20_15,
        "ema50_15": e50_15,
        "ema20_1h": e20_1h,
        "ema50_1h": e50_1h,
        "support": support,
        "resistance": resistance,
        "support_pct": support_pct,
        "resistance_pct": resistance_pct,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "room_pct": room_pct,
        "score": score
    }, None


# -------------------- REPORT --------------------

def build_report(best, source, checked, failures, reasons):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if best is None:
        reason_text = "\n".join(
            f"• {name}: {count}"
            for name, count in sorted(
                reasons.items(),
                key=lambda item: item[1],
                reverse=True
            )[:3]
        ) or "• گزینه واجد شرایط پیدا نشد"

        return (
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 <b>گزارش روند بازار</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚪ <b>WAIT — گزینه مناسب پیدا نشد</b>\n\n"
            f"🔎 بازارهای بررسی‌شده: {checked}\n"
            f"⚠️ خطاهای تحلیل: {failures}\n"
            f"📌 دلایل اصلی رد بازارها:\n{reason_text}\n\n"
            f"منبع: {source}\n"
            f"زمان: {now}\n\n"
            "🧪 تحلیل آزمایشی؛ هیچ سفارش واقعی ثبت نشده است."
        )

    direction_text = (
        "صعودی / LONG"
        if best["direction"] == "LONG"
        else "نزولی / SHORT"
    )

    return (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 <b>بهترین گزینه این اسکن</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🪙 نماد: <b>{best['symbol']}</b>\n"
        f"📈 جهت روند: <b>{direction_text}</b>\n"
        f"💵 قیمت مبنا: <code>{price_text(best['price'])}</code>\n"
        f"⭐ امتیاز تحلیلی: <b>{best['score']:.1f}/100</b>\n\n"
        "📊 <b>اندیکاتورها</b>\n"
        f"RSI 15m: <code>{best['rsi15']:.1f}</code>\n"
        f"RSI 1h: <code>{best['rsi1h']:.1f}</code>\n"
        f"EMA20 15m: <code>{price_text(best['ema20_15'])}</code>\n"
        f"EMA50 15m: <code>{price_text(best['ema50_15'])}</code>\n"
        f"EMA20 1h: <code>{price_text(best['ema20_1h'])}</code>\n"
        f"EMA50 1h: <code>{price_text(best['ema50_1h'])}</code>\n\n"
        "🧱 <b>حمایت و مقاومت تخمینی</b>\n"
        f"حمایت: <code>{price_text(best['support'])}</code>\n"
        f"فاصله تا حمایت: {best['support_pct']:.2f}%\n"
        f"مقاومت: <code>{price_text(best['resistance'])}</code>\n"
        f"فاصله تا مقاومت: {best['resistance_pct']:.2f}%\n\n"
        "🎯 <b>اهداف فرضی</b>\n"
        f"TP1: <code>{price_text(best['tp1'])}</code>\n"
        f"TP2: <code>{price_text(best['tp2'])}</code>\n"
        f"TP3: <code>{price_text(best['tp3'])}</code>\n\n"
        "ℹ️ TP1 و TP2 قبل از مانع نزدیک قرار گرفته‌اند؛ TP3 همان سطح تخمینی حمایت/مقاومت است.\n"
        "این اهداف تضمین‌شده نیستند و حد ضرر محاسبه نشده است.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"منبع: {source}\n"
        f"بازارهای بررسی‌شده: {checked} | خطاها: {failures}\n"
        f"زمان: {now}\n\n"
        "🧪 <b>PAPER ANALYSIS ONLY</b>\n"
        "🚫 سفارش واقعی: خاموش"
    )


# -------------------- MAIN --------------------

def main():
    source, markets, candle_fetcher = load_markets()

    candidates = []
    failures = 0
    reasons = {}

    for market in markets:
        try:
            result, reason = analyze_market(market, candle_fetcher)

            if result is not None:
                candidates.append(result)
            elif reason:
                reasons[reason] = reasons.get(reason, 0) + 1

        except Exception as exc:
            failures += 1
            logging.warning(
                "Failed %s: %s",
                market.get("symbol", "UNKNOWN"),
                exc
            )

        time.sleep(PAUSE_BETWEEN_MARKETS)

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    # One best candidate, or WAIT when no market qualifies.
    best = candidates[0] if candidates else None

    message = build_report(
        best,
        source,
        len(markets),
        failures,
        reasons
    )

    send_telegram(message)

    logging.info(
        "Finished: source=%s checked=%s candidates=%s failures=%s",
        source, len(markets), len(candidates), failures
    )


if __name__ == "__main__":
    main()
