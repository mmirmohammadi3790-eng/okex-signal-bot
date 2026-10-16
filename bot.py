
import os
import time
import logging
from datetime import datetime, timezone

import requests

# ============================================================
# ETH WHALE | CRYPTO TREND MONITOR
# 15m trend + 1h confirmation
# REPORT ONLY - NO BUY/SELL SIGNALS - NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"

BINANCE_BASE = "https://data-api.binance.vision"
BYBIT_BASE = "https://api.bybit.com"

TIMEFRAME_MAIN = "15m"
TIMEFRAME_CONFIRM = "1h"

EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14

MAX_MARKETS = 25
CANDLE_LIMIT = 100
REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
TELEGRAM_CHUNK_SIZE = 3500

# Stablecoins excluded from trend ranking.
STABLE_BASES = {
    "USDT", "USDC", "USD1", "USDE", "USDS",
    "FDUSD", "TUSD", "USDP", "DAI", "PYUSD",
    "RLUSD", "EURC", "EURI", "EUR", "USTC",
    "USDD", "FRAX", "LUSD", "USDX", "USDXL",
    "BUSD", "GUSD", "USDK", "AEUR"
}

LEVERAGED_SUFFIXES = (
    "UP", "DOWN", "BULL", "BEAR"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Trend-Monitor/2.0"
})


def get_env(*names):
    """Return the first non-empty environment variable."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


TELEGRAM_TOKEN = get_env(
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_TOKEN"
)

CHAT_ID = get_env(
    "TELEGRAM_CHAT_ID",
    "CHAT_ID"
)


def http_json(url, params=None):
    """HTTP GET with retries and JSON validation."""
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response.json()

        except Exception as exc:
            last_error = exc
            logging.warning(
                "Request failed (%s/%s): %s | %s",
                attempt + 1,
                MAX_RETRIES + 1,
                url,
                exc
            )
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(str(last_error))


def is_excluded_symbol(symbol):
    """Exclude stablecoin bases and leveraged tokens."""
    if not symbol.endswith("USDT"):
        return True

    base = symbol[:-4]

    if base in STABLE_BASES:
        return True

    if any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
        return True

    return False


def get_binance_markets():
    url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
    data = http_json(url)

    if not isinstance(data, list):
        raise RuntimeError("Unexpected Binance ticker response")

    markets = []

    for item in data:
        symbol = str(item.get("symbol", "")).upper()

        if not symbol.endswith("USDT"):
            continue

        if is_excluded_symbol(symbol):
            continue

        try:
            quote_volume = float(item.get("quoteVolume", 0))
            last_price = float(item.get("lastPrice", 0))
        except (TypeError, ValueError):
            continue

        if quote_volume <= 0 or last_price <= 0:
            continue

        markets.append({
            "symbol": symbol,
            "quote_volume": quote_volume,
            "price": last_price,
            "source": "Binance"
        })

    markets.sort(
        key=lambda item: item["quote_volume"],
        reverse=True
    )

    return markets[:MAX_MARKETS]


def get_bybit_markets():
    url = f"{BYBIT_BASE}/v5/market/tickers"

    data = http_json(url, {
        "category": "spot"
    })

    if data.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit ticker error: {data.get('retMsg')}"
        )

    result = data.get("result", {}).get("list", [])
    markets = []

    for item in result:
        symbol = str(item.get("symbol", "")).upper()

        if not symbol.endswith("USDT"):
            continue

        if is_excluded_symbol(symbol):
            continue

        try:
            quote_volume = float(item.get("turnover24h", 0))
            last_price = float(item.get("lastPrice", 0))
        except (TypeError, ValueError):
            continue

        if quote_volume <= 0 or last_price <= 0:
            continue

        markets.append({
            "symbol": symbol,
            "quote_volume": quote_volume,
            "price": last_price,
            "source": "Bybit"
        })

    markets.sort(
        key=lambda item: item["quote_volume"],
        reverse=True
    )

    return markets[:MAX_MARKETS]


def get_markets():
    try:
        markets = get_binance_markets()
        if markets:
            logging.info(
                "Loaded %s markets from Binance",
                len(markets)
            )
            return markets, "Binance"

    except Exception as exc:
        logging.warning("Binance market list failed: %s", exc)

    markets = get_bybit_markets()

    if not markets:
        raise RuntimeError("No eligible USDT markets found")

    logging.info(
        "Loaded %s markets from Bybit",
        len(markets)
    )

    return markets, "Bybit"


def get_binance_closes(symbol, interval):
    url = f"{BINANCE_BASE}/api/v3/klines"

    data = http_json(url, {
        "symbol": symbol,
        "interval": interval,
        "limit": CANDLE_LIMIT
    })

    if not isinstance(data, list):
        raise RuntimeError("Unexpected Binance candle response")

    # Drop the latest candle because it may still be forming.
    if len(data) > 1:
        data = data[:-1]

    closes = []

    for candle in data:
        try:
            closes.append(float(candle[4]))
        except (TypeError, ValueError, IndexError):
            continue

    return closes


def get_bybit_closes(symbol, interval):
    url = f"{BYBIT_BASE}/v5/market/kline"

    data = http_json(url, {
        "category": "spot",
        "symbol": symbol,
        "interval": interval,
        "limit": CANDLE_LIMIT
    })

    if data.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit candle error: {data.get('retMsg')}"
        )

    candles = data.get("result", {}).get("list", [])

    # Bybit returns newest candle first.
    candles = list(reversed(candles))

    interval_ms = (
        15 * 60 * 1000 if interval == "15"
        else 60 * 60 * 1000
    )

    now_ms = int(time.time() * 1000)
    closes = []

    for candle in candles:
        try:
            start_ms = int(candle[0])
            close_price = float(candle[4])
        except (TypeError, ValueError, IndexError):
            continue

        # Only use candles that have fully closed.
        if start_ms + interval_ms <= now_ms:
            closes.append(close_price)

    return closes


def get_closes(symbol, interval):
    """Try Binance first, then Bybit."""
    try:
        closes = get_binance_closes(symbol, interval)
        if len(closes) >= EMA_SLOW + 2:
            return closes, "Binance"
    except Exception as exc:
        logging.debug(
            "Binance candles failed for %s %s: %s",
            symbol, interval, exc
        )

    bybit_interval = "15" if interval == "15m" else "60"
    closes = get_bybit_closes(symbol, bybit_interval)

    if len(closes) < EMA_SLOW + 2:
        raise RuntimeError(
            f"Not enough closed candles: {len(closes)}"
        )

    return closes, "Bybit"


def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough values for EMA")

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = (
            value * multiplier
            + result * (1 - multiplier)
        )

    return result


def rsi(values, period=RSI_PERIOD):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    recent = changes[-period:]
    gains = [max(change, 0) for change in recent]
    losses = [abs(min(change, 0)) for change in recent]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze(closes):
    if len(closes) < EMA_SLOW + 2:
        raise ValueError("Insufficient candles")

    fast_ema = ema(closes, EMA_FAST)
    slow_ema = ema(closes, EMA_SLOW)
    last_price = closes[-1]
    rsi_value = rsi(closes)

    if fast_ema > slow_ema and last_price > fast_ema:
        trend = "صعودی"
        trend_key = "up"

    elif fast_ema < slow_ema and last_price < fast_ema:
        trend = "نزولی"
        trend_key = "down"

    else:
        trend = "نامشخص"
        trend_key = "neutral"

    return {
        "trend": trend,
        "key": trend_key,
        "price": last_price,
        "ema20": fast_ema,
        "ema50": slow_ema,
        "rsi": rsi_value
    }


def analyze_market(market):
    symbol = market["symbol"]

    closes_15m, source_15m = get_closes(
        symbol, TIMEFRAME_MAIN
    )
    closes_1h, source_1h = get_closes(
        symbol, TIMEFRAME_CONFIRM
    )

    result_15m = analyze(closes_15m)
    result_1h = analyze(closes_1h)

    key_15m = result_15m["key"]
    key_1h = result_1h["key"]

    if key_15m == "up" and key_1h == "up":
        alignment = "هم‌جهت صعودی"
        group = 0

    elif key_15m == "down" and key_1h == "down":
        alignment = "هم‌جهت نزولی"
        group = 1

    elif key_15m == "neutral" or key_1h == "neutral":
        alignment = "نامشخص / خنثی"
        group = 3

    else:
        alignment = "ناهم‌جهت"
        group = 2

    return {
        "symbol": symbol,
        "price": result_15m["price"],
        "trend_15m": result_15m["trend"],
        "key_15m": key_15m,
        "rsi_15m": result_15m["rsi"],
        "trend_1h": result_1h["trend"],
        "key_1h": key_1h,
        "rsi_1h": result_1h["rsi"],
        "alignment": alignment,
        "group": group,
        "source": f"{source_15m}/{source_1h}"
    }


def format_price(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.5f}"
    return f"{value:.8f}"


def format_rsi(value):
    return f"{value:.1f}" if value is not None else "N/A"


def format_market(item):
    return (
        f"• {item['symbol']}\n"
        f"  15m: {item['trend_15m']} | "
        f"RSI {format_rsi(item['rsi_15m'])}\n"
        f"  1h: {item['trend_1h']} | "
        f"RSI {format_rsi(item['rsi_1h'])}\n"
        f"  وضعیت: {item['alignment']}\n"
        f"  قیمت: {format_price(item['price'])}"
    )


def build_report(results, failed, source):
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    results.sort(
        key=lambda item: (
            item["group"],
            -item["price"]
        )
    )

    bullish = [
        item for item in results
        if item["group"] == 0
    ]
    bearish = [
        item for item in results
        if item["group"] == 1
    ]
    mixed = [
        item for item in results
        if item["group"] == 2
    ]
    neutral = [
        item for item in results
        if item["group"] == 3
    ]

    lines = [
        "🐋 ETH WHALE",
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش روند بازار",
        "⏱ تایم اصلی: ۱۵ دقیقه",
        "🕐 تأیید روند: ۱ ساعت",
        "🧪 تحلیل بازار؛ بدون معامله",
        "🚫 سفارش واقعی: غیرفعال",
        "━━━━━━━━━━━━━━━━━━",
        f"🕒 زمان: {now}",
        f"📡 منبع فهرست بازار: {source}",
        f"🔎 بررسی‌شده: {len(results)}",
        f"⚠️ ناموفق: {failed}",
        "",
        f"🟢 هم‌جهت صعودی ({len(bullish)})"
    ]

    if bullish:
        lines.extend(format_market(x) for x in bullish)
    else:
        lines.append("موردی یافت نشد.")

    lines += [
        "",
        f"🔴 هم‌جهت نزولی ({len(bearish)})"
    ]

    if bearish:
        lines.extend(format_market(x) for x in bearish)
    else:
        lines.append("موردی یافت نشد.")

    lines += [
        "",
        f"🟡 ناهم‌جهت ({len(mixed)})"
    ]

    if mixed:
        lines.extend(format_market(x) for x in mixed)
    else:
        lines.append("موردی یافت نشد.")

    lines += [
        "",
        f"⚪ خنثی / نامشخص ({len(neutral)})"
    ]

    if neutral:
        lines.extend(format_market(x) for x in neutral)
    else:
        lines.append("موردی یافت نشد.")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📌 EMA20 / EMA50 / RSI14",
        "ℹ️ گزارش وضعیت فعلی است، نه پیش‌بینی قطعی.",
        "🚫 هیچ سیگنال خرید/فروش یا سفارشی صادر نشده است."
    ]

    return "\n".join(lines)


def split_message(text, limit=TELEGRAM_CHUNK_SIZE):
    chunks = []
    current = ""

    for line in text.splitlines():
        candidate = line if not current else current + "\n" + line

        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Telegram credentials missing. Configure "
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "in GitHub Actions secrets."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    for chunk in split_message(message):
        response = SESSION.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True
            },
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                f"Telegram send failed: {data}"
            )


def main():
    print("=" * 55)
    print(BOT_NAME)
    print("15m Trend + 1h Confirmation")
    print("REPORT ONLY | NO ORDERS")
    print("=" * 55)

    try:
        markets, source = get_markets()
    except Exception as exc:
        error_text = (
            f"🐋 {BOT_NAME}\n"
            "❌ دریافت فهرست بازارها ناموفق بود.\n"
            f"علت: {exc}\n"
            "🚫 هیچ سفارشی ثبت نشده است."
        )
        print(error_text)

        if TELEGRAM_TOKEN and CHAT_ID:
            try:
                send_telegram(error_text)
            except Exception as telegram_error:
                logging.error(
                    "Telegram error notification failed: %s",
                    telegram_error
                )
        raise

    results = []
    failed = 0

    for index, market in enumerate(markets, start=1):
        symbol = market["symbol"]

        print(
            f"[{index}/{len(markets)}] Analyzing {symbol}"
        )

        try:
            result = analyze_market(market)
            results.append(result)

        except Exception as exc:
            failed += 1
            logging.warning(
                "Market analysis failed for %s: %s",
                symbol,
                exc
            )

        time.sleep(0.12)

    report = build_report(results, failed, source)

    print(report)

    if not results:
        raise RuntimeError(
            "All market analyses failed; no report sent."
        )

    send_telegram(report)
    print("Telegram report sent successfully.")


if __name__ == "__main__":
    main()
