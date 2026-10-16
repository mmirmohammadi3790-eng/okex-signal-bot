
import os
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# ETH WHALE - CRYPTO MARKET TREND REPORT
# TREND REPORT ONLY | NO BUY/SELL SIGNALS | NO REAL ORDERS
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

TIMEFRAMES = ["15m", "1h", "4h"]
MAX_MARKETS = 25
CANDLE_LIMIT = 100
REQUEST_TIMEOUT = 20

HEADERS = {"User-Agent": "ETH-WHALE-TrendBot/1.0"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

session = requests.Session()
session.headers.update(HEADERS)


def get_json(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Telegram token or chat ID is missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = session.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True
            },
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            logging.error("Telegram API returned ok=false.")
            return False

        logging.info("Telegram message sent.")
        return True

    except Exception as exc:
        logging.error("Telegram error: %s", exc)
        return False


def excluded_symbol(symbol):
    excluded_suffixes = (
        "UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"
    )

    return (
        not symbol.endswith("USDT")
        or any(symbol.endswith(s) for s in excluded_suffixes)
    )


# ---------------- BINANCE MARKET DATA ----------------

def binance_markets():
    info = get_json(f"{BINANCE_BASE}/api/v3/exchangeInfo")
    valid = set()

    for item in info.get("symbols", []):
        symbol = item.get("symbol", "")

        if (
            item.get("status") == "TRADING"
            and item.get("quoteAsset") == "USDT"
            and item.get("isSpotTradingAllowed", True)
            and not excluded_symbol(symbol)
        ):
            valid.add(symbol)

    tickers = get_json(f"{BINANCE_BASE}/api/v3/ticker/24hr")
    ranked = []

    for item in tickers:
        symbol = item.get("symbol", "")

        if symbol not in valid:
            continue

        try:
            volume = float(item.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue

        if volume > 0:
            ranked.append((symbol, volume))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return [symbol for symbol, _ in ranked[:MAX_MARKETS]]


def binance_candles(symbol, timeframe, limit=CANDLE_LIMIT):
    # Binance requires values such as 15m, 1h and 4h.
    interval_map = {
        "15": "15m", "15m": "15m",
        "60": "1h", "1h": "1h",
        "240": "4h", "4h": "4h"
    }

    interval = interval_map.get(str(timeframe), str(timeframe))

    if interval not in ("15m", "1h", "4h"):
        raise ValueError(f"Invalid Binance interval: {timeframe}")

    data = get_json(
        f"{BINANCE_BASE}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not isinstance(data, list) or len(data) < 50:
        raise ValueError(f"Not enough Binance candles: {symbol}")

    return data


# ---------------- BYBIT FALLBACK DATA ----------------

def bybit_markets():
    data = get_json(
        f"{BYBIT_BASE}/v5/market/tickers",
        {"category": "spot"}
    )

    if data.get("retCode") != 0:
        raise ValueError(data.get("retMsg", "Bybit ticker error"))

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

    ranked.sort(key=lambda item: item[1], reverse=True)
    return [symbol for symbol, _ in ranked[:MAX_MARKETS]]


def bybit_candles(symbol, timeframe, limit=CANDLE_LIMIT):
    interval_map = {
        "15m": "15", "15": "15",
        "1h": "60", "60": "60",
        "4h": "240", "240": "240"
    }

    interval = interval_map.get(str(timeframe), str(timeframe))

    if interval not in ("15", "60", "240"):
        raise ValueError(f"Invalid Bybit interval: {timeframe}")

    data = get_json(
        f"{BYBIT_BASE}/v5/market/kline",
        {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if data.get("retCode") != 0:
        raise ValueError(data.get("retMsg", "Bybit kline error"))

    candles = data.get("result", {}).get("list", [])
    candles = list(reversed(candles))

    if len(candles) < 50:
        raise ValueError(f"Not enough Bybit candles: {symbol}")

    return candles


# ---------------- TECHNICAL INDICATORS ----------------

def extract_closes(candles):
    closes = []

    for candle in candles:
        try:
            closes.append(float(candle[4]))
        except (TypeError, ValueError, IndexError):
            continue

    if len(closes) < 50:
        raise ValueError("Not enough valid closing prices")

    return closes


def calculate_ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough values for EMA")

    ema = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for value in values[period:]:
        ema = value * multiplier + ema * (1 - multiplier)

    return ema


def calculate_rsi(values, period=14):
    if len(values) <= period:
        raise ValueError("Not enough values for RSI")

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
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


def analyze_candles(candles):
    closes = extract_closes(candles)

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes, 14)
    last_price = closes[-1]

    if ema20 > ema50 and last_price > ema20:
        trend = "صعودی"
    elif ema20 < ema50 and last_price < ema20:
        trend = "نزولی"
    else:
        trend = "خنثی / در حال نوسان"

    if rsi >= 70:
        rsi_status = "بالا؛ احتمال اشباع خرید"
    elif rsi <= 30:
        rsi_status = "پایین؛ احتمال اشباع فروش"
    else:
        rsi_status = "در محدوده میانی"

    return {
        "price": last_price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "trend": trend,
        "rsi_status": rsi_status
    }


# ---------------- REPORT CREATION ----------------

def analyze_market(symbol):
    results = []
    sources_used = set()

    for timeframe in TIMEFRAMES:
        analysis = None
        last_error = None

        # Try Binance first, then Bybit.
        for source in ("Binance", "Bybit"):
            try:
                if source == "Binance":
                    candles = binance_candles(symbol, timeframe)
                else:
                    candles = bybit_candles(symbol, timeframe)

                analysis = analyze_candles(candles)
                sources_used.add(source)
                break

            except Exception as exc:
                last_error = exc
                logging.warning(
                    "%s %s %s error: %s",
                    symbol, timeframe, source, exc
                )

        if analysis is None:
            results.append(
                f"  {timeframe}: داده دریافت نشد"
            )
            continue

        results.append(
            f"  ⏱ {timeframe}\n"
            f"  روند: {analysis['trend']}\n"
            f"  قیمت آخر: {analysis['price']:.8g}\n"
            f"  EMA20: {analysis['ema20']:.8g}\n"
            f"  EMA50: {analysis['ema50']:.8g}\n"
            f"  RSI14: {analysis['rsi']:.1f} "
            f"({analysis['rsi_status']})"
        )

    return results, sources_used


def build_report(markets):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"{BOT_NAME}",
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش روند بازار رمزارزها",
        "🧪 تحلیل اطلاعات بازار؛ بدون معامله",
        f"🕒 زمان: {now}",
        f"🔎 تعداد بازارها: {len(markets)}",
        "━━━━━━━━━━━━━━━━━━"
    ]

    sources = set()
    successful_markets = 0

    for symbol in markets:
        try:
            details, used_sources = analyze_market(symbol)
            sources.update(used_sources)

            if any("داده دریافت نشد" not in item for item in details):
                successful_markets += 1

            lines.append(f"\n💠 {symbol}")
            lines.extend(details)

        except Exception as exc:
            logging.warning("Market analysis failed for %s: %s", symbol, exc)
            lines.append(f"\n💠 {symbol}\n  خطا در تحلیل")

    lines.extend([
        "\n━━━━━━━━━━━━━━━━━━",
        f"✅ بازارهای دارای داده: {successful_markets}",
        "📚 منبع: " + (", ".join(sorted(sources)) if sources else "نامشخص"),
        "🚫 سفارش واقعی: غیرفعال",
        "ℹ️ این گزارش توصیه خرید یا فروش نیست."
    ])

    # Telegram messages have a practical text length limit.
    report = "\n".join(lines)
    max_length = 3800

    if len(report) <= max_length:
        return [report]

    chunks = []
    current = ""

    for line in lines:
        candidate = current + ("\n" if current else "") + line

        if len(candidate) > max_length:
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


# ---------------- MAIN ----------------

def main():
    logging.info("Starting %s", BOT_NAME)

    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "in GitHub repository Actions secrets."
        )

    try:
        markets = binance_markets()
        logging.info("Binance markets loaded: %d", len(markets))
    except Exception as exc:
        logging.warning("Binance market list failed: %s", exc)

        try:
            markets = bybit_markets()
            logging.info("Bybit fallback markets loaded: %d", len(markets))
        except Exception as fallback_exc:
            logging.exception("Both market sources failed.")
            send_telegram(
                f"{BOT_NAME}\n"
                "❌ دریافت فهرست بازارها ناموفق بود.\n"
                f"Binance: {str(exc)[:300]}\n"
                f"Bybit: {str(fallback_exc)[:300]}\n"
                "🧪 هیچ سفارش واقعی ثبت نشده است."
            )
            raise

    if not markets:
        raise RuntimeError("No eligible USDT spot markets found.")

    reports = build_report(markets)

    all_sent = True
    for report in reports:
        if not send_telegram(report):
            all_sent = False

    if not all_sent:
        raise RuntimeError("One or more Telegram messages failed.")

    logging.info("Trend report completed successfully.")


if __name__ == "__main__":
    main()
