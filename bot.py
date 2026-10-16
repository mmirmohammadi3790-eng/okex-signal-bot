
import os
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# 🐋 ETH WHALE - 15M TREND MONITOR
# 15m MAIN TREND + 1h CONFIRMATION
# REPORT ONLY - NO TRADING - NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
BINANCE_BASE = "https://data-api.binance.vision"
BYBIT_BASE = "https://api.bybit.com"

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN", "")
).strip()

CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID", "")
).strip()

MAX_MARKETS = 25
CANDLE_LIMIT = 100
TIMEFRAMES = ("15m", "1h")
TIMEOUT = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

session = requests.Session()
session.headers.update({"User-Agent": "ETH-WHALE-TrendBot/2.0"})


def get_json(url, params=None):
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = session.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True
        },
        timeout=TIMEOUT
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram API did not accept the message")


def excluded_symbol(symbol):
    suffixes = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
    return (
        not symbol.endswith("USDT")
        or any(symbol.endswith(s) for s in suffixes)
    )


# ---------------- MARKET LIST ----------------

def binance_markets():
    info = get_json(f"{BINANCE_BASE}/api/v3/exchangeInfo")
    allowed = set()

    for item in info.get("symbols", []):
        symbol = item.get("symbol", "")
        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("isSpotTradingAllowed", True)
            and not excluded_symbol(symbol)
        ):
            allowed.add(symbol)

    tickers = get_json(f"{BINANCE_BASE}/api/v3/ticker/24hr")
    ranked = []

    for item in tickers:
        symbol = item.get("symbol", "")
        if symbol not in allowed:
            continue
        try:
            volume = float(item.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        if volume > 0:
            ranked.append((symbol, volume))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return [symbol for symbol, _ in ranked[:MAX_MARKETS]]


def bybit_markets():
    data = get_json(
        f"{BYBIT_BASE}/v5/market/tickers",
        {"category": "spot"}
    )

    if data.get("retCode") != 0:
        raise RuntimeError(data.get("retMsg", "Bybit ticker error"))

    ranked = []
    for item in data.get("result", {}).get("list", []):
        symbol = item.get("symbol", "")
        if excluded_symbol(symbol):
            continue
        try:
            volume = float(item.get("turnover24h", 0))
        except (TypeError, ValueError):
            continue
        if volume > 0:
            ranked.append((symbol, volume))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return [symbol for symbol, _ in ranked[:MAX_MARKETS]]


# ---------------- CANDLES ----------------

def binance_candles(symbol, timeframe):
    interval_map = {
        "15m": "15m",
        "1h": "1h"
    }
    interval = interval_map[timeframe]

    data = get_json(
        f"{BINANCE_BASE}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": CANDLE_LIMIT
        }
    )

    if not isinstance(data, list) or len(data) < 55:
        raise ValueError("Insufficient Binance candle data")

    # Remove the currently forming candle when possible.
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    closed = [c for c in data if int(c[6]) < now_ms]

    if len(closed) < 55:
        raise ValueError("Insufficient closed Binance candles")

    return closed


def bybit_candles(symbol, timeframe):
    interval = {"15m": "15", "1h": "60"}[timeframe]

    data = get_json(
        f"{BYBIT_BASE}/v5/market/kline",
        {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": CANDLE_LIMIT
        }
    )

    if data.get("retCode") != 0:
        raise RuntimeError(data.get("retMsg", "Bybit kline error"))

    candles = list(reversed(data.get("result", {}).get("list", [])))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    duration_ms = {"15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000}[timeframe]

    closed = []
    for candle in candles:
        try:
            start_ms = int(candle[0])
            if start_ms + duration_ms <= now_ms:
                closed.append(candle)
        except (TypeError, ValueError, IndexError):
            continue

    if len(closed) < 55:
        raise ValueError("Insufficient closed Bybit candles")

    return closed


def get_candles(symbol, timeframe):
    errors = []

    try:
        return binance_candles(symbol, timeframe), "Binance"
    except Exception as exc:
        errors.append(f"Binance: {exc}")
        logging.warning("%s %s Binance failed: %s", symbol, timeframe, exc)

    try:
        return bybit_candles(symbol, timeframe), "Bybit"
    except Exception as exc:
        errors.append(f"Bybit: {exc}")
        logging.warning("%s %s Bybit failed: %s", symbol, timeframe, exc)

    raise RuntimeError(" | ".join(errors))


# ---------------- INDICATORS ----------------

def closes_from(candles):
    closes = [float(candle[4]) for candle in candles]
    if len(closes) < 55:
        raise ValueError("Not enough closing prices")
    return closes


def ema(values, period):
    result = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for value in values[period:]:
        result = value * multiplier + result * (1 - multiplier)

    return result


def rsi(values, period=14):
    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]
    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def analyze(candles):
    values = closes_from(candles)
    price = values[-1]
    ema20 = ema(values, 20)
    ema50 = ema(values, 50)
    rsi14 = rsi(values)

    if ema20 > ema50 and price > ema20:
        trend = "صعودی"
    elif ema20 < ema50 and price < ema20:
        trend = "نزولی"
    else:
        trend = "خنثی"

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "trend": trend
    }


# ---------------- TREND REPORT ----------------

def analyze_symbol(symbol):
    output = {}
    sources = set()

    for timeframe in TIMEFRAMES:
        candles, source = get_candles(symbol, timeframe)
        output[timeframe] = analyze(candles)
        sources.add(source)

    trend15 = output["15m"]["trend"]
    trend1h = output["1h"]["trend"]

    if trend15 == "صعودی" and trend1h == "صعودی":
        alignment = "هم‌جهت صعودی"
    elif trend15 == "نزولی" and trend1h == "نزولی":
        alignment = "هم‌جهت نزولی"
    elif trend15 == "خنثی" or trend1h == "خنثی":
        alignment = "تأیید ناقص"
    else:
        alignment = "ناهم‌جهت"

    return output, alignment, sources


def build_reports(markets):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    records = []
    all_sources = set()
    failures = 0

    for symbol in markets:
        try:
            data, alignment, sources = analyze_symbol(symbol)
            all_sources.update(sources)
            records.append({
                "symbol": symbol,
                "data": data,
                "alignment": alignment
            })
        except Exception as exc:
            failures += 1
            logging.warning("Analysis failed for %s: %s", symbol, exc)

    # Group by alignment, without generating trade recommendations.
    order = {
        "هم‌جهت صعودی": 0,
        "هم‌جهت نزولی": 1,
        "ناهم‌جهت": 2,
        "تأیید ناقص": 3
    }
    records.sort(key=lambda r: order.get(r["alignment"], 4))

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش روند برای تایم‌فریم ۱۵ دقیقه",
        "🕐 تأیید روند: ۱ ساعت",
        f"🗓 {now}",
        "🧪 فقط پایش بازار؛ بدون معامله",
        "━━━━━━━━━━━━━━━━━━"
    ]

    for record in records:
        symbol = record["symbol"]
        data = record["data"]
        short = data["15m"]
        hourly = data["1h"]

        lines.extend([
            "",
            f"💠 {symbol}",
            f"۱۵ دقیقه: {short['trend']}",
            f"۱ ساعت: {hourly['trend']}",
            f"وضعیت کلی: {record['alignment']}",
            f"RSI 15m: {short['rsi']:.1f}",
            f"RSI 1h: {hourly['rsi']:.1f}"
        ])

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"📈 بازارهای تحلیل‌شده: {len(records)}",
        f"⚠️ بازارهای ناموفق: {failures}",
        "📚 منابع: " + (
            ", ".join(sorted(all_sources)) if all_sources else "نامشخص"
        ),
        "🚫 خریدوفروش و سفارش واقعی: غیرفعال",
        "ℹ️ گزارش روند است، نه توصیه معاملاتی."
    ])

    # Split into Telegram-safe message sizes.
    chunks = []
    current = ""

    for line in lines:
        candidate = current + ("\n" if current else "") + line
        if len(candidate) > 3800:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)

    total = len(chunks)
    return [
        f"📄 بخش {i + 1}/{total}\n{chunk}"
        for i, chunk in enumerate(chunks)
    ]


def main():
    logging.info("Starting ETH WHALE 15m trend monitor")

    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in GitHub Secrets"
        )

    try:
        markets = binance_markets()
        logging.info("Loaded %d markets from Binance", len(markets))
    except Exception as exc:
        logging.warning("Binance market list failed: %s", exc)
        markets = bybit_markets()
        logging.info("Loaded %d markets from Bybit", len(markets))

    if not markets:
        raise RuntimeError("No USDT spot markets found")

    for report in build_reports(markets):
        send_telegram(report)

    logging.info("Trend report finished")


if __name__ == "__main__":
    main()
