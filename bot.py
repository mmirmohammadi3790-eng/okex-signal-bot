import os
import math
import time
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# 🐋 ETH WHALE — TREND WATCH + TP1/TP2/TP3
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

# برای تحلیل و گزارش؛ نه ثبت سفارش
PAPER_ONLY = True

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
SESSION.headers.update({"User-Agent": "ETH-WHALE-Paper-Analyzer/1.0"})


# -------------------- HTTP --------------------

def get_json(url, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Telegram secrets are missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
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
            logging.error("Telegram rejected the message.")
            return False

        return True

    except Exception as exc:
        logging.error("Telegram error: %s", exc)
        return False


# -------------------- INDICATORS --------------------

def ema(values, period):
    if len(values) < period:
        return None

    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result

    return result


def rsi(values, period=14):
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
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close)
            )
        )

    if len(true_ranges) < period:
        return None

    value = sum(true_ranges[:period]) / period

    for tr in true_ranges[period:]:
        value = (value * (period - 1) + tr) / period

    return value


# -------------------- MARKET DATA --------------------

def get_binance_markets():
    data = get_json(BINANCE_BASE + "/api/v3/ticker/24hr")
    exchange_info = get_json(BINANCE_BASE + "/api/v3/exchangeInfo")

    allowed = set()

    for item in exchange_info.get("symbols", []):
        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("isSpotTradingAllowed", True)
        ):
            symbol = item.get("symbol", "")
            base = item.get("baseAsset", "")

            if base in EXCLUDED_BASES:
                continue

            if base.endswith(LEVERAGED_ENDINGS):
                continue

            allowed.add(symbol)

    markets = []

    for item in data:
        symbol = item.get("symbol", "")

        if symbol not in allowed:
            continue

        try:
            quote_volume = float(item.get("quoteVolume", 0))
            price = float(item.get("lastPrice", 0))

            if quote_volume <= 0 or price <= 0:
                continue

            markets.append({
                "symbol": symbol,
                "price": price,
                "volume": quote_volume
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

    # آخرین کندل ممکن است هنوز باز باشد؛ حذفش می‌کنیم.
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

            if price <= 0 or volume <= 0:
                continue

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

    # Bybit کندل‌ها را معمولاً از جدید به قدیم می‌دهد.
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
        logging.warning("Binance market data failed: %s", exc)

    markets = get_bybit_markets()

    if markets:
        return "Bybit Linear", markets, get_bybit_candles

    raise RuntimeError("Both market data sources failed.")


# -------------------- SUPPORT / RESISTANCE --------------------

def find_levels(candles, price):
    recent = candles[-40:]

    lows = sorted(c["low"] for c in recent if c["low"] < price)
    highs = sorted(c["high"] for c in recent if c["high"] > price)

    support = max(lows) if lows else min(c["low"] for c in recent)
    resistance = min(highs) if highs else max(c["high"] for c in recent)

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


def distance_text(price, level):
    difference = abs(price - level)
    percent = difference / price * 100 if price else 0
    return f"{price_text(difference)} USDT ({percent:.2f}٪)"


# -------------------- ANALYSIS --------------------

def analyze_market(market, candle_fetcher):
    symbol = market["symbol"]

    candles15 = candle_fetcher(symbol, "15m")
    candles1h = candle_fetcher(symbol, "1h")

    if len(candles15) < 55 or len(candles1h) < 55:
        return None

    closes15 = [c["close"] for c in candles15]
    closes1h = [c["close"] for c in candles1h]

    price = closes15[-1]

    ema20_15 = ema(closes15, 20)
    ema50_15 = ema(closes15, 50)
    ema20_1h = ema(closes1h, 20)
    ema50_1h = ema(closes1h, 50)

    rsi15 = rsi(closes15)
    rsi1h = rsi(closes1h)
    atr15 = atr(candles15)

    if any(
        value is None
        for value in (
            ema20_15, ema50_15, ema20_1h,
            ema50_1h, rsi15, rsi1h, atr15
        )
    ):
        return None

    support, resistance = find_levels(candles15, price)

    support_distance_pct = (price - support) / price * 100
    resistance_distance_pct = (resistance - price) / price * 100

    if support_distance_pct <= 0 or resistance_distance_pct <= 0:
        return None

    gap15 = abs(ema20_15 - ema50_15) / price * 100
    gap1h = abs(ema20_1h - ema50_1h) / price * 100

    direction = None

    bullish = (
        ema20_15 > ema50_15
        and ema20_1h > ema50_1h
        and price > ema20_15
        and 48 <= rsi15 <= 65
        and 42 <= rsi1h <= 68
    )

    bearish = (
        ema20_15 < ema50_15
        and ema20_1h < ema50_1h
        and price < ema20_15
        and 35 <= rsi15 <= 52
        and 32 <= rsi1h <= 55
    )

    if bullish:
        direction = "LONG"
        room_pct = resistance_distance_pct

    elif bearish:
        direction = "SHORT"
        room_pct = support_distance_pct

    else:
        return None

    # فیلتر روند ضعیف و هدف خیلی نزدیک
    if gap15 < 0.03 or gap1h < 0.03:
        return None

    if room_pct < 0.60:
        return None

    # اهداف فرضی بر اساس فاصله تا مانع تکنیکال و ATR
    if direction == "LONG":
        tp1 = price + (resistance - price) * 0.40
        tp2 = price + (resistance - price) * 0.80
        tp3 = resistance + 0.50 * atr15

        rsi_quality = 1.0 - abs(rsi15 - 56) / 20

    else:
        tp1 = price - (price - support) * 0.40
        tp2 = price - (price - support) * 0.80
        tp3 = support - 0.50 * atr15

        rsi_quality = 1.0 - abs(rsi15 - 44) / 20

    rsi_quality = max(0.0, min(1.0, rsi_quality))

    # امتیاز کیفیت روند، فضای حرکت، RSI و حجم
    volume_score = min(
        1.0,
        math.log10(max(market["volume"], 1)) / 10
    )

    score = (
        min(gap15 * 8, 20)
        + min(gap1h * 8, 20)
        + min(room_pct * 4, 20)
        + rsi_quality * 20
        + volume_score * 20
    )

    return {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "volume": market["volume"],
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "ema20_15": ema20_15,
        "ema50_15": ema50_15,
        "ema20_1h": ema20_1h,
        "ema50_1h": ema50_1h,
        "support": support,
        "resistance": resistance,
        "support_distance_pct": support_distance_pct,
        "resistance_distance_pct": resistance_distance_pct,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "room_pct": room_pct,
        "score": score
    }


# -------------------- TELEGRAM REPORT --------------------

def build_report(result, source, checked, failures):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if result is None:
        return (
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 <b>گزارش روند بازار</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚪ در این اسکن گزینه‌ای با شرایط فیلترها پیدا نشد.\n\n"
            f"منبع: {source}\n"
            f"بازارهای بررسی‌شده: {checked}\n"
            f"خطاهای تحلیل: {failures}\n"
            f"زمان: {now}\n\n"
            "🧪 فقط تحلیل آزمایشی؛ هیچ سفارشی ثبت نشده است."
        )

    is_long = result["direction"] == "LONG"
    direction_text = "صعودی — LONG" if is_long else "نزولی — SHORT"

    target_note = (
        "اهداف در جهت صعود محاسبه شده‌اند."
        if is_long
        else "اهداف در جهت نزول محاسبه شده‌اند."
    )

    return (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 <b>بهترین گزینه‌ی روند در این اسکن</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🪙 بازار: <b>{result['symbol']}</b>\n"
        f"📈 جهت روند: <b>{direction_text}</b>\n"
        f"💵 قیمت مبنا: <code>{price_text(result['price'])}</code>\n"
        f"⭐ امتیاز تحلیلی: <b>{result['score']:.1f}/100</b>\n\n"
        "📊 <b>تأیید روند</b>\n"
        f"RSI 15m: <code>{result['rsi15']:.1f}</code>\n"
        f"RSI 1h: <code>{result['rsi1h']:.1f}</code>\n"
        f"EMA20 15m: <code>{price_text(result['ema20_15'])}</code>\n"
        f"EMA50 15m: <code>{price_text(result['ema50_15'])}</code>\n"
        f"EMA20 1h: <code>{price_text(result['ema20_1h'])}</code>\n"
        f"EMA50 1h: <code>{price_text(result['ema50_1h'])}</code>\n\n"
        "🧱 <b>حمایت و مقاومت</b>\n"
        f"حمایت: <code>{price_text(result['support'])}</code>\n"
        f"فاصله تا حمایت: {result['support_distance_pct']:.2f}٪\n"
        f"مقاومت: <code>{price_text(result['resistance'])}</code>\n"
        f"فاصله تا مقاومت: {result['resistance_distance_pct']:.2f}٪\n\n"
        "🎯 <b>اهداف قیمتی فرضی (TP)</b>\n"
        f"TP1: <code>{price_text(result['tp1'])}</code>\n"
        f"TP2: <code>{price_text(result['tp2'])}</code>\n"
        f"TP3: <code>{price_text(result['tp3'])}</code>\n\n"
        f"ℹ️ {target_note}\n"
        "اهداف تخمینی‌اند؛ ممکن است قیمت قبل از رسیدن به آن‌ها برگردد.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"منبع: {source}\n"
        f"بازارهای بررسی‌شده: {checked} | خطاها: {failures}\n"
        f"زمان: {now}\n\n"
        "🧪 <b>PAPER ANALYSIS ONLY</b>\n"
        "🚫 سفارش واقعی: خاموش"
    )


# -------------------- MAIN --------------------

def main():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in GitHub Secrets."
        )

    source, markets, candle_fetcher = load_markets()

    candidates = []
    failures = 0

    for market in markets:
        try:
            result = analyze_market(market, candle_fetcher)

            if result is not None:
                candidates.append(result)

        except Exception as exc:
            failures += 1
            logging.warning(
                "Analysis failed for %s: %s",
                market.get("symbol", "UNKNOWN"),
                exc
            )

        # کاهش فشار روی API عمومی
        time.sleep(0.15)

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    # انتخاب فقط یک گزینه؛ اگر مناسب نباشد، گزارش WAIT ارسال می‌شود.
    best = candidates[0] if candidates else None

    message = build_report(
        best,
        source,
        len(markets),
        failures
    )

    if not send_telegram(message):
        raise RuntimeError("Could not send the Telegram report.")

    logging.info(
        "Completed. Source=%s Markets=%s Candidates=%s Failures=%s",
        source,
        len(markets),
        len(candidates),
        failures
    )


if __name__ == "__main__":
    main()
