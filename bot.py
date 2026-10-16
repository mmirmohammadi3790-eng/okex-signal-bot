
import os
import time
import html
import logging
from datetime import datetime, timezone

import requests

# ============================================================
# ETH WHALE - BITPIN SMART MARKET WATCH
# PAPER SIGNALS ONLY - NO REAL ORDERS
#
# Bitpin: market list and current prices
# Binance public API: 15m and 1h OHLCV candles
# ============================================================

BITPIN_BASE = "https://api.bitpin.org"
BINANCE_BASE = "https://api.binance.com"
TELEGRAM_API = "https://api.telegram.org"

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

PAPER_MODE = True
REAL_ORDERS_ENABLED = False

CAPITAL_USDT = 48.0
LEVERAGE = 3
POSITION_VALUE = CAPITAL_USDT * LEVERAGE

MAX_MARKETS = 30
MAX_SIGNALS = 5
MIN_SCORE = 60
STRONG_SCORE = 75
CANDLE_LIMIT = 100

EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14

REQUEST_TIMEOUT = 15
REQUEST_PAUSE = 0.15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("eth-whale")

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/2.0",
    "Accept": "application/json",
})


# ============================================================
# HTTP
# ============================================================

def get_json(url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        log.warning(
            "GET failed | %s | params=%s | %s",
            url, params, exc
        )
        return None


def telegram_send(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.warning("Telegram token/chat ID missing.")
        return False

    url = f"{TELEGRAM_API}/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = session.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            log.error("Telegram API error: %s", result)
            return False

        log.info("Telegram message sent.")
        return True

    except Exception as exc:
        log.error("Telegram error: %s", exc)
        return False


def unwrap_list(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "results", "data", "markets",
            "items", "list",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in (
                    "results", "items", "list"
                ):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return nested

    return []


# ============================================================
# BITPIN MARKETS AND TICKERS
# ============================================================

def get_first_list(endpoints):
    for endpoint in endpoints:
        data = get_json(BITPIN_BASE + endpoint)
        rows = unwrap_list(data)

        if rows:
            log.info(
                "Bitpin endpoint OK: %s | rows=%d",
                endpoint, len(rows)
            )
            return rows

    return []


def get_markets():
    return get_first_list([
        "/v1/mkt/markets/",
        "/api/v1/mkt/markets/",
    ])


def get_tickers():
    endpoints = [
        "/v1/mkt/tickers/",
        "/api/v1/mkt/tickers/",
    ]

    for endpoint in endpoints:
        data = get_json(BITPIN_BASE + endpoint)

        if isinstance(data, dict):
            tickers = data.get("tickers")

            if isinstance(tickers, dict):
                log.info(
                    "Bitpin tickers OK: %d",
                    len(tickers)
                )
                return tickers

            if isinstance(tickers, list):
                return tickers

        rows = unwrap_list(data)
        if rows:
            return rows

    return []


def normalize_symbol(value):
    if isinstance(value, dict):
        value = (
            value.get("code")
            or value.get("symbol")
            or value.get("name")
            or ""
        )

    return (
        str(value)
        .upper()
        .strip()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "")
    )


def market_symbol(item):
    if not isinstance(item, dict):
        return ""

    market = item.get("market")

    if isinstance(market, dict):
        value = (
            market.get("code")
            or market.get("symbol")
            or market.get("name")
        )
    else:
        value = (
            item.get("symbol")
            or item.get("code")
            or item.get("market")
        )

    return normalize_symbol(value)


def ticker_price(item):
    if not isinstance(item, dict):
        return 0.0

    for key in (
        "price",
        "last",
        "last_price",
        "lastPrice",
        "close",
        "c",
    ):
        value = item.get(key)

        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                continue

    return 0.0


def build_market_map(markets, tickers):
    prices = {}

    if isinstance(tickers, dict):
        for symbol, item in tickers.items():
            normalized = normalize_symbol(symbol)
            price = ticker_price(item)

            if normalized and price > 0:
                prices[normalized] = price
    else:
        for item in tickers:
            symbol = market_symbol(item)
            price = ticker_price(item)

            if symbol and price > 0:
                prices[symbol] = price

    result = {}

    for item in markets:
        if not isinstance(item, dict):
            continue

        symbol = market_symbol(item)

        if not symbol.endswith("_USDT"):
            continue

        price = prices.get(symbol, 0.0)

        if price <= 0:
            price = prices.get(symbol.replace("_", ""), 0.0)

        if price > 0:
            result[symbol] = {
                "symbol": symbol,
                "price": price,
            }

    # Fallback: use ticker symbols if market data shape differs.
    for symbol, price in prices.items():
        if symbol.endswith("_USDT") and price > 0:
            result.setdefault(
                symbol,
                {"symbol": symbol, "price": price}
            )

    return result


# ============================================================
# BINANCE PUBLIC CANDLES
# ============================================================

def binance_symbol(bitpin_symbol):
    # BTC_USDT -> BTCUSDT
    return bitpin_symbol.replace("_", "")


def get_candles(symbol, timeframe):
    url = BINANCE_BASE + "/api/v3/klines"

    params = {
        "symbol": binance_symbol(symbol),
        "interval": timeframe,
        "limit": CANDLE_LIMIT,
    }

    data = get_json(url, params=params)

    if not isinstance(data, list):
        log.warning(
            "No Binance candle list: %s %s",
            symbol, timeframe
        )
        return []

    candles = []

    for row in data:
        try:
            if not isinstance(row, list) or len(row) < 6:
                continue

            candles.append({
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })

        except (ValueError, TypeError, IndexError):
            continue

    if len(candles) >= EMA_SLOW:
        log.info(
            "Binance candles OK: %s %s | %d",
            symbol, timeframe, len(candles)
        )
        return candles

    log.warning(
        "Insufficient candles: %s %s | %d",
        symbol, timeframe, len(candles)
    )
    return []


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)

    for price in values[period:]:
        value = price * alpha + value * (1.0 - alpha)

    return value


def rsi(values, period=RSI_PERIOD):
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

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    ranges = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous_close = candles[index - 1]["close"]

        ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close),
        ))

    return sum(ranges[-period:]) / period


def analyze_timeframe(candles):
    if len(candles) < EMA_SLOW + 2:
        return None

    closes = [candle["close"] for candle in candles]
    volumes = [candle["volume"] for candle in candles]

    fast = ema(closes, EMA_FAST)
    slow = ema(closes, EMA_SLOW)
    current_rsi = rsi(closes)
    current_atr = calculate_atr(candles)

    if any(value is None for value in (
        fast, slow, current_rsi, current_atr
    )):
        return None

    recent_volumes = volumes[-5:]
    baseline_volumes = volumes[-25:-5]

    recent_volume = (
        sum(recent_volumes) / len(recent_volumes)
        if recent_volumes else 0.0
    )

    baseline_volume = (
        sum(baseline_volumes) / len(baseline_volumes)
        if baseline_volumes else 0.0
    )

    volume_ratio = (
        recent_volume / baseline_volume
        if baseline_volume > 0 else 1.0
    )

    last_close = closes[-1]

    return {
        "close": last_close,
        "ema20": fast,
        "ema50": slow,
        "rsi": current_rsi,
        "atr": current_atr,
        "volume_ratio": volume_ratio,
        "bullish": fast > slow and last_close > fast,
        "bearish": fast < slow and last_close < fast,
    }


# ============================================================
# SIGNAL ENGINE
# ============================================================

def build_signal(symbol, bitpin_price, candles15, candles1h):
    data15 = analyze_timeframe(candles15)
    data1h = analyze_timeframe(candles1h)

    if not data15 or not data1h:
        return None

    long_score = 0
    short_score = 0

    # Trend alignment
    if data15["bullish"]:
        long_score += 25

    if data1h["bullish"]:
        long_score += 30

    if data15["bearish"]:
        short_score += 25

    if data1h["bearish"]:
        short_score += 30

    # RSI confirmation
    if 50 <= data15["rsi"] <= 68:
        long_score += 15

    if 32 <= data15["rsi"] < 50:
        short_score += 15

    if data1h["rsi"] >= 50:
        long_score += 10
    else:
        short_score += 10

    # Volume confirmation
    if data15["volume_ratio"] >= 1.15:
        if data15["close"] >= data15["ema20"]:
            long_score += 15
        else:
            short_score += 15

    direction = None
    score = 0

    if long_score >= MIN_SCORE and long_score > short_score:
        direction = "LONG"
        score = long_score

    elif short_score >= MIN_SCORE and short_score > long_score:
        direction = "SHORT"
        score = short_score

    if direction is None:
        return None

    # Entry is the latest Bitpin ticker price.
    # ATR is derived from Binance candles.
    entry = bitpin_price
    volatility = data15["atr"]

    if entry <= 0 or volatility <= 0:
        return None

    # Keep risk distance proportional to Bitpin price.
    # ATR is scaled by the ratio between Bitpin and Binance prices.
    scale = entry / data15["close"]
    risk_distance = 1.5 * volatility * scale

    if direction == "LONG":
        stop = entry - risk_distance
        targets = [
            entry + risk_distance,
            entry + 2 * risk_distance,
            entry + 3 * risk_distance,
        ]
    else:
        stop = entry + risk_distance
        targets = [
            entry - risk_distance,
            entry - 2 * risk_distance,
            entry - 3 * risk_distance,
        ]

    quantity = POSITION_VALUE / entry

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "entry": entry,
        "stop": stop,
        "targets": targets,
        "rsi15": data15["rsi"],
        "rsi1h": data1h["rsi"],
        "volume_ratio": data15["volume_ratio"],
        "quantity": quantity,
        "notional": POSITION_VALUE,
    }


# ============================================================
# TELEGRAM FORMATTING
# ============================================================

def fmt_price(value):
    if value >= 1000:
        return f"{value:,.4f}".rstrip("0").rstrip(".")

    if value >= 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    return f"{value:.8f}".rstrip("0").rstrip(".")


def header_message():
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    return (
        "🐋 <b>ETH WHALE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>BITPIN SMART MARKET WATCH</b>\n"
        "🧪 <b>PAPER MODE • REAL ORDERS OFF</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Capital: <b>{CAPITAL_USDT:.2f} USDT</b>\n"
        f"⚙️ Simulated leverage: <b>{LEVERAGE}x</b>\n"
        f"📐 Hypothetical position: "
        f"<b>{POSITION_VALUE:.2f} USDT</b>\n"
        "📈 Timeframes: <b>15m + 1h</b>\n"
        "📊 Candles: <b>Binance public API</b>\n"
        "💱 Market prices: <b>Bitpin</b>\n"
        "🛡️ Real orders: <b>OFF</b>\n"
        f"🕒 <code>{now}</code>"
    )


def signal_message(signal):
    symbol = html.escape(signal["symbol"])
    direction = signal["direction"]

    icon = "🟢" if direction == "LONG" else "🔴"
    label = "LONG / خرید آزمایشی" if direction == "LONG" else "SHORT / فروش آزمایشی"

    tp1, tp2, tp3 = signal["targets"]

    strength = (
        "🔥 قوی"
        if signal["score"] >= STRONG_SCORE
        else "⚡ متعادل"
    )

    return (
        f"🐋 <b>ETH WHALE | {symbol}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{icon} <b>{label}</b> | {strength}\n"
        f"⭐ امتیاز: <b>{signal['score']}/100</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Entry: <code>{fmt_price(signal['entry'])}</code>\n"
        f"🛑 Stop Loss: <code>{fmt_price(signal['stop'])}</code>\n"
        f"🥉 TP1: <code>{fmt_price(tp1)}</code>\n"
        f"🥈 TP2: <code>{fmt_price(tp2)}</code>\n"
        f"🥇 TP3: <code>{fmt_price(tp3)}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI 15m: <b>{signal['rsi15']:.1f}</b>\n"
        f"📊 RSI 1h: <b>{signal['rsi1h']:.1f}</b>\n"
        f"🔊 Volume ratio: <b>{signal['volume_ratio']:.2f}x</b>\n"
        f"💵 Position: <b>{signal['notional']:.2f} USDT</b>\n"
        f"📦 Hypothetical quantity: "
        f"<code>{signal['quantity']:.8f}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ سیگنال آزمایشی است؛ سفارش واقعی ثبت نمی‌شود.\n"
        "ℹ️ کندل‌ها از بایننس و قیمت ورود از بیت‌پین است."
    )


# ============================================================
# MAIN
# ============================================================

def main():
    log.info("=" * 55)
    log.info("ETH WHALE BOT STARTED")
    log.info("Bitpin base: %s", BITPIN_BASE)
    log.info("Binance candle source: %s", BINANCE_BASE)
    log.info("Paper mode: %s", PAPER_MODE)
    log.info("Real orders enabled: %s", REAL_ORDERS_ENABLED)

    if not PAPER_MODE or REAL_ORDERS_ENABLED:
        raise RuntimeError(
            "Safety check failed: paper mode must be ON "
            "and real orders must be OFF."
        )

    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.warning(
            "Telegram secrets missing. "
            "Expected TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )

    markets = get_markets()
    tickers = get_tickers()

    if not markets:
        log.error("No Bitpin markets received.")
        telegram_send(
            header_message()
            + "\n\n🔴 خطا: دریافت فهرست بازارهای بیت‌پین ناموفق بود."
        )
        return

    if not tickers:
        log.error("No Bitpin tickers received.")
        telegram_send(
            header_message()
            + "\n\n🔴 خطا: دریافت قیمت‌های بیت‌پین ناموفق بود."
        )
        return

    market_map = build_market_map(markets, tickers)

    candidates = sorted(
        market_map.values(),
        key=lambda item: item["symbol"]
    )[:MAX_MARKETS]

    log.info("Markets received: %d", len(markets))
    log.info("USDT markets with prices: %d", len(market_map))
    log.info("Markets selected for scan: %d", len(candidates))

    signals = []
    analyzed = 0
    candle_errors = 0

    for index, item in enumerate(candidates, start=1):
        symbol = item["symbol"]
        price = item["price"]

        log.info(
            "Scanning %d/%d: %s | Bitpin price=%s",
            index, len(candidates), symbol, price
        )

        candles15 = get_candles(symbol, "15m")
        time.sleep(REQUEST_PAUSE)

        candles1h = get_candles(symbol, "1h")
        time.sleep(REQUEST_PAUSE)

        if not candles15 or not candles1h:
            candle_errors += 1
            continue

        analyzed += 1

        signal = build_signal(
            symbol,
            price,
            candles15,
            candles1h,
        )

        if signal:
            signals.append(signal)
            log.info(
                "SIGNAL: %s %s score=%d",
                symbol,
                signal["direction"],
                signal["score"],
            )

    signals.sort(
        key=lambda signal: signal["score"],
        reverse=True,
    )
    signals = signals[:MAX_SIGNALS]

    log.info("Analyzed: %d", analyzed)
    log.info("Missing/error candles: %d", candle_errors)
    log.info("Signals found: %d", len(signals))

    summary = (
        header_message()
        + "\n━━━━━━━━━━━━━━━━━━━━\n"
        + "📋 <b>SCAN REPORT</b>\n"
        + f"🌐 Markets selected: <b>{len(candidates)}</b>\n"
        + f"🔎 Analyzed: <b>{analyzed}</b>\n"
        + f"⚠️ Missing/error candle data: <b>{candle_errors}</b>\n"
        + f"📡 Signals found: <b>{len(signals)}</b>\n"
    )

    if analyzed == 0:
        summary += (
            "\n🔴 <b>تحلیل انجام نشد.</b>\n"
            "دریافت کندل از بایننس ناموفق بود یا نمادها "
            "در بایننس بازار مشترک ندارند."
        )
    elif not signals:
        summary += (
            "\n⏳ <b>WAIT — فعلاً سیگنال تأییدشده‌ای نیست.</b>\n"
            "روندها یا شروط RSI و حجم به حد نصاب نرسیدند."
        )

    telegram_send(summary)

    for signal in signals:
        telegram_send(signal_message(signal))
        time.sleep(0.3)

    log.info("ETH WHALE BOT FINISHED")


if __name__ == "__main__":
    main()
