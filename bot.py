
import os
import time
import logging
import requests
from datetime import datetime, timezone

# =========================================================
# ETH WHALE - ONE BEST FUTURES SIGNAL
# PAPER ONLY - NO REAL ORDERS
# Capital: 48 USDT | Leverage calculation: 3x
# =========================================================

BOT_NAME = "🐋 ETH WHALE"
BITPIN_URL = "https://api.bitpin.ir"
CANDLE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api.binance.com",
]

CAPITAL = 48.0
LEVERAGE = 3
MARGIN = 16.0
NOTIONAL = MARGIN * LEVERAGE

MAX_MARKETS = 40
MIN_SCORE = 80
MIN_VOLUME_RATIO = 1.15
MIN_RR = 1.8
REQUEST_TIMEOUT = 8

TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or ""
).strip()

CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
    or ""
).strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

S = requests.Session()
S.headers.update({"User-Agent": "ETH-WHALE-PaperBot/2.0"})


def get_json(url, params=None, timeout=REQUEST_TIMEOUT):
    r = S.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def send_message(text):
    print(text)

    if not TOKEN or not CHAT_ID:
        logging.error("Telegram secrets are missing.")
        return

    try:
        r = S.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        r.raise_for_status()

        if not r.json().get("ok"):
            logging.error("Telegram API did not confirm delivery.")

    except Exception as exc:
        logging.error("Telegram error: %s", exc)


def get_markets():
    markets = []
    url = f"{BITPIN_URL}/v1/mkt/markets/"

    for page in range(1, 10):
        data = get_json(url, {"page": page}, timeout=15)

        if isinstance(data, list):
            rows = data
            has_next = False
        elif isinstance(data, dict):
            rows = data.get("results", [])
            has_next = bool(data.get("next"))
        else:
            rows = []
            has_next = False

        for item in rows:
            if not isinstance(item, dict):
                continue

            code = str(item.get("code", "")).upper().replace("-", "_")

            if not code.endswith("_USDT"):
                continue

            if item.get("tradable") is False:
                continue

            base = code[:-5]
            if not base or not base.replace("_", "").isalnum():
                continue

            volume = 0.0
            for key in (
                "order_book_info",
                "price_info",
                "internal_price_info",
            ):
                info = item.get(key)
                if isinstance(info, dict):
                    try:
                        volume = max(
                            volume,
                            float(info.get("value") or 0)
                        )
                    except (ValueError, TypeError):
                        pass

            markets.append({
                "base": base,
                "code": code,
                "volume": volume,
            })

        if not has_next or not rows:
            break

        time.sleep(0.15)

    # حذف نمادهای تکراری
    unique = {m["base"]: m for m in markets}
    result = sorted(
        unique.values(),
        key=lambda m: m["volume"],
        reverse=True,
    )

    if not result:
        raise RuntimeError("No Bitpin USDT markets found.")

    return result[:MAX_MARKETS]


def get_candles(symbol, interval, limit=120):
    errors = []

    for host in CANDLE_HOSTS:
        try:
            data = get_json(
                f"{host}/api/v3/klines",
                {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                },
            )

            if not isinstance(data, list) or len(data) < 60:
                raise RuntimeError("Insufficient candle history")

            candles = []
            for row in data:
                candles.append({
                    "time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": int(row[6]),
                })

            # حذف کندل باز
            now_ms = int(time.time() * 1000)
            if candles and candles[-1]["close_time"] > now_ms:
                candles.pop()

            if len(candles) < 55:
                raise RuntimeError("Not enough closed candles")

            return candles

        except Exception as exc:
            errors.append(f"{host}: {str(exc)[:100]}")

    raise RuntimeError(
        f"No candle source available for {symbol} {interval}. "
        + " | ".join(errors)
    )


def ema(values, period):
    if len(values) < period:
        return None

    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)

    for price in values[period:]:
        value = alpha * price + (1 - alpha) * value

    return value


def calc_rsi(values, period=14):
    if len(values) <= period:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

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
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def calc_atr(candles, period=14):
    trs = []

    for i in range(1, len(candles)):
        c = candles[i]
        p = candles[i - 1]

        trs.append(max(
            c["high"] - c["low"],
            abs(c["high"] - p["close"]),
            abs(c["low"] - p["close"]),
        ))

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


def pct_distance(price, level):
    if price <= 0:
        return 0.0
    return abs(price - level) / price * 100


def fmt(number):
    if number >= 1000:
        return f"{number:,.2f}"
    if number >= 1:
        return f"{number:.6f}".rstrip("0").rstrip(".")
    return f"{number:.8f}".rstrip("0").rstrip(".")


def analyze(market):
    base = market["base"]
    symbol = base + "USDT"

    c15 = get_candles(symbol, "15m")
    c1h = get_candles(symbol, "1h")

    closes15 = [c["close"] for c in c15]
    closes1h = [c["close"] for c in c1h]

    price = closes15[-1]
    e20_15 = ema(closes15, 20)
    e50_15 = ema(closes15, 50)
    e20_1h = ema(closes1h, 20)
    e50_1h = ema(closes1h, 50)
    rsi15 = calc_rsi(closes15)
    rsi1h = calc_rsi(closes1h)
    atr15 = calc_atr(c15)

    if any(x is None for x in (
        e20_15, e50_15, e20_1h, e50_1h,
        rsi15, rsi1h, atr15
    )):
        return None

    if price <= 0 or atr15 <= 0:
        return None

    # حجم آخر کندل بسته‌شده نسبت به 20 کندل قبل
    avg_vol = sum(c["volume"] for c in c15[-21:-1]) / 20
    vol_ratio = c15[-1]["volume"] / avg_vol if avg_vol > 0 else 0

    # حمایت و مقاومت از 30 کندل قبلی
    structure = c15[-31:-1]
    support = min(c["low"] for c in structure)
    resistance = max(c["high"] for c in structure)

    if support >= price or resistance <= price:
        return None

    bullish15 = e20_15 > e50_15 and price > e20_15
    bearish15 = e20_15 < e50_15 and price < e20_15
    bullish1h = e20_1h > e50_1h
    bearish1h = e20_1h < e50_1h

    direction = None

    if bullish15 and bullish1h and 52 <= rsi15 <= 68 and 50 <= rsi1h <= 70:
        direction = "LONG"
    elif bearish15 and bearish1h and 32 <= rsi15 <= 48 and 30 <= rsi1h <= 50:
        direction = "SHORT"

    if direction is None or vol_ratio < MIN_VOLUME_RATIO:
        return None

    support_pct = pct_distance(price, support)
    resistance_pct = pct_distance(price, resistance)
    atr_pct = atr15 / price * 100

    # از ورود درست جلوی مانع نزدیک اجتناب کن
    if direction == "LONG" and resistance_pct < 1.5 * atr_pct:
        return None

    if direction == "SHORT" and support_pct < 1.5 * atr_pct:
        return None

    if direction == "LONG":
        stop = min(support - 0.15 * atr15, price - 1.2 * atr15)
        risk = price - stop
        tp1 = price + risk
        tp2 = price + 1.8 * risk
        tp3 = price + 2.5 * risk
    else:
        stop = max(resistance + 0.15 * atr15, price + 1.2 * atr15)
        risk = stop - price
        tp1 = price - risk
        tp2 = price - 1.8 * risk
        tp3 = price - 2.5 * risk

    if risk <= 0 or (direction == "SHORT" and tp3 <= 0):
        return None

    rr = abs(tp2 - price) / risk
    if rr < MIN_RR:
        return None

    score = 25  # روند هر دو تایم‌فریم
    score += 20  # EMA و قیمت

    if direction == "LONG":
        score += 15 if 55 <= rsi15 <= 64 else 10
        score += 10 if 53 <= rsi1h <= 65 else 5
    else:
        score += 15 if 36 <= rsi15 <= 45 else 10
        score += 10 if 35 <= rsi1h <= 47 else 5

    score += 15 if vol_ratio >= 1.5 else 10
    score += 10 if rr >= 2.2 else 5

    if score < MIN_SCORE:
        return None

    return {
        "base": base,
        "direction": direction,
        "price": price,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "support": support,
        "resistance": resistance,
        "support_pct": support_pct,
        "resistance_pct": resistance_pct,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "vol_ratio": vol_ratio,
        "score": score,
        "rr": rr,
        "loss": NOTIONAL * risk / price,
        "gain_tp2": NOTIONAL * abs(tp2 - price) / price,
    }


def signal_message(best, scanned, errors):
    side = "خرید (LONG)" if best["direction"] == "LONG" else "فروش (SHORT)"

    return (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🏆 بهترین سیگنال فیوچرز\n"
        "🧪 PAPER ONLY | 🚫 بدون سفارش واقعی\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🪙 نماد: {best['base']}/USDT\n"
        f"📍 جهت: {side}\n"
        f"⭐ امتیاز: {best['score']}/100\n\n"
        f"🎯 ورود فرضی: {fmt(best['price'])}\n"
        f"🛑 حد ضرر: {fmt(best['stop'])}\n"
        f"🥇 TP1: {fmt(best['tp1'])}\n"
        f"🥈 TP2: {fmt(best['tp2'])}\n"
        f"🥉 TP3: {fmt(best['tp3'])}\n\n"
        "📐 حمایت و مقاومت\n"
        f"🟢 حمایت: {fmt(best['support'])}\n"
        f"↕️ فاصله تا حمایت: {best['support_pct']:.2f}%\n"
        f"🔴 مقاومت: {fmt(best['resistance'])}\n"
        f"↕️ فاصله تا مقاومت: {best['resistance_pct']:.2f}%\n\n"
        "📊 تأییدها\n"
        f"• RSI 15m: {best['rsi15']:.1f}\n"
        f"• RSI 1h: {best['rsi1h']:.1f}\n"
        f"• حجم نسبت به میانگین: {best['vol_ratio']:.2f}x\n"
        f"• نسبت سود به زیان TP2: {best['rr']:.2f}R\n\n"
        "💰 اندازه فرضی موقعیت\n"
        f"• سرمایه: {CAPITAL:.2f} USDT\n"
        f"• مارجین: {MARGIN:.2f} USDT\n"
        f"• اهرم محاسباتی: {LEVERAGE}x\n"
        f"• ارزش موقعیت: {NOTIONAL:.2f} USDT\n"
        f"• زیان برآوردی تا SL: {best['loss']:.3f} USDT\n"
        f"• سود برآوردی تا TP2: {best['gain_tp2']:.3f} USDT\n"
        "⚠️ برآوردها بدون کارمزد، فاندینگ و لغزش قیمت‌اند.\n\n"
        f"🔎 بازارهای بررسی‌شده: {scanned}\n"
        f"⚠️ خطاهای تحلیل: {errors}\n"
        f"🕒 UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ سیگنال احتمالاتی است؛ سود تضمین‌شده نیست."
    )


def main():
    logging.info("Starting %s", BOT_NAME)

    try:
        markets = get_markets()
    except Exception as exc:
        send_message(
            f"{BOT_NAME}\n"
            "❌ دریافت بازارهای بیت‌پین ناموفق بود.\n"
            f"علت: {str(exc)[:400]}\n"
            "هیچ سفارشی ثبت نشده است."
        )
        raise

    candidates = []
    errors = 0
    scanned = 0

    logging.info("Selected %s markets", len(markets))

    for market in markets:
        try:
            result = analyze(market)
            scanned += 1
            if result:
                candidates.append(result)
                logging.info(
                    "Candidate %s %s score=%s",
                    result["base"],
                    result["direction"],
                    result["score"],
                )
        except Exception as exc:
            errors += 1
            logging.warning("%s skipped: %s", market["base"], exc)

        time.sleep(0.4)

    if not candidates:
        send_message(
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚪ WAIT — سیگنال واجد شرایط پیدا نشد\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🔎 بازارهای بررسی‌شده: {scanned}\n"
            f"⚠️ خطاهای تحلیل: {errors}\n"
            f"⭐ حداقل امتیاز: {MIN_SCORE}/100\n"
            "اگر خطاها مربوط به منبع کندل باشند،"
            " دسترسی به سرویس داده باید بررسی شود.\n"
            "🧪 حالت آزمایشی؛ هیچ سفارش واقعی ثبت نشده است."
        )
        return

    candidates.sort(
        key=lambda x: (x["score"], x["rr"], x["vol_ratio"]),
        reverse=True,
    )

    send_message(signal_message(candidates[0], scanned, errors))


if __name__ == "__main__":
    main()
