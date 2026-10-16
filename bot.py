
import os
import time
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# 🐋 ETH WHALE — MARKET TREND + ONE BEST SIGNAL
# PAPER ANALYSIS ONLY — NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# سرمایه آزمایشی؛ فقط برای محاسبات نمایشی
CAPITAL_USDT = 48.0
LEVERAGE = 3
MARGIN_PER_TRADE = 16.0
POSITION_VALUE = MARGIN_PER_TRADE * LEVERAGE

MIN_SCORE = 75
STRONG_SCORE = 85
TIMEOUT = 12

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "SUIUSDT",
    "ADAUSDT",
    "AVAXUSDT",
]

BASE_URLS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Market-Report/2.0"
})


def get_candles(symbol, interval, limit=120):
    errors = []

    for base_url in BASE_URLS:
        try:
            response = SESSION.get(
                base_url + "/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                },
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list) and len(data) >= 55:
                return data

            errors.append(base_url + ": insufficient candles")

        except Exception as exc:
            errors.append(
                base_url + ": " + str(exc).replace("\n", " ")[:120]
            )

    raise RuntimeError(" | ".join(errors))


def ema(values, period):
    if not values:
        return 0.0

    alpha = 2.0 / (period + 1.0)
    result = values[0]

    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result

    return result


def calculate_rsi(closes, period=14):
    if len(closes) <= period:
        return 50.0

    changes = [
        closes[i] - closes[i - 1]
        for i in range(len(closes) - period, len(closes))
    ]

    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def candle_data(raw):
    return {
        "open_time": int(c[0]),
        "open": float(c[1]),
        "high": float(c[2]),
        "low": float(c[3]),
        "close": float(c[4]),
        "volume": float(c[5]),
        "close_time": int(c[6]),
    }


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )
        ranges.append(true_range)

    recent = ranges[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def analyze_candles(raw):
    candles = [candle_data(c) for c in raw]
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    price = closes[-1]
    ema20 = ema(closes[-100:], 20)
    ema50 = ema(closes[-100:], 50)
    rsi = calculate_rsi(closes)
    atr = calculate_atr(candles)

    recent_volume = sum(volumes[-5:]) / 5
    older_volume = sum(volumes[-20:-5]) / 15

    volume_ratio = (
        recent_volume / older_volume
        if older_volume > 0 else 0.0
    )

    if price > ema20 > ema50:
        direction = "LONG"
    elif price < ema20 < ema50:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    previous_close = closes[-2]
    change_pct = (
        (price / previous_close - 1.0) * 100.0
        if previous_close else 0.0
    )

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
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "volume_ratio": volume_ratio,
        "direction": direction,
        "change_pct": change_pct,
        "candle_direction": candle_direction,
    }


def find_support_resistance(candles, price, atr):
    """
    Find recent swing lows and highs.
    S1-S3 are nearest confirmed local lows below price.
    R1-R3 are nearest confirmed local highs above price.
    """

    lows = []
    highs = []

    # Ignore the newest two candles because their swing
    # status is not yet confirmed.
    start = max(2, len(candles) - 90)
    end = len(candles) - 2

    for i in range(start, end):
        current = candles[i]
        previous = candles[i - 2:i]
        following = candles[i + 1:i + 3]

        if len(previous) < 2 or len(following) < 2:
            continue

        if all(current["low"] < x["low"] for x in previous + following):
            if current["low"] < price:
                lows.append(current["low"])

        if all(current["high"] > x["high"] for x in previous + following):
            if current["high"] > price:
                highs.append(current["high"])

    # Use recent actual candle extremes if too few swing
    # points exist; these remain observed prices, not guesses.
    if len(lows) < 3:
        lows.extend(
            c["low"] for c in candles[-40:]
            if c["low"] < price
        )

    if len(highs) < 3:
        highs.extend(
            c["high"] for c in candles[-40:]
            if c["high"] > price
        )

    tolerance = max(atr * 0.15, price * 0.0002)

    def unique_levels(levels):
        output = []

        for level in sorted(levels):
            if not output or abs(level - output[-1]) > tolerance:
                output.append(level)

        return output

    supports = sorted(
        unique_levels([x for x in lows if x < price]),
        reverse=True,
    )[:3]

    resistances = sorted(
        unique_levels([x for x in highs if x > price])
    )[:3]

    return supports, resistances


def score_candidate(h1, h4, m15, supports, resistances):
    """
    Score out of 100:
    trend alignment 25
    EMA alignment 20
    RSI/momentum 15
    volume 15
    support/resistance clearance 15
    candle confirmation 10
    """

    direction = h4["direction"]

    if direction not in ("LONG", "SHORT"):
        return None

    # Both 1h and 4h must agree.
    if h1["direction"] != direction:
        return None

    score = 25

    # EMA alignment across both timeframes.
    score += 10 if h1["direction"] == direction else 0
    score += 10 if h4["direction"] == direction else 0

    # RSI should support direction without being extreme.
    rsi = h1["rsi"]

    if direction == "LONG":
        if 52 <= rsi <= 67:
            score += 15
        elif 50 <= rsi < 52 or 67 < rsi <= 72:
            score += 10
        elif 45 <= rsi < 50:
            score += 5
    else:
        if 33 <= rsi <= 48:
            score += 15
        elif 28 <= rsi < 33 or 48 < rsi <= 50:
            score += 10
        elif 50 < rsi <= 55:
            score += 5

    # Volume confirms activity, not direction by itself.
    ratio = h1["volume_ratio"]

    if ratio >= 1.5:
        score += 15
    elif ratio >= 1.15:
        score += 12
    elif ratio >= 0.8:
        score += 8
    else:
        score += 3

    # Avoid entering directly into nearby resistance/support.
    price = h1["price"]
    atr = h1["atr"]

    if atr <= 0:
        return None

    if direction == "LONG":
        nearby = [level for level in resistances if level > price]
        distance = (min(nearby) - price) / atr if nearby else 3.0
    else:
        nearby = [level for level in supports if level < price]
        distance = (price - max(nearby)) / atr if nearby else 3.0

    if distance >= 1.5:
        score += 15
    elif distance >= 1.0:
        score += 10
    elif distance >= 0.65:
        score += 5

    # 15m candle confirmation.
    if m15["candle_direction"] == direction:
        score += 10
    elif m15["candle_direction"] == "NEUTRAL":
        score += 4

    return min(score, 100)


def make_trade_levels(direction, price, atr, supports, resistances):
    if atr <= 0:
        return None

    if direction == "LONG":
        stop = price - 1.5 * atr

        # Place stop beyond nearby support when practical.
        valid_supports = [s for s in supports if s < price]
        if valid_supports:
            candidate_stop = max(valid_supports) - 0.2 * atr
            if candidate_stop < price and candidate_stop > stop:
                stop = candidate_stop

        risk = price - stop
        if risk <= 0:
            return None

        targets = [
            price + risk * 1.0,
            price + risk * 1.5,
            price + risk * 2.0,
        ]

    else:
        stop = price + 1.5 * atr

        valid_resistances = [r for r in resistances if r > price]
        if valid_resistances:
            candidate_stop = min(valid_resistances) + 0.2 * atr
            if candidate_stop > price and candidate_stop < stop:
                stop = candidate_stop

        risk = stop - price
        if risk <= 0:
            return None

        targets = [
            price - risk * 1.0,
            price - risk * 1.5,
            price - risk * 2.0,
        ]

    return {
        "entry": price,
        "stop": stop,
        "targets": targets,
        "risk": risk,
    }


def fmt_price(value):
    if value is None:
        return "نامشخص"

    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.5f}"
    return f"{value:.8f}"


def get_market_analysis(symbol):
    m15 = analyze_candles(get_candles(symbol, "15m"))
    h1 = analyze_candles(get_candles(symbol, "1h"))
    h4 = analyze_candles(get_candles(symbol, "4h"))
    daily = analyze_candles(get_candles(symbol, "1d"))

    supports, resistances = find_support_resistance(
        h4["candles"], h4["price"], h4["atr"]
    )

    score = score_candidate(h1, h4, m15, supports, resistances)

    return {
        "symbol": symbol,
        "m15": m15,
        "h1": h1,
        "h4": h4,
        "daily": daily,
        "supports": supports,
        "resistances": resistances,
        "score": score,
    }


def summarize_trend(analyses, timeframe):
    values = [
        a[timeframe]["direction"]
        for a in analyses
        if timeframe in a
    ]

    if not values:
        return "نامشخص"

    bullish = values.count("LONG")
    bearish = values.count("SHORT")
    total = len(values)

    if bullish / total >= 0.60:
        return "🟢 صعودی"
    if bearish / total >= 0.60:
        return "🔴 نزولی"

    return "🟡 خنثی / ترکیبی"


def format_levels(title, levels):
    if not levels:
        return f"{title}: سطح معتبر کافی پیدا نشد"

    return "\n".join(
        f"{title}{i}: {fmt_price(value)}"
        for i, value in enumerate(levels, 1)
    )


def build_report(analyses, errors):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not analyses:
        return (
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 گزارش روند بازار\n"
            "⚠️ داده کافی دریافت نشد.\n"
            f"خطاهای دریافت داده: {len(errors)}\n"
            f"زمان: {now}\n"
            "🚫 هیچ سفارش واقعی ثبت نشده است."
        )

    trend_1h = summarize_trend(analyses, "h1")
    trend_4h = summarize_trend(analyses, "h4")
    trend_1d = summarize_trend(analyses, "daily")

    btc = next(
        (a for a in analyses if a["symbol"] == "BTCUSDT"),
        None,
    )

    alts = [a for a in analyses if a["symbol"] != "BTCUSDT"]
    alt_trend = summarize_trend(alts, "h4") if alts else "نامشخص"

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش روند کلی بازار",
        "━━━━━━━━━━━━━━━━━━",
        f"⏱ کوتاه‌مدت (۱ ساعته): {trend_1h}",
        f"🕓 میان‌مدت (۴ ساعته): {trend_4h}",
        f"📅 روزانه: {trend_1d}",
        f"₿ آلت‌کوین‌ها: {alt_trend}",
    ]

    if btc:
        b = btc["h4"]
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━",
            "₿ وضعیت بیت‌کوین",
            f"روند ۴ ساعته: {b['direction']}",
            f"قدرت روند: {'قوی' if b['atr'] and abs(b['ema20'] - b['ema50']) / b['price'] >= 0.01 else 'متوسط' if b['atr'] and abs(b['ema20'] - b['ema50']) / b['price'] >= 0.003 else 'ضعیف'}",
            f"RSI: {b['rsi']:.1f}",
            f"تغییر آخرین کندل: {b['change_pct']:+.2f}%",
        ])

    eligible = [
        a for a in analyses
        if a["score"] is not None and a["score"] >= MIN_SCORE
    ]

    # Keep only the single highest-scoring candidate.
    eligible.sort(key=lambda a: a["score"], reverse=True)
    best = eligible[0] if eligible else None

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🎯 بهترین فرصت بازار",
        "━━━━━━━━━━━━━━━━━━",
    ])

    if not best:
        lines.extend([
            "⚪ WAIT — ارز واجد شرایط پیدا نشد",
            f"حداقل امتیاز لازم: {MIN_SCORE}/100",
            "جهت معامله به‌اجبار انتخاب نمی‌شود.",
        ])
    else:
        symbol = best["symbol"]
        direction = best["h4"]["direction"]
        score = best["score"]
        price = best["h1"]["price"]

        levels = make_trade_levels(
            direction,
            price,
            best["h1"]["atr"],
            best["supports"],
            best["resistances"],
        )

        if levels is None:
            lines.extend([
                "⚪ WAIT — محاسبه ریسک معتبر نبود",
            ])
        else:
            strength = "🔥 قوی" if score >= STRONG_SCORE else "🟡 قابل‌بررسی"

            lines.extend([
                f"🪙 ارز منتخب: {symbol}",
                f"📌 جهت: {'🟢 LONG' if direction == 'LONG' else '🔴 SHORT'}",
                f"💪 قدرت سیگنال: {score}/100 — {strength}",
                f"💵 قیمت فعلی/ورود فرضی: {fmt_price(levels['entry'])}",
                f"🛑 حد ضرر: {fmt_price(levels['stop'])}",
                f"🎯 TP1: {fmt_price(levels['targets'][0])}",
                f"🎯 TP2: {fmt_price(levels['targets'][1])}",
                f"🎯 TP3: {fmt_price(levels['targets'][2])}",
                f"📊 RSI یک‌ساعته: {best['h1']['rsi']:.1f}",
                f"📦 نسبت حجم: {best['h1']['volume_ratio']:.2f}x",
                "",
                "🟢 حمایت‌های مهم:",
                format_levels("S", best["supports"]),
                "",
                "🔴 مقاومت‌های مهم:",
                format_levels("R", best["resistances"]),
            ])

            nearest_resistance = next(
                (r for r in best["resistances"] if r > price), None
            )
            nearest_support = next(
                (s for s in best["supports"] if s < price), None
            )

            lines.extend([
                "",
                "📏 فاصله از نزدیک‌ترین سطوح:",
                (
                    f"تا حمایت: {(price - nearest_support) / price * 100:.2f}%"
                    if nearest_support else "تا حمایت: نامشخص"
                ),
                (
                    f"تا مقاومت: {(nearest_resistance - price) / price * 100:.2f}%"
                    if nearest_resistance else "تا مقاومت: نامشخص"
                ),
            ])

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"📊 بازارهای تحلیل‌شده: {len(analyses)}",
        f"⚠️ خطاهای دریافت داده: {len(errors)}",
        f"🕒 زمان گزارش: {now}",
        "━━━━━━━━━━━━━━━━━━",
        "🧪 تحلیل آزمایشی؛ بدون سفارش واقعی",
        "⚠️ امتیاز بالا تضمین سود نیست.",
    ])

    return "\n".join(lines)


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Secrets missing: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    response = SESSION.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram did not accept the message")


def main():
    logging.info("Starting %s", BOT_NAME)

    analyses = []
    errors = []

    for symbol in SYMBOLS:
        try:
            result = get_market_analysis(symbol)
            analyses.append(result)
            logging.info(
                "%s analyzed; candidate score=%s",
                symbol,
                result["score"],
            )
        except Exception as exc:
            errors.append(f"{symbol}: {str(exc)[:180]}")
            logging.warning("Skipped %s: %s", symbol, exc)

        time.sleep(0.15)

    report = build_report(analyses, errors)
    print(report)
    send_telegram(report)

    logging.info(
        "Report sent: analyzed=%d errors=%d",
        len(analyses),
        len(errors),
    )


if __name__ == "__main__":
    main()
