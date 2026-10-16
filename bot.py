
import os
import time
import html
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# ETH WHALE | ONE BEST TREND + SUPPORT / RESISTANCE
# 15m + 1h confirmation | REPORT ONLY | NO REAL ORDERS
# ============================================================

BINANCE = "https://data-api.binance.vision"
BYBIT = "https://api.bybit.com"

MAX_MARKETS = 25
CANDLE_LIMIT = 100
TIMEOUT = 15
RETRIES = 2
TELEGRAM_LIMIT = 3500

STABLE_BASES = {
    "USDT", "USDC", "USD1", "USDE", "USDS", "FDUSD",
    "TUSD", "USDP", "DAI", "PYUSD", "RLUSD", "EURC",
    "EURI", "EUR", "USTC", "USDD", "FRAX", "LUSD",
    "BUSD", "GUSD", "USDK", "AEUR"
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ETH-WHALE/4.0"})

TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)
CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID", "").strip()
    or os.getenv("CHAT_ID", "").strip()
)


def request_json(url, params=None):
    last_error = None
    for attempt in range(RETRIES + 1):
        try:
            response = SESSION.get(
                url, params=params, timeout=TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            logging.warning("Request error: %s", exc)
            if attempt < RETRIES:
                time.sleep(attempt + 1)
    raise RuntimeError(str(last_error))


def is_excluded(symbol):
    if not symbol.endswith("USDT"):
        return True
    base = symbol[:-4]
    return (
        base in STABLE_BASES
        or any(base.endswith(s) for s in LEVERAGED_SUFFIXES)
    )


def get_markets():
    try:
        data = request_json(f"{BINANCE}/api/v3/ticker/24hr")
        markets = []

        for row in data:
            symbol = str(row.get("symbol", "")).upper()
            if is_excluded(symbol):
                continue
            try:
                volume = float(row.get("quoteVolume", 0))
                price = float(row.get("lastPrice", 0))
            except (ValueError, TypeError):
                continue
            if volume > 0 and price > 0:
                markets.append({
                    "symbol": symbol,
                    "volume": volume,
                    "price": price
                })

        markets.sort(key=lambda x: x["volume"], reverse=True)
        if markets:
            return markets[:MAX_MARKETS], "Binance"

    except Exception as exc:
        logging.warning("Binance market list failed: %s", exc)

    data = request_json(
        f"{BYBIT}/v5/market/tickers",
        {"category": "spot"}
    )
    if data.get("retCode") != 0:
        raise RuntimeError("Bybit ticker API error")

    markets = []
    for row in data.get("result", {}).get("list", []):
        symbol = str(row.get("symbol", "")).upper()
        if is_excluded(symbol):
            continue
        try:
            volume = float(row.get("turnover24h", 0))
            price = float(row.get("lastPrice", 0))
        except (ValueError, TypeError):
            continue
        if volume > 0 and price > 0:
            markets.append({
                "symbol": symbol,
                "volume": volume,
                "price": price
            })

    markets.sort(key=lambda x: x["volume"], reverse=True)
    if not markets:
        raise RuntimeError("No eligible USDT markets found")
    return markets[:MAX_MARKETS], "Bybit"


def binance_candles(symbol, interval):
    rows = request_json(
        f"{BINANCE}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": CANDLE_LIMIT
        }
    )

    # Ignore the last candle because it may still be open.
    if len(rows) > 1:
        rows = rows[:-1]

    candles = []
    for row in rows:
        try:
            candles.append({
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5])
            })
        except (ValueError, TypeError, IndexError):
            continue
    return candles


def bybit_candles(symbol, interval):
    interval_code = "15" if interval == "15m" else "60"
    duration_ms = 900000 if interval_code == "15" else 3600000

    data = request_json(
        f"{BYBIT}/v5/market/kline",
        {
            "category": "spot",
            "symbol": symbol,
            "interval": interval_code,
            "limit": CANDLE_LIMIT
        }
    )

    if data.get("retCode") != 0:
        raise RuntimeError(data.get("retMsg", "Bybit candle error"))

    rows = list(reversed(data.get("result", {}).get("list", [])))
    now_ms = int(time.time() * 1000)
    candles = []

    for row in rows:
        try:
            start = int(row[0])
            candle = {
                "time": start,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5])
            }
        except (ValueError, TypeError, IndexError):
            continue

        if start + duration_ms <= now_ms:
            candles.append(candle)

    return candles


def get_candles(symbol, interval):
    try:
        candles = binance_candles(symbol, interval)
        if len(candles) >= 55:
            return candles
    except Exception as exc:
        logging.warning(
            "Binance candles failed for %s %s: %s",
            symbol, interval, exc
        )

    candles = bybit_candles(symbol, interval)
    if len(candles) < 55:
        raise RuntimeError("Not enough closed candles")
    return candles


def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough data for EMA")

    value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        value = price * multiplier + value * (1 - multiplier)

    return value


def calc_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]
    recent = changes[-period:]
    gains = [max(x, 0) for x in recent]
    losses = [abs(min(x, 0)) for x in recent]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze(candles):
    closes = [c["close"] for c in candles]

    if len(closes) < 52:
        raise RuntimeError("Insufficient closed candles")

    fast = ema(closes, 20)
    slow = ema(closes, 50)
    price = closes[-1]
    rsi_value = calc_rsi(closes)

    if fast > slow and price > fast:
        key, label = "up", "صعودی"
    elif fast < slow and price < fast:
        key, label = "down", "نزولی"
    else:
        key, label = "neutral", "خنثی"

    return {
        "key": key,
        "label": label,
        "price": price,
        "ema20": fast,
        "ema50": slow,
        "rsi": rsi_value
    }


def support_resistance(candles, price):
    """
    Find recent local swing lows/highs on closed 15m candles.
    Support must be below price; resistance must be above price.
    """
    recent = candles[-49:-1] if len(candles) > 50 else candles[:-1]
    supports = []
    resistances = []

    for i in range(2, len(recent) - 2):
        low = recent[i]["low"]
        high = recent[i]["high"]

        neighbors = recent[i - 2:i] + recent[i + 1:i + 3]

        if all(low <= x["low"] for x in neighbors):
            if low < price:
                supports.append(low)

        if all(high >= x["high"] for x in neighbors):
            if high > price:
                resistances.append(high)

    support = max(supports) if supports else None
    resistance = min(resistances) if resistances else None

    # Fallback to recent candle extremes if no swing level is found.
    if support is None:
        lows = [c["low"] for c in recent if c["low"] < price]
        support = max(lows) if lows else None

    if resistance is None:
        highs = [c["high"] for c in recent if c["high"] > price]
        resistance = min(highs) if highs else None

    return support, resistance


def distance_percent(price, level):
    if level is None or price <= 0:
        return None
    return abs(price - level) / price * 100


def fmt_price(value):
    if value is None:
        return "یافت نشد"
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.5f}"
    return f"{value:.8f}"


def fmt_rsi(value):
    return "N/A" if value is None else f"{value:.1f}"


def fmt_distance(price, level):
    if level is None:
        return "محاسبه نشد"
    amount = abs(price - level)
    pct = distance_percent(price, level)
    return f"{fmt_price(amount)} USDT  ({pct:.2f}٪)"


def evaluate_market(market):
    symbol = market["symbol"]
    candles15 = get_candles(symbol, "15m")
    candles1h = get_candles(symbol, "1h")

    a15 = analyze(candles15)
    a1h = analyze(candles1h)

    # Only aligned 15m and 1h trends qualify for selection.
    if a15["key"] == "up" and a1h["key"] == "up":
        direction = "up"
        label = "هم‌جهت صعودی"
    elif a15["key"] == "down" and a1h["key"] == "down":
        direction = "down"
        label = "هم‌جهت نزولی"
    else:
        return None

    # Avoid selecting an extreme RSI reading as the best candidate.
    rsi15 = a15["rsi"]
    rsi1h = a1h["rsi"]

    if rsi15 is None or rsi1h is None:
        return None

    if direction == "up":
        if not (42 <= rsi15 <= 68 and 35 <= rsi1h <= 72):
            return None
    else:
        if not (32 <= rsi15 <= 58 and 25 <= rsi1h <= 65):
            return None

    price = a15["price"]
    support, resistance = support_resistance(candles15, price)

    support_gap = distance_percent(price, support)
    resistance_gap = distance_percent(price, resistance)

    # Skip incomplete levels rather than inventing support/resistance.
    if support is None or resistance is None:
        return None

    # Require some room to the nearest level; this is a filter,
    # not a guarantee that price will respect the level.
    if direction == "up" and resistance_gap < 0.15:
        return None
    if direction == "down" and support_gap < 0.15:
        return None

    # Rank eligible markets by 24h quote volume and RSI moderation.
    rsi_center = 55 if direction == "up" else 45
    rsi_penalty = abs(rsi15 - rsi_center) + abs(rsi1h - rsi_center) * 0.5
    score = max(0, 100 - rsi_penalty)

    return {
        "symbol": symbol,
        "direction": direction,
        "label": label,
        "price": price,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "ema20": a15["ema20"],
        "ema50": a15["ema50"],
        "support": support,
        "resistance": resistance,
        "support_gap": support_gap,
        "resistance_gap": resistance_gap,
        "volume": market["volume"],
        "score": score
    }


def build_report(best, checked, failed, source):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    header = (
        "🐋 <b>ETH WHALE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>ارز منتخب بر اساس روند</b>\n"
        "⏱ تایم اصلی: ۱۵ دقیقه\n"
        "🕐 تأیید: یک‌ساعته\n"
        "📐 EMA20 / EMA50 / RSI14\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <code>{now}</code>\n"
        f"📡 منبع بازار: <b>{html.escape(source)}</b>\n"
        f"🔎 بررسی‌شده: <b>{checked}</b> | خطا: <b>{failed}</b>\n"
        "🚫 بدون سفارش واقعی\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if best is None:
        return (
            header
            + "\n⚪ <b>مورد مناسبی پیدا نشد</b>\n"
            "هیچ ارزی تمام شروط روند، RSI و سطوح معتبر را نداشت.\n"
            "برای جلوگیری از انتخاب اجباری، موردی نمایش داده نشد.\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ℹ️ این ابزار گزارش تحلیلی است، نه تضمین سود."
        )

    icon = "🟢" if best["direction"] == "up" else "🔴"
    direction_text = "روند صعودی" if best["direction"] == "up" else "روند نزولی"

    return (
        header
        + f"{icon} <b>{html.escape(best['symbol'])}</b>\n"
        + f"📌 وضعیت: <b>{direction_text}</b>\n"
        + f"🤝 تأیید دو تایم‌فریم: <b>{best['label']}</b>\n"
        + f"💵 قیمت آخرین کندل بسته‌شده: <code>{fmt_price(best['price'])}</code>\n"
        + "━━━━━━━━━━━━━━━━━━\n"
        + "⏱ <b>تایم‌فریم ۱۵ دقیقه</b>\n"
        + f"• RSI14: <code>{fmt_rsi(best['rsi15'])}</code>\n"
        + f"• EMA20: <code>{fmt_price(best['ema20'])}</code>\n"
        + f"• EMA50: <code>{fmt_price(best['ema50'])}</code>\n"
        + "🕐 <b>تأیید یک‌ساعته</b>\n"
        + f"• RSI14: <code>{fmt_rsi(best['rsi1h'])}</code>\n"
        + "━━━━━━━━━━━━━━━━━━\n"
        + "🛡 <b>حمایت نزدیک</b>\n"
        + f"• سطح: <code>{fmt_price(best['support'])}</code>\n"
        + f"• فاصله از قیمت: <code>{fmt_distance(best['price'], best['support'])}</code>\n"
        + "🧱 <b>مقاومت نزدیک</b>\n"
        + f"• سطح: <code>{fmt_price(best['resistance'])}</code>\n"
        + f"• فاصله از قیمت: <code>{fmt_distance(best['price'], best['resistance'])}</code>\n"
        + "━━━━━━━━━━━━━━━━━━\n"
        + "ℹ️ حمایت و مقاومت از نوسان‌های اخیر ۱۵ دقیقه محاسبه شده‌اند.\n"
        + "⚠️ انتخاب روند به‌معنی تضمین ادامه حرکت نیست.\n"
        + "🚫 این گزارش دستور ورود یا سفارش معاملاتی نیست."
    )


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Telegram secrets missing: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )

    response = SESSION.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=TIMEOUT
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram send failed: {result}")


def main():
    markets, source = get_markets()
    candidates = []
    failed = 0

    for index, market in enumerate(markets, 1):
        print(f"[{index}/{len(markets)}] {market['symbol']}")
        try:
            result = evaluate_market(market)
            if result is not None:
                candidates.append(result)
        except Exception as exc:
            failed += 1
            logging.warning("%s failed: %s", market["symbol"], exc)
        time.sleep(0.12)

    # Prefer moderate RSI; use liquidity as the tie-breaker.
    candidates.sort(
        key=lambda x: (x["score"], x["volume"]),
        reverse=True
    )
    best = candidates[0] if candidates else None

    report = build_report(
        best=best,
        checked=len(markets),
        failed=failed,
        source=source
    )

    print(report)
    send_telegram(report)
    print("Telegram report sent.")


if __name__ == "__main__":
    main()
