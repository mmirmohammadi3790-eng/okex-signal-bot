
import os
import time
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# ETH WHALE | ONE BEST FUTURES SIGNAL
# BITPIN USDT MARKETS + BINANCE PUBLIC CANDLES
# PAPER SIGNALS ONLY - NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
BITPIN_BASE = "https://api.bitpin.ir"
BINANCE_BASE = "https://api.binance.com"

# تنظیمات
CAPITAL_USDT = 48.0
LEVERAGE = 3
MARGIN_PER_TRADE = 16.0
POSITION_NOTIONAL = MARGIN_PER_TRADE * LEVERAGE

MAX_MARKETS = 40
MIN_SCORE = 80
MIN_RR_TP2 = 1.8
MIN_VOLUME_RATIO = 1.15
SCAN_DELAY = 2

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ETH-WHALE-Paper-Signal/1.0"})


def get_json(url, params=None, timeout=12):
    response = SESSION.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram credentials missing; message printed locally.")
        print(message)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = SESSION.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True
            },
            timeout=15
        )
        response.raise_for_status()

        result = response.json()
        if not result.get("ok"):
            logging.error("Telegram rejected message: %s", result)
            return False

        return True

    except Exception as exc:
        logging.error("Telegram send failed: %s", exc)
        return False


def get_bitpin_markets():
    """دریافت بازارهای USDT قابل معامله از بیت‌پین."""
    all_markets = []

    for page in range(1, 6):
        try:
            data = get_json(
                f"{BITPIN_BASE}/v1/mkt/markets/",
                params={"page": page},
                timeout=15
            )
        except Exception as exc:
            if page == 1:
                raise RuntimeError(
                    f"Bitpin markets unavailable: {exc}"
                )
            break

        if isinstance(data, list):
            results = data
        elif isinstance(data, dict):
            results = data.get("results", [])
        else:
            results = []

        if not results:
            break

        all_markets.extend(results)

        if isinstance(data, dict) and not data.get("next"):
            break

    selected = {}

    for market in all_markets:
        if not isinstance(market, dict):
            continue

        code = str(market.get("code", "")).upper().replace("-", "_")

        if not code.endswith("_USDT"):
            continue

        if market.get("tradable") is False:
            continue

        base = code[:-5]

        # از نمادهای غیرعادی یا خالی صرف‌نظر کن
        if not base or not base.replace("_", "").isalnum():
            continue

        # برای انتخاب اولیه، ارزش معامله موجود را در صورت دسترسی بخوان
        volume = 0.0
        for key in ("order_book_info", "price_info", "internal_price_info"):
            info = market.get(key)
            if isinstance(info, dict):
                for volume_key in ("value", "amount"):
                    try:
                        volume = max(
                            volume,
                            float(info.get(volume_key) or 0)
                        )
                    except (ValueError, TypeError):
                        pass

        selected[base] = {
            "base": base,
            "symbol": code,
            "volume": volume
        }

    if not selected:
        raise RuntimeError(
            "No tradable Bitpin USDT markets were found."
        )

    # فقط تعداد محدودی بازار بررسی می‌شود تا اسکن سریع‌تر بماند
    markets = sorted(
        selected.values(),
        key=lambda item: item["volume"],
        reverse=True
    )

    return markets[:MAX_MARKETS]


def get_binance_klines(symbol, interval, limit=120):
    url = f"{BINANCE_BASE}/api/v3/klines"

    data = get_json(
        url,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        },
        timeout=12
    )

    if not isinstance(data, list) or len(data) < 60:
        raise RuntimeError(f"Not enough candles for {symbol} {interval}")

    candles = []
    for row in data:
        candles.append({
            "open_time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": int(row[6])
        })

    # آخرین کندل ممکن است هنوز باز باشد؛ آن را حذف کن
    now_ms = int(time.time() * 1000)
    if candles and candles[-1]["close_time"] > now_ms:
        candles.pop()

    if len(candles) < 55:
        raise RuntimeError(f"Not enough closed candles for {symbol}")

    return candles


def ema(values, period):
    if len(values) < period:
        return None

    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    if len(candles) < period + 2:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )
        true_ranges.append(tr)

    recent = true_ranges[-period:]
    return sum(recent) / len(recent)


def average(values):
    return sum(values) / len(values) if values else 0.0


def pct_distance(price, level):
    if price <= 0:
        return 0.0
    return abs(price - level) / price * 100.0


def analyze_market(market):
    base = market["base"]
    symbol = base + "USDT"

    # تایم‌فریم‌های تأیید
    candles15 = get_binance_klines(symbol, "15m")
    candles1h = get_binance_klines(symbol, "1h")

    closes15 = [c["close"] for c in candles15]
    closes1h = [c["close"] for c in candles1h]

    price = closes15[-1]

    if price <= 0:
        return None

    ema20_15 = ema(closes15, 20)
    ema50_15 = ema(closes15, 50)
    ema20_1h = ema(closes1h, 20)
    ema50_1h = ema(closes1h, 50)

    rsi15 = rsi(closes15)
    rsi1h = rsi(closes1h)
    atr15 = atr(candles15)

    if any(v is None for v in (
        ema20_15, ema50_15, ema20_1h, ema50_1h,
        rsi15, rsi1h, atr15
    )):
        return None

    if atr15 <= 0:
        return None

    # حجم کندل بسته‌شده اخیر در برابر 20 کندل قبل
    recent_volumes = [c["volume"] for c in candles15[-21:-1]]
    current_volume = candles15[-1]["volume"]
    avg_volume = average(recent_volumes)

    if avg_volume <= 0:
        return None

    volume_ratio = current_volume / avg_volume

    # حمایت و مقاومت: محدوده 30 کندل قبل از آخرین کندل
    structure = candles15[-31:-1]
    support = min(c["low"] for c in structure)
    resistance = max(c["high"] for c in structure)

    if support >= price or resistance <= price:
        return None

    support_distance = pct_distance(price, support)
    resistance_distance = pct_distance(price, resistance)

    bullish15 = ema20_15 > ema50_15 and price > ema20_15
    bearish15 = ema20_15 < ema50_15 and price < ema20_15

    bullish1h = ema20_1h > ema50_1h
    bearish1h = ema20_1h < ema50_1h

    direction = None

    if bullish15 and bullish1h and 52 <= rsi15 <= 68 and 50 <= rsi1h <= 70:
        direction = "LONG"

    elif bearish15 and bearish1h and 32 <= rsi15 <= 48 and 30 <= rsi1h <= 50:
        direction = "SHORT"

    if direction is None:
        return None

    # حجم باید تأییدکننده باشد
    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    # ورود نزدیک مانع مخالف، ریسک نامناسب دارد
    if direction == "LONG":
        if resistance_distance < 1.5 * atr15 / price * 100:
            return None

        # حد ضرر زیر حمایت یا با فاصله ATR؛ هرکدام پایین‌تر باشد
        stop = min(support - 0.15 * atr15, price - 1.2 * atr15)

        if stop <= 0 or stop >= price:
            return None

        risk = price - stop
        tp1 = price + risk * 1.0
        tp2 = price + risk * 1.8
        tp3 = price + risk * 2.5

        # فاصله مانع را تا اولین مقاومت ساختاری نمایش بده
        resistance_level = resistance

    else:
        if support_distance < 1.5 * atr15 / price * 100:
            return None

        # حد ضرر بالای مقاومت یا با فاصله ATR؛ هرکدام بالاتر باشد
        stop = max(resistance + 0.15 * atr15, price + 1.2 * atr15)

        risk = stop - price

        if risk <= 0:
            return None

        tp1 = price - risk * 1.0
        tp2 = price - risk * 1.8
        tp3 = price - risk * 2.5

        if tp3 <= 0:
            return None

        resistance_level = resistance

    reward_risk_tp2 = abs(tp2 - price) / risk

    if reward_risk_tp2 < MIN_RR_TP2:
        return None

    # امتیاز کیفیت؛ فقط گزینه‌های قوی پذیرفته می‌شوند
    score = 0

    score += 25  # تأیید روند دو تایم‌فریم
    score += 20  # هم‌جهتی قیمت و EMA در 15m

    if direction == "LONG":
        if 55 <= rsi15 <= 64:
            score += 15
        elif 52 <= rsi15 <= 68:
            score += 10

        if 53 <= rsi1h <= 65:
            score += 10
        else:
            score += 5
    else:
        if 36 <= rsi15 <= 45:
            score += 15
        elif 32 <= rsi15 <= 48:
            score += 10

        if 35 <= rsi1h <= 47:
            score += 10
        else:
            score += 5

    if volume_ratio >= 1.5:
        score += 15
    elif volume_ratio >= MIN_VOLUME_RATIO:
        score += 10

    if reward_risk_tp2 >= 2.2:
        score += 10
    elif reward_risk_tp2 >= MIN_RR_TP2:
        score += 5

    if score < MIN_SCORE:
        return None

    # برآورد ریسک دلاری روی مارجین فرضی؛ کارمزد لحاظ نشده
    risk_pct_of_position = risk / price
    estimated_loss = POSITION_NOTIONAL * risk_pct_of_position
    estimated_gain_tp2 = POSITION_NOTIONAL * abs(tp2 - price) / price

    return {
        "base": base,
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "support": support,
        "resistance": resistance_level,
        "support_distance": support_distance,
        "resistance_distance": resistance_distance,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "volume_ratio": volume_ratio,
        "atr": atr15,
        "score": score,
        "rr": reward_risk_tp2,
        "estimated_loss": estimated_loss,
        "estimated_gain_tp2": estimated_gain_tp2
    }


def fmt(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def make_signal_message(signal, scanned, errors):
    direction_fa = "خرید (LONG)" if signal["direction"] == "LONG" else "فروش (SHORT)"

    return (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🏆 بهترین سیگنال فیوچرز\n"
        "🧪 PAPER TRADING ONLY\n"
        "🚫 سفارش واقعی: غیرفعال\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🪙 نماد: {signal['base']}/USDT\n"
        f"📍 جهت: {direction_fa}\n"
        f"⭐ امتیاز کیفیت: {signal['score']}/100\n\n"
        f"🎯 ورود فرضی: {fmt(signal['price'])}\n"
        f"🛑 حد ضرر: {fmt(signal['stop'])}\n"
        f"🥇 TP1: {fmt(signal['tp1'])}\n"
        f"🥈 TP2: {fmt(signal['tp2'])}\n"
        f"🥉 TP3: {fmt(signal['tp3'])}\n\n"
        "📐 حمایت و مقاومت\n"
        f"🟢 حمایت: {fmt(signal['support'])}\n"
        f"↕️ فاصله تا حمایت: {signal['support_distance']:.2f}%\n"
        f"🔴 مقاومت: {fmt(signal['resistance'])}\n"
        f"↕️ فاصله تا مقاومت: {signal['resistance_distance']:.2f}%\n\n"
        "📊 تأییدها\n"
        f"• RSI 15m: {signal['rsi15']:.1f}\n"
        f"• RSI 1h: {signal['rsi1h']:.1f}\n"
        f"• حجم نسبت به میانگین: {signal['volume_ratio']:.2f}x\n"
        f"• نسبت سود به زیان تا TP2: {signal['rr']:.2f}R\n\n"
        "💰 محاسبات آزمایشی\n"
        f"• سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
        f"• مارجین فرضی: {MARGIN_PER_TRADE:.2f} USDT\n"
        f"• اهرم محاسباتی: {LEVERAGE}x\n"
        f"• ارزش فرضی موقعیت: {POSITION_NOTIONAL:.2f} USDT\n"
        f"• زیان برآوردی تا SL: {signal['estimated_loss']:.3f} USDT\n"
        f"• سود برآوردی تا TP2: {signal['estimated_gain_tp2']:.3f} USDT\n"
        "⚠️ تخمین‌ها بدون کارمزد، لغزش قیمت و فاندینگ هستند.\n\n"
        f"🔎 بازارهای بررسی‌شده: {scanned}\n"
        f"⚠️ خطاهای تحلیل: {errors}\n"
        f"🕒 زمان UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ سیگنال احتمالاتی است؛ سود تضمین‌شده نیست."
    )


def make_wait_message(scanned, errors):
    return (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚪ WAIT — سیگنال باکیفیت پیدا نشد\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔎 بازارهای بررسی‌شده: {scanned}\n"
        f"⚠️ خطاهای تحلیل: {errors}\n"
        f"⭐ حداقل امتیاز لازم: {MIN_SCORE}/100\n"
        "🧪 حالت آزمایشی فعال است.\n"
        "🚫 هیچ سفارش واقعی ثبت نشده است.\n"
        "━━━━━━━━━━━━━━━━━━"
    )


def main():
    logging.info("Starting %s", BOT_NAME)

    try:
        markets = get_bitpin_markets()
    except Exception as exc:
        message = (
            f"{BOT_NAME}\n"
            "❌ دریافت فهرست بازارها ناموفق بود.\n"
            f"علت: {str(exc)[:500]}\n"
            "هیچ سفارشی ثبت نشده است."
        )
        send_telegram(message)
        raise

    candidates = []
    errors = 0
    scanned = 0

    logging.info("Markets selected for analysis: %s", len(markets))

    for market in markets:
        try:
            signal = analyze_market(market)
            scanned += 1

            if signal:
                candidates.append(signal)
                logging.info(
                    "Candidate %s %s score=%s",
                    signal["symbol"],
                    signal["direction"],
                    signal["score"]
                )

        except Exception as exc:
            errors += 1
            logging.warning(
                "Skipping %s: %s",
                market.get("symbol", market.get("base", "?")),
                exc
            )

        time.sleep(SCAN_DELAY)

    if not candidates:
        send_telegram(make_wait_message(scanned, errors))
        logging.info("No qualifying signal found.")
        return

    # فقط یک گزینه: بالاترین امتیاز، سپس بهترین نسبت سود به زیان
    candidates.sort(
        key=lambda s: (s["score"], s["rr"], s["volume_ratio"]),
        reverse=True
    )

    best = candidates[0]
    message = make_signal_message(best, scanned, errors)
    send_telegram(message)

    logging.info(
        "Sent single best signal: %s %s score=%s",
        best["symbol"],
        best["direction"],
        best["score"]
    )


if __name__ == "__main__":
    main()
