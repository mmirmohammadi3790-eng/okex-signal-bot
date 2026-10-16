
import os
import time
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# 🐋 ETH WHALE V3
# Market trend + one best LONG/SHORT candidate
# Kraken public market data | PAPER ANALYSIS ONLY
# NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
TIMEOUT = 20
MIN_SCORE = 75
STRONG_SCORE = 85

# Kraken market pairs; all prices are quoted in USD.
MARKETS = {
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "XRP": "XRPUSD",
    "DOGE": "DOGEUSD",
    "LINK": "LINKUSD",
    "ADA": "ADAUSD",
    "AVAX": "AVAXUSD",
    "LTC": "LTCUSD",
    "BCH": "BCHUSD",
}

INTERVALS = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

S = requests.Session()
S.headers.update({"User-Agent": "ETH-WHALE-Market-Report/3.0"})


def get_candles(pair, interval):
    response = S.get(
        KRAKEN_URL,
        params={"pair": pair, "interval": interval},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    api_errors = payload.get("error", [])
    if api_errors:
        raise RuntimeError("; ".join(api_errors))

    result = payload.get("result", {})
    pair_keys = [key for key in result if key != "last"]

    if not pair_keys:
        raise RuntimeError("Kraken returned no candle series")

    rows = result[pair_keys[0]]

    # Kraken's final row is the currently forming candle.
    # Exclude it so incomplete candles don't create false signals.
    if len(rows) > 1:
        rows = rows[:-1]

    candles = []

    for row in rows:
        candles.append({
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "vwap": float(row[5]),
            "volume": float(row[6]),
            "count": int(row[7]),
        })

    if len(candles) < 55:
        raise RuntimeError(
            f"Not enough closed candles: {len(candles)}"
        )

    return candles


def ema(values, period):
    alpha = 2.0 / (period + 1.0)
    result = values[0]

    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0

    changes = [
        values[i] - values[i - 1]
        for i in range(len(values) - period, len(values))
    ]

    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr(candles, period=14):
    ranges = []

    for i in range(1, len(candles)):
        c = candles[i]
        p = candles[i - 1]

        ranges.append(max(
            c["high"] - c["low"],
            abs(c["high"] - p["close"]),
            abs(c["low"] - p["close"]),
        ))

    if len(ranges) < period:
        return 0.0

    return sum(ranges[-period:]) / period


def analyze(candles):
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    price = closes[-1]
    e20 = ema(closes[-100:], 20)
    e50 = ema(closes[-100:], 50)
    r = rsi(closes)
    a = atr(candles)

    recent_volume = sum(volumes[-5:]) / 5
    previous_volume = sum(volumes[-20:-5]) / 15

    volume_ratio = (
        recent_volume / previous_volume
        if previous_volume > 0 else 0.0
    )

    if price > e20 > e50:
        direction = "LONG"
    elif price < e20 < e50:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    last = candles[-1]
    if last["close"] > last["open"]:
        candle_direction = "LONG"
    elif last["close"] < last["open"]:
        candle_direction = "SHORT"
    else:
        candle_direction = "NEUTRAL"

    return {
        "candles": candles,
        "price": price,
        "ema20": e20,
        "ema50": e50,
        "rsi": r,
        "atr": a,
        "volume_ratio": volume_ratio,
        "direction": direction,
        "candle_direction": candle_direction,
        "change": (
            (closes[-1] / closes[-2] - 1) * 100
            if closes[-2] else 0
        ),
    }


def levels(candles, price):
    """Identify recent swing lows and highs from closed candles."""
    lows = []
    highs = []

    start = max(2, len(candles) - 120)
    end = len(candles) - 2

    for i in range(start, end):
        c = candles[i]
        neighbors = candles[i - 2:i] + candles[i + 1:i + 3]

        if len(neighbors) != 4:
            continue

        if all(c["low"] < n["low"] for n in neighbors):
            if c["low"] < price:
                lows.append(c["low"])

        if all(c["high"] > n["high"] for n in neighbors):
            if c["high"] > price:
                highs.append(c["high"])

    tolerance = price * 0.001

    def deduplicate(items):
        result = []
        for x in sorted(items):
            if not result or abs(x - result[-1]) > tolerance:
                result.append(x)
        return result

    supports = sorted(
        deduplicate([x for x in lows if x < price]),
        reverse=True,
    )[:3]

    resistances = sorted(
        deduplicate([x for x in highs if x > price])
    )[:3]

    return supports, resistances


def score_signal(m15, h1, h4, supports, resistances):
    direction = h4["direction"]

    # Require agreement between 1h and 4h.
    if direction not in ("LONG", "SHORT"):
        return None

    if h1["direction"] != direction:
        return None

    score = 25  # 1h + 4h trend agreement

    # EMA confirmation: 20 points total.
    score += 10
    score += 10

    # RSI / momentum: maximum 15 points.
    r = h1["rsi"]

    if direction == "LONG":
        if 52 <= r <= 67:
            score += 15
        elif 50 <= r < 52 or 67 < r <= 72:
            score += 10
        elif 45 <= r < 50:
            score += 5
    else:
        if 33 <= r <= 48:
            score += 15
        elif 28 <= r < 33 or 48 < r <= 50:
            score += 10
        elif 50 < r <= 55:
            score += 5

    # Volume confirmation: maximum 15.
    vr = h1["volume_ratio"]
    if vr >= 1.5:
        score += 15
    elif vr >= 1.15:
        score += 12
    elif vr >= 0.8:
        score += 8
    else:
        score += 3

    # Avoid entering too close to an obstacle: maximum 15.
    price = h1["price"]
    volatility = h1["atr"]

    if volatility <= 0:
        return None

    if direction == "LONG":
        above = [x for x in resistances if x > price]
        distance = (
            (min(above) - price) / volatility
            if above else 3.0
        )
    else:
        below = [x for x in supports if x < price]
        distance = (
            (price - max(below)) / volatility
            if below else 3.0
        )

    if distance >= 1.5:
        score += 15
    elif distance >= 1.0:
        score += 10
    elif distance >= 0.65:
        score += 5

    # 15m candle confirmation: maximum 10.
    if m15["candle_direction"] == direction:
        score += 10
    elif m15["candle_direction"] == "NEUTRAL":
        score += 4

    return min(score, 100)


def trade_levels(direction, price, volatility, supports, resistances):
    if volatility <= 0:
        return None

    if direction == "LONG":
        stop = price - 1.5 * volatility
        nearby = [x for x in supports if x < price]

        if nearby:
            candidate = max(nearby) - 0.2 * volatility
            if stop < candidate < price:
                stop = candidate

        risk = price - stop
        if risk <= 0:
            return None

        targets = [
            price + risk,
            price + risk * 1.5,
            price + risk * 2,
        ]

    else:
        stop = price + 1.5 * volatility
        nearby = [x for x in resistances if x > price]

        if nearby:
            candidate = min(nearby) + 0.2 * volatility
            if price < candidate < stop:
                stop = candidate

        risk = stop - price
        if risk <= 0:
            return None

        targets = [
            price - risk,
            price - risk * 1.5,
            price - risk * 2,
        ]

    return {
        "entry": price,
        "stop": stop,
        "targets": targets,
    }


def fmt(value):
    if value is None:
        return "نامشخص"
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:.4f}"
    if value >= 0.01:
        return f"${value:.5f}"
    return f"${value:.8f}"


def trend_label(items, timeframe):
    directions = [
        x[timeframe]["direction"]
        for x in items if timeframe in x
    ]

    if not directions:
        return "نامشخص"

    total = len(directions)
    bullish = directions.count("LONG")
    bearish = directions.count("SHORT")

    if bullish / total >= 0.6:
        return "🟢 صعودی"
    if bearish / total >= 0.6:
        return "🔴 نزولی"

    return "🟡 خنثی / ترکیبی"


def format_levels(title, values):
    if not values:
        return f"{title}: سطح معتبر کافی پیدا نشد"

    return "\n".join(
        f"{title}{i}: {fmt(value)}"
        for i, value in enumerate(values, 1)
    )


def make_report(analyses, errors):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not analyses:
        return (
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 گزارش روند بازار\n"
            "⚠️ هیچ بازار معتبری تحلیل نشد.\n"
            f"خطاها: {len(errors)}\n"
            "لطفاً خطاهای Kraken را بررسی کن.\n"
            f"زمان: {now}\n"
            "🚫 بدون سفارش واقعی."
        )

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش روند کلی بازار",
        "━━━━━━━━━━━━━━━━━━",
        f"⏱ ۱ ساعته: {trend_label(analyses, 'h1')}",
        f"🕓 ۴ ساعته: {trend_label(analyses, 'h4')}",
        f"📅 روزانه: {trend_label(analyses, 'd1')}",
    ]

    btc = next((x for x in analyses if x["symbol"] == "BTC"), None)
    alts = [x for x in analyses if x["symbol"] != "BTC"]

    if btc:
        b = btc["h4"]
        lines.extend([
            "",
            "₿ وضعیت بیت‌کوین",
            f"روند ۴ ساعته: {b['direction']}",
            f"RSI: {b['rsi']:.1f}",
            f"تغییر آخرین کندل بسته‌شده: {b['change']:+.2f}%",
        ])

    lines.append(f"₿ آلت‌کوین‌ها: {trend_label(alts, 'h4')}")

    candidates = [
        x for x in analyses
        if x["score"] is not None and x["score"] >= MIN_SCORE
    ]
    candidates.sort(key=lambda x: x["score"], reverse=True)

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🎯 بهترین فرصت بازار",
        "━━━━━━━━━━━━━━━━━━",
    ])

    if not candidates:
        lines.extend([
            "⚪ WAIT — ارز واجد شرایط پیدا نشد",
            f"حداقل امتیاز لازم: {MIN_SCORE}/100",
        ])
    else:
        best = candidates[0]
        direction = best["h4"]["direction"]
        price = best["h1"]["price"]

        levels_trade = trade_levels(
            direction, price, best["h1"]["atr"],
            best["supports"], best["resistances"]
        )

        if levels_trade is None:
            lines.append("⚪ WAIT — محاسبه ریسک معتبر نبود")
        else:
            score = best["score"]
            strength = "قوی" if score >= STRONG_SCORE else "قابل بررسی"

            lines.extend([
                f"🪙 ارز: {best['symbol']}/USD",
                f"📌 جهت: {'🟢 LONG' if direction == 'LONG' else '🔴 SHORT'}",
                f"💪 قدرت سیگنال: {score}/100 — {strength}",
                f"💵 ورود فرضی: {fmt(levels_trade['entry'])}",
                f"🛑 حد ضرر: {fmt(levels_trade['stop'])}",
                f"🎯 TP1: {fmt(levels_trade['targets'][0])}",
                f"🎯 TP2: {fmt(levels_trade['targets'][1])}",
                f"🎯 TP3: {fmt(levels_trade['targets'][2])}",
                f"📊 RSI یک‌ساعته: {best['h1']['rsi']:.1f}",
                f"📦 نسبت حجم: {best['h1']['volume_ratio']:.2f}x",
                "",
                "🟢 حمایت‌های مهم:",
                format_levels("S", best["supports"]),
                "",
                "🔴 مقاومت‌های مهم:",
                format_levels("R", best["resistances"]),
            ])

            support = next(
                (x for x in best["supports"] if x < price), None
            )
            resistance = next(
                (x for x in best["resistances"] if x > price), None
            )

            lines.extend([
                "",
                "📏 فاصله تا سطوح:",
                (
                    f"حمایت: {(price - support) / price * 100:.2f}%"
                    if support else "حمایت: نامشخص"
                ),
                (
                    f"مقاومت: {(resistance - price) / price * 100:.2f}%"
                    if resistance else "مقاومت: نامشخص"
                ),
            ])

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"📊 بازارهای تحلیل‌شده: {len(analyses)}",
        f"⚠️ خطاهای داده: {len(errors)}",
        f"🕒 زمان: {now}",
        "━━━━━━━━━━━━━━━━━━",
        "ℹ️ داده قیمت از Kraken؛ تحلیل تکنیکال خودکار",
        "⚠️ این ربات سیگنال اختصاصی تحلیلگران را دریافت نمی‌کند.",
        "🚫 فقط تحلیل آزمایشی؛ هیچ سفارش واقعی ثبت نمی‌شود.",
    ])

    return "\n".join(lines)


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
        )

    response = S.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()

    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected the message")


def main():
    logging.info("Starting %s — Kraken data source", BOT_NAME)

    analyses = []
    errors = []

    for symbol, pair in MARKETS.items():
        try:
            data = {
                "symbol": symbol,
                "m15": analyze(get_candles(pair, INTERVALS["15m"])),
                "h1": analyze(get_candles(pair, INTERVALS["1h"])),
                "h4": analyze(get_candles(pair, INTERVALS["4h"])),
                "d1": analyze(get_candles(pair, INTERVALS["1d"])),
            }

            data["supports"], data["resistances"] = levels(
                data["h4"]["candles"],
                data["h1"]["price"],
            )

            data["score"] = score_signal(
                data["m15"],
                data["h1"],
                data["h4"],
                data["supports"],
                data["resistances"],
            )

            analyses.append(data)

            logging.info(
                "%s analyzed; score=%s",
                symbol,
                data["score"],
            )

        except Exception as exc:
            errors.append(f"{symbol}: {str(exc)[:180]}")
            logging.warning("%s failed: %s", symbol, exc)

        # Be considerate of the public API.
        time.sleep(0.5)

    report = make_report(analyses, errors)
    print(report)
    send_telegram(report)

    logging.info(
        "Report sent. Markets=%d Errors=%d",
        len(analyses), len(errors)
    )


if __name__ == "__main__":
    main()
# ==========================================
# SMART ENTRY FILTER — ETH WHALE
# ==========================================

MIN_LEVEL_DISTANCE_PCT = 0.30
REQUIRE_CLOSED_CANDLE = True
MAX_SIGNAL_COUNT = 1


def distance_pct(price, level):
    """فاصله درصدی قیمت تا حمایت یا مقاومت"""
    if not price or not level:
        return 999.0
    return abs(price - level) / price * 100.0


def check_entry_filter(
    direction,
    price,
    support,
    resistance,
    candle_closed=True,
):
    """
    فقط فیلتر فاصله از سطوح و بسته‌شدن کندل را بررسی می‌کند.
    این تابع به‌تنهایی تأیید شکست حمایت یا مقاومت نیست.
    """

    if not candle_closed:
        return False, "انتظار برای بسته‌شدن کندل"

    if direction == "SHORT" and support:
        dist = distance_pct(price, support)

        if price > support and dist < MIN_LEVEL_DISTANCE_PCT:
            return (
                False,
                f"فاصله تا حمایت فقط {dist:.2f}% است؛ "
                "منتظر شکست معتبر حمایت بمان",
            )

    elif direction == "LONG" and resistance:
        dist = distance_pct(price, resistance)

        if price < resistance and dist < MIN_LEVEL_DISTANCE_PCT:
            return (
                False,
                f"فاصله تا مقاومت فقط {dist:.2f}% است؛ "
                "منتظر شکست معتبر مقاومت بمان",
            )

    return True, "فیلتر فاصله تأیید شد"
