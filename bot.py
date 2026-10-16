
import os
import time
import logging
import requests
from datetime import datetime, timezone

# ==========================================================
# 🐋 ETH WHALE | CRYPTO MARKET TREND
# فقط گزارش روند بازار — بدون سیگنال و سفارش واقعی
# ==========================================================

BOT_NAME = "🐋 ETH WHALE"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

BASE_URLS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

TIMEFRAMES = {
    "1h": "کوتاه‌مدت",
    "4h": "میان‌مدت",
    "1d": "روزانه",
}

MARKET_SYMBOLS = [
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

TIMEOUT = 12
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ETH-WHALE-Market-Trend/1.0"})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def get_klines(symbol, interval, limit=100):
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

            errors.append(base_url + ": insufficient candle data")

        except Exception as exc:
            errors.append(base_url + ": " + str(exc)[:160])

    raise RuntimeError(" | ".join(errors))


def calculate_trend(candles):
    closes = [float(candle[4]) for candle in candles]
    volumes = [float(candle[5]) for candle in candles]

    def ema(values, period):
        alpha = 2 / (period + 1)
        result = values[0]

        for value in values[1:]:
            result = alpha * value + (1 - alpha) * result

        return result

    ema20 = ema(closes[-100:], 20)
    ema50 = ema(closes[-100:], 50)

    # RSI محاسبه‌شده از تغییرات اخیر قیمت
    changes = [
        closes[i] - closes[i - 1]
        for i in range(len(closes) - 14, len(closes))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14

    if avg_loss == 0:
        rsi = 100 if avg_gain > 0 else 50
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

    price = closes[-1]
    previous_price = closes[-2]

    if price > ema20 > ema50:
        direction = "صعودی"
        score = 1
    elif price < ema20 < ema50:
        direction = "نزولی"
        score = -1
    else:
        direction = "خنثی"
        score = 0

    if rsi >= 70:
        momentum = "اشباع خرید"
    elif rsi <= 30:
        momentum = "اشباع فروش"
    elif rsi >= 55:
        momentum = "تمایل صعودی"
    elif rsi <= 45:
        momentum = "تمایل نزولی"
    else:
        momentum = "متعادل"

    recent_volume = sum(volumes[-5:]) / 5
    previous_volume = sum(volumes[-20:-5]) / 15

    if previous_volume > 0:
        volume_ratio = recent_volume / previous_volume
    else:
        volume_ratio = 0

    if abs(ema20 - ema50) / price >= 0.01:
        strength = "قوی"
    elif abs(ema20 - ema50) / price >= 0.003:
        strength = "متوسط"
    else:
        strength = "ضعیف"

    change_pct = (
        (price / previous_price - 1) * 100
        if previous_price else 0
    )

    return {
        "direction": direction,
        "score": score,
        "rsi": rsi,
        "momentum": momentum,
        "strength": strength,
        "change": change_pct,
        "volume_ratio": volume_ratio,
    }


def analyze_market():
    results = []
    errors = []

    for symbol in MARKET_SYMBOLS:
        row = {"symbol": symbol}

        for interval, label in TIMEFRAMES.items():
            try:
                candles = get_klines(symbol, interval)
                row[interval] = calculate_trend(candles)
            except Exception as exc:
                errors.append(f"{symbol} {interval}: {str(exc)[:120]}")

        if "4h" in row:
            results.append(row)

        time.sleep(0.15)

    return results, errors


def direction_summary(results, timeframe):
    available = [
        row[timeframe]["score"]
        for row in results
        if timeframe in row
    ]

    if not available:
        return "نامشخص", 0, 0

    bullish = sum(score == 1 for score in available)
    bearish = sum(score == -1 for score in available)
    neutral = sum(score == 0 for score in available)
    total = len(available)

    if bullish / total >= 0.60:
        trend = "🟢 صعودی"
    elif bearish / total >= 0.60:
        trend = "🔴 نزولی"
    else:
        trend = "🟡 خنثی / ترکیبی"

    return trend, bullish, bearish


def build_report(results, errors):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not results:
        return (
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 گزارش روند بازار\n\n"
            "⚠️ داده کافی دریافت نشد.\n"
            "ممکن است دسترسی منبع داده محدود باشد.\n"
            f"خطاها: {len(errors)}\n"
            f"زمان: {now}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ℹ️ فقط تحلیل بازار؛ بدون سفارش واقعی."
        )

    trend_1h, bull_1h, bear_1h = direction_summary(results, "1h")
    trend_4h, bull_4h, bear_4h = direction_summary(results, "4h")
    trend_1d, bull_1d, bear_1d = direction_summary(results, "1d")

    btc = next(
        (row for row in results if row["symbol"] == "BTCUSDT"),
        None,
    )

    alt_rows = [
        row for row in results
        if row["symbol"] != "BTCUSDT" and "4h" in row
    ]

    if alt_rows:
        alt_scores = [row["4h"]["score"] for row in alt_rows]
        alt_bull = sum(score == 1 for score in alt_scores)
        alt_bear = sum(score == -1 for score in alt_scores)
        alt_total = len(alt_scores)

        if alt_bull / alt_total >= 0.60:
            alt_trend = "🟢 عمدتاً صعودی"
        elif alt_bear / alt_total >= 0.60:
            alt_trend = "🔴 عمدتاً نزولی"
        else:
            alt_trend = "🟡 ترکیبی"
    else:
        alt_trend = "نامشخص"

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

    if btc and "4h" in btc:
        data = btc["4h"]
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━",
            "₿ وضعیت بیت‌کوین",
            f"روند ۴ ساعته: {data['direction']}",
            f"قدرت روند: {data['strength']}",
            f"RSI: {data['rsi']:.1f}",
            f"مومنتوم: {data['momentum']}",
            f"تغییر آخرین کندل: {data['change']:+.2f}%",
        ])

    if trend_1h.startswith("🟢") and trend_4h.startswith("🟢"):
        conclusion = "تمایل صعودی در کوتاه‌مدت و میان‌مدت"
    elif trend_1h.startswith("🔴") and trend_4h.startswith("🔴"):
        conclusion = "تمایل نزولی در کوتاه‌مدت و میان‌مدت"
    elif trend_1h.startswith("🟡") or trend_4h.startswith("🟡"):
        conclusion = "بازار ترکیبی است؛ جهت واحد تأیید نشده"
    else:
        conclusion = "روندها هم‌جهت نیستند یا داده کافی نیست"

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"🧭 جمع‌بندی: {conclusion}",
        f"📊 بازارهای تحلیل‌شده: {len(results)}",
        f"⚠️ خطاهای دریافت داده: {len(errors)}",
        f"🕒 زمان گزارش: {now}",
        "━━━━━━━━━━━━━━━━━━",
        "ℹ️ فقط گزارش روند بازار",
        "🚫 بدون سیگنال خریدوفروش یا سفارش واقعی",
    ])

    return "\n".join(lines)


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Telegram secrets missing: "
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
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
        raise RuntimeError("Telegram rejected the message")


def main():
    logging.info("Starting %s — market trend only", BOT_NAME)

    results, errors = analyze_market()
    report = build_report(results, errors)

    print(report)
    send_telegram(report)

    logging.info(
        "Report sent. Markets=%s Errors=%s",
        len(results),
        len(errors),
    )


if __name__ == "__main__":
    main()
