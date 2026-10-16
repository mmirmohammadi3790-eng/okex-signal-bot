
import os
import time
import logging
from datetime import datetime, timezone

import requests

# ETH WHALE - TREND ONLY
# No real orders

BOT_NAME = "🐋 ETH WHALE"

BINANCE_BASE = "https://data-api.binance.vision"
BYBIT_BASE = "https://api.bybit.com"

MAX_MARKETS = 25
MIN_VOLUME_USDT = 2_000_000
CANDLE_LIMIT = 100

TIMEFRAMES = [
    ("15m", "15"),
    ("1h", "60"),
    ("4h", "240"),
]

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)

TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID", "").strip()
    or os.getenv("CHAT_ID", "").strip()
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

SESSION = requests.Session()


def get_json(url, params=None):
    last_error = None

    for attempt in range(3):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            return response.json()

        except Exception as exc:
            last_error = exc
            time.sleep(attempt + 1)

    raise RuntimeError(str(last_error))


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        logging.error("Telegram secrets missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    for start in range(0, len(message), 3800):
        response = SESSION.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[start:start + 3800],
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        response.raise_for_status()

        if not response.json().get("ok"):
            raise RuntimeError("Telegram send failed")

    return True


def excluded_symbol(symbol):
    if not symbol.endswith("USDT"):
        return True

    base = symbol[:-4]

    stablecoins = {
        "USDC", "FDUSD", "TUSD", "USDP",
        "DAI", "USDE", "USDD", "PYUSD",
        "BUSD", "USTC", "USDS", "USD1",
    }

    if base in stablecoins:
        return True

    return base.endswith(("UP", "DOWN", "BULL", "BEAR"))

def binance_markets():
    data = get_json(
        f"{BINANCE_BASE}/api/v3/ticker/24hr"
    )

    if not isinstance(data, list):
        raise RuntimeError("Invalid Binance ticker response")

    markets = []

    for item in data:
        symbol = item.get("symbol", "")

        if excluded_symbol(symbol):
            continue

        try:
            price = float(item["lastPrice"])
            volume = float(item["quoteVolume"])
            change = float(item["priceChangePercent"])
        except (ValueError, TypeError, KeyError):
            continue

        if price <= 0 or volume < MIN_VOLUME_USDT:
            continue

        markets.append({
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "change": change,
        })

    markets.sort(
        key=lambda item: item["volume"],
        reverse=True,
    )

    return markets[:MAX_MARKETS]


def binance_candles(symbol, interval):
    data = get_json(
        f"{BINANCE_BASE}/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": CANDLE_LIMIT,
        },
    )

    if not isinstance(data, list) or len(data) < 55:
        raise RuntimeError("Insufficient Binance candles")

    # Ignore the latest candle because it may be incomplete.
    return [float(row[4]) for row in data[:-1]]


def bybit_markets():
    data = get_json(
        f"{BYBIT_BASE}/v5/market/tickers",
        params={"category": "spot"},
    )

    if data.get("retCode") != 0:
        raise RuntimeError(
            data.get("retMsg", "Bybit ticker error")
        )

    markets = []

    for item in data.get("result", {}).get("list", []):
        symbol = item.get("symbol", "")

        if excluded_symbol(symbol):
            continue

        try:
            price = float(item["lastPrice"])
            volume = float(item["turnover24h"])
            change = float(item["price24hPcnt"]) * 100
        except (ValueError, TypeError, KeyError):
            continue

        if price <= 0 or volume < MIN_VOLUME_USDT:
            continue

        markets.append({
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "change": change,
        })

    markets.sort(
        key=lambda item: item["volume"],
        reverse=True,
    )

    return markets[:MAX_MARKETS]


def bybit_candles(symbol, interval):
    data = get_json(
        f"{BYBIT_BASE}/v5/market/kline",
        params={
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": CANDLE_LIMIT,
        },
    )

    if data.get("retCode") != 0:
        raise RuntimeError(
            data.get("retMsg", "Bybit candle error")
        )

    rows = data.get("result", {}).get("list", [])
    rows = list(reversed(rows))

    if len(rows) < 55:
        raise RuntimeError("Insufficient Bybit candles")

    # Exclude the latest potentially incomplete candle.
    return [float(row[4]) for row in rows[:-1]]

def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough data for EMA")

    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result

    return result


def rsi(values, period=14):
    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    if len(changes) < period:
        return 50.0

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
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def classify(closes):
    fast = ema(closes, 20)
    slow = ema(closes, 50)
    price = closes[-1]
    momentum = rsi(closes)

    if fast > slow and price > fast:
        if momentum >= 55:
            label, score = "🟢 صعودی", 2
        else:
            label, score = "🟡 صعود ضعیف", 1

    elif fast < slow and price < fast:
        if momentum <= 45:
            label, score = "🔴 نزولی", -2
        else:
            label, score = "🟡 نزول ضعیف", -1

    else:
        label, score = "🟡 خنثی", 0

    return {
        "label": label,
        "score": score,
        "rsi": momentum,
    }


def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"

    if price >= 1:
        return f"{price:.4f}".rstrip("0").rstrip(".")

    return f"{price:.8f}".rstrip("0").rstrip(".")


def analyze(markets, candle_function):
    results = []

    for market in markets:
        result = dict(market)
        result["trends"] = {}

        for timeframe, interval in TIMEFRAMES:
            try:
                closes = candle_function(
                    market["symbol"], interval
                )

                result["trends"][timeframe] = classify(closes)

            except Exception as exc:
                logging.warning(
                    "%s %s: %s",
                    market["symbol"], timeframe, exc
                )

            time.sleep(0.1)

        if result["trends"]:
            results.append(result)

    return results


def overall_trend(results):
    scores = [
        item["trends"]["1h"]["score"]
        for item in results
        if "1h" in item["trends"]
    ]

    if not scores:
        return "⚪ اطلاعات کافی برای تعیین روند وجود ندارد."

    bullish = sum(score > 0 for score in scores)
    bearish = sum(score < 0 for score in scores)
    neutral = len(scores) - bullish - bearish
    total = len(scores)

    if bullish / total >= 0.60:
        mood = "🟢 تمایل کلی بازار صعودی"
    elif bearish / total >= 0.60:
        mood = "🔴 تمایل کلی بازار نزولی"
    else:
        mood = "🟡 بازار ترکیبی یا خنثی"

    return (
        f"{mood}\n"
        f"🟢 صعودی: {bullish}/{total}\n"
        f"🔴 نزولی: {bearish}/{total}\n"
        f"🟡 خنثی: {neutral}/{total}"
    )


def build_report(results, source):
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش روند بازار کریپتو",
        "🧪 فقط تحلیل بازار؛ بدون معامله",
        f"📡 منبع: {source}",
        f"🕒 زمان: {now}",
        "━━━━━━━━━━━━━━━━━━",
        "🌐 وضعیت کلی بازار",
        overall_trend(results),
        "",
    ]

    btc = next(
        (x for x in results if x["symbol"] == "BTCUSDT"),
        None,
    )

    if btc:
        lines.extend([
            "₿ بیت‌کوین",
            f"💵 قیمت: {format_price(btc['price'])} USDT",
            f"📈 تغییر ۲۴ساعته: {btc['change']:+.2f}%",
        ])

        for timeframe, _ in TIMEFRAMES:
            trend = btc["trends"].get(timeframe)

            if trend:
                lines.append(
                    f"{timeframe}: {trend['label']} "
                    f"| RSI {trend['rsi']:.0f}"
                )

        lines.append("")

    hourly = [
        x for x in results if "1h" in x["trends"]
    ]

    bullish = sorted(
        [x for x in hourly if x["trends"]["1h"]["score"] > 0],
        key=lambda x: (
            x["trends"]["1h"]["score"],
            x["trends"].get("4h", {}).get("score", 0),
            x["change"],
        ),
        reverse=True,
    )

    bearish = sorted(
        [x for x in hourly if x["trends"]["1h"]["score"] < 0],
        key=lambda x: (
            x["trends"]["1h"]["score"],
            x["trends"].get("4h", {}).get("score", 0),
            x["change"],
        ),
    )

    lines.append("🟢 ارزهای دارای روند صعودی | ۱ساعته")

    if bullish:
        for item in bullish[:8]:
            lines.append(
                f"• {item['symbol']} | "
                f"{format_price(item['price'])} USDT | "
                f"۲۴ساعت {item['change']:+.2f}%"
            )

            trend4 = item["trends"].get("4h")

            if trend4:
                lines.append(f"  روند ۴ساعته: {trend4['label']}")
    else:
        lines.append("موردی شناسایی نشد.")

    lines.extend([
        "",
        "🔴 ارزهای دارای روند نزولی | ۱ساعته",
    ])

    if bearish:
        for item in bearish[:8]:
            lines.append(
                f"• {item['symbol']} | "
                f"{format_price(item['price'])} USDT | "
                f"۲۴ساعت {item['change']:+.2f}%"
            )

            trend4 = item["trends"].get("4h")

            if trend4:
                lines.append(f"  روند ۴ساعته: {trend4['label']}")
    else:
        lines.append("موردی شناسایی نشد.")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        "ℹ️ گزارش روند است، نه توصیه خرید یا فروش.",
        "🚫 سفارش واقعی: غیرفعال",
    ])

    return "\n".join(lines)


def main():
    try:
        markets = binance_markets()
        source = "Binance Public Data"
        candle_function = binance_candles

    except Exception as exc:
        logging.warning("Binance unavailable: %s", exc)

        try:
            markets = bybit_markets()
            source = "Bybit Public API (fallback)"
            candle_function = bybit_candles

        except Exception as fallback_exc:
            message = (
                f"{BOT_NAME}\n"
                "❌ دریافت اطلاعات بازار ناموفق بود.\n"
                f"Binance: {str(exc)[:200]}\n"
                f"Bybit: {str(fallback_exc)[:200]}\n"
                "هیچ روندی حدس زده نشده است."
            )

            send_telegram(message)
            raise RuntimeError(
                "Both market data sources failed"
            ) from fallback_exc

    if not markets:
        raise RuntimeError("No eligible USDT markets found")

    logging.info("Markets selected: %d", len(markets))

    results = analyze(markets, candle_function)

    if not results:
        message = (
            f"{BOT_NAME}\n"
            "❌ کندل کافی برای تحلیل دریافت نشد."
        )

        send_telegram(message)
        raise RuntimeError("No markets analyzed")

    report = build_report(results, source)
    send_telegram(report)

    logging.info(
        "Completed: %d markets analyzed",
        len(results),
    )


if __name__ == "__main__":
    main()
