
import os
import time
import html
import logging
from datetime import datetime, timezone

import requests

# ============================================================
# ETH WHALE - BITPIN SMART MARKET WATCH
# PAPER SIGNALS ONLY - NO REAL ORDERS
# ============================================================

BITPIN_BASE = "https://api.bitpin.ir"
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

TIMEFRAMES = ("15m", "1h")
REQUEST_TIMEOUT = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("eth-whale")

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/1.0",
    "Accept": "application/json",
})


# ============================================================
# HTTP HELPERS
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
            "GET failed: %s | params=%s | error=%s",
            url, params, exc
        )
        return None


def telegram_send(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.warning("Telegram credentials are missing.")
        return False

    url = f"{TELEGRAM_API}/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = session.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            log.error("Telegram API returned: %s", result)
            return False

        log.info("Telegram message sent.")
        return True

    except Exception as exc:
        log.error("Telegram send failed: %s", exc)
        return False


def unwrap_list(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "results", "data", "markets",
            "tickers", "items", "list"
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in ("results", "items", "list"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return nested

    return []


# ============================================================
# MARKETS AND TICKERS
# ============================================================

def get_markets():
    endpoints = [
        "/v1/mkt/markets/",
        "/api/v1/mkt/markets/",
    ]

    for endpoint in endpoints:
        data = get_json(BITPIN_BASE + endpoint)

        rows = unwrap_list(data)
        if rows:
            log.info(
                "Markets endpoint OK: %s (%d rows)",
                endpoint, len(rows)
            )
            return rows

    log.error("Could not retrieve markets from tested endpoints.")
    return []


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
                    "Ticker endpoint OK: %s (%d rows)",
                    endpoint, len(tickers)
                )
                return tickers

        rows = unwrap_list(data)
        if rows:
            log.info(
                "Ticker endpoint OK: %s (%d rows)",
                endpoint, len(rows)
            )
            return rows

    log.error("Could not retrieve tickers.")
    return []


def norm_symbol(value):
    if isinstance(value, dict):
        value = (
            value.get("code")
            or value.get("symbol")
            or value.get("name")
            or ""
        )

    value = str(value).upper().strip()
    value = value.replace("/", "-").replace("_", "-")
    return value


def item_symbol(item):
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

    return norm_symbol(value)


def ticker_price(item):
    if not isinstance(item, dict):
        return 0.0

    for key in (
        "last", "last_price", "price",
        "close", "lastPrice", "c"
    ):
        value = item.get(key)

        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                pass

    return 0.0


def build_markets(markets, tickers):
    prices = {}

    if isinstance(tickers, dict):
        for symbol, item in tickers.items():
            if isinstance(item, dict):
                prices[norm_symbol(symbol)] = ticker_price(item)
    else:
        for item in tickers:
            symbol = item_symbol(item)
            if symbol:
                prices[symbol] = ticker_price(item)

    output = {}

    for market in markets:
        if not isinstance(market, dict):
            continue

        symbol = item_symbol(market)
        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        # Accept BTC-USDT and BTCUSDT symbol forms.
        price = prices.get(symbol, 0.0)

        if price <= 0:
            compact = symbol.replace("-", "")
            for ticker_symbol, ticker_value in prices.items():
                if ticker_symbol.replace("-", "") == compact:
                    price = ticker_value
                    break

        output[symbol] = {
            "symbol": symbol,
            "price": price,
            "market": market,
        }

    # Some ticker responses contain symbols missing from markets.
    for symbol, price in prices.items():
        if symbol.endswith("USDT") and symbol not in output:
            output[symbol] = {
                "symbol": symbol,
                "price": price,
                "market": {},
            }

    return output


# ============================================================
# CANDLE DATA
# NOTE: Bitpin candle routes/parameters can vary by API version.
# Every attempt is logged; no candle data is fabricated.
# ============================================================

def parse_candle(row):
    try:
        if isinstance(row, dict):
            open_price = row.get("open", row.get("o"))
            high_price = row.get("high", row.get("h"))
            low_price = row.get("low", row.get("l"))
            close_price = row.get("close", row.get("c"))
            volume = row.get(
                "volume",
                row.get("base_volume", row.get("v", 0))
            )

            if None in (
                open_price, high_price,
                low_price, close_price
            ):
                return None

            return {
                "open": float(open_price),
                "high": float(high_price),
                "low": float(low_price),
                "close": float(close_price),
                "volume": float(volume or 0),
            }

        if isinstance(row, (list, tuple)) and len(row) >= 5:
            # Common OHLCV layout:
            # timestamp, open, high, low, close, volume
            return {
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 else 0.0,
            }

    except (ValueError, TypeError, IndexError):
        return None

    return None


def candle_rows(data):
    rows = unwrap_list(data)

    if not rows and isinstance(data, dict):
        for key in ("candles", "ohlc", "klines"):
            value = data.get(key)
            if isinstance(value, list):
                rows = value
                break

    result = []

    for row in rows:
        candle = parse_candle(row)
        if candle:
            result.append(candle)

    return result


def get_candles(symbol, timeframe):
    compact_symbol = symbol.replace("-", "_")
    dash_symbol = symbol.replace("_", "-")

    # These are compatibility attempts, not a claim that every
    # path is supported by the current Bitpin API.
    attempts = [
        (
            "/v1/mkt/ohlc/",
            {"market": symbol, "interval": timeframe},
        ),
        (
            "/v1/mkt/ohlc/",
            {"symbol": symbol, "interval": timeframe},
        ),
        (
            "/v1/mkt/ohlc/",
            {"market": compact_symbol, "interval": timeframe},
        ),
        (
            "/v1/mkt/candles/",
            {"market": symbol, "interval": timeframe},
        ),
        (
            "/v1/mkt/candles/",
            {"symbol": symbol, "interval": timeframe},
        ),
        (
            "/api/v1/mkt/ohlc/",
            {"market": symbol, "interval": timeframe},
        ),
        (
            "/api/v1/mkt/candles/",
            {"market": symbol, "interval": timeframe},
        ),
        (
            "/v1/mkt/ohlc/",
            {"market": dash_symbol, "timeframe": timeframe},
        ),
        (
            "/v1/mkt/ohlc/",
            {"symbol": compact_symbol, "timeframe": timeframe},
        ),
    ]

    for endpoint, params in attempts:
        data = get_json(BITPIN_BASE + endpoint, params=params)
        rows = candle_rows(data)

        if len(rows) >= EMA_SLOW:
            log.info(
                "Candles OK: %s %s (%d)",
                symbol, timeframe, len(rows)
            )
            return rows[-CANDLE_LIMIT:]

    log.warning(
        "No usable candle route found for %s %s. "
        "Signal analysis skipped for this timeframe.",
        symbol, timeframe
    )
    return []


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period

    for value in values[period:]:
        current = value * alpha + current * (1.0 - alpha)

    return current


def rsi(values, period=RSI_PERIOD):
    if len(values) < period + 1:
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
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close),
        )
        true_ranges.append(true_range)

    return sum(true_ranges[-period:]) / period


def analyze_timeframe(candles):
    if len(candles) < EMA_SLOW + 2:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    fast = ema(closes, EMA_FAST)
    slow = ema(closes, EMA_SLOW)
    current_rsi = rsi(closes)
    current_atr = atr(candles)

    if None in (fast, slow, current_rsi, current_atr):
        return None

    recent_volume = (
        sum(volumes[-5:]) / min(5, len(volumes))
        if volumes else 0.0
    )

    prior_volumes = volumes[-25:-5]
    baseline_volume = (
        sum(prior_volumes) / len(prior_volumes)
        if prior_volumes else 0.0
    )

    volume_ratio = (
        recent_volume / baseline_volume
        if baseline_volume > 0 else 1.0
    )

    price = closes[-1]

    return {
        "price": price,
        "ema20": fast,
        "ema50": slow,
        "rsi": current_rsi,
        "atr": current_atr,
        "volume_ratio": volume_ratio,
        "bullish": fast > slow and price > fast,
        "bearish": fast < slow and price < fast,
    }


# ============================================================
# SIGNAL ENGINE - PAPER ONLY
# ============================================================

def build_signal(symbol, candles_15m, candles_1h):
    data15 = analyze_timeframe(candles_15m)
    data1h = analyze_timeframe(candles_1h)

    if not data15 or not data1h:
        return None

    long_score = 0
    short_score = 0

    if data15["bullish"]:
        long_score += 25
    if data1h["bullish"]:
        long_score += 30

    if data15["bearish"]:
        short_score += 25
    if data1h["bearish"]:
        short_score += 30

    rsi15 = data15["rsi"]

    if 50 <= rsi15 <= 68:
        long_score += 15
    elif 32 <= rsi15 <= 50:
        short_score += 15

    if data15["volume_ratio"] >= 1.15:
        if data15["price"] >= data15["ema20"]:
            long_score += 15
        else:
            short_score += 15

    if data1h["rsi"] >= 50:
        long_score += 10
    else:
        short_score += 10

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

    entry = data15["price"]
    volatility = data15["atr"]

    if entry <= 0 or volatility <= 0:
        return None

    if direction == "LONG":
        stop = entry - (1.5 * volatility)
        risk = entry - stop
        targets = [
            entry + risk,
            entry + (risk * 2),
            entry + (risk * 3),
        ]
    else:
        stop = entry + (1.5 * volatility)
        risk = stop - entry
        targets = [
            entry - risk,
            entry - (risk * 2),
            entry - (risk * 3),
        ]

    if risk <= 0:
        return None

    # Position sizing is a simulation only.
    margin = CAPITAL_USDT
    notional = margin * LEVERAGE
    estimated_quantity = notional / entry

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
        "quantity": estimated_quantity,
        "notional": notional,
    }


# ============================================================
# TELEGRAM MESSAGE DESIGN
# ============================================================

def fmt_price(value):
    if value >= 1000:
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if value >= 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def header_message():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return (
        "🐋 <b>ETH WHALE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>BITPIN SMART MARKET WATCH</b>\n"
        "🧪 <b>PAPER SIGNALS ONLY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 سرمایه آزمایشی: <b>{CAPITAL_USDT:.2f} USDT</b>\n"
        f"⚙️ اهرم شبیه‌سازی: <b>{LEVERAGE}x</b>\n"
        f"📦 ارزش فرضی پوزیشن: <b>{POSITION_VALUE:.2f} USDT</b>\n"
        "📈 تایم‌فریم: <b>15m + 1h</b>\n"
        "🛡️ سفارش واقعی: <b>خاموش</b>\n"
        f"🕒 <code>{now}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


def signal_message(signal):
    symbol = html.escape(signal["symbol"])
    direction = signal["direction"]

    icon = "🟢" if direction == "LONG" else "🔴"
    label = "خرید آزمایشی / LONG" if direction == "LONG" else "فروش آزمایشی / SHORT"

    entry = signal["entry"]
    stop = signal["stop"]
    tp1, tp2, tp3 = signal["targets"]

    return (
        f"{icon} <b>{symbol}</b>\n"
        f"🎯 <b>{label}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ امتیاز سیگنال: <b>{signal['score']}/100</b>\n"
        f"📍 ورود فرضی: <code>{fmt_price(entry)}</code>\n"
        f"🛑 حد ضرر: <code>{fmt_price(stop)}</code>\n"
        f"🥉 TP1: <code>{fmt_price(tp1)}</code>\n"
        f"🥈 TP2: <code>{fmt_price(tp2)}</code>\n"
        f"🥇 TP3: <code>{fmt_price(tp3)}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI 15m: <b>{signal['rsi15']:.1f}</b>\n"
        f"📊 RSI 1h: <b>{signal['rsi1h']:.1f}</b>\n"
        f"🔊 نسبت حجم: <b>{signal['volume_ratio']:.2f}x</b>\n"
        f"💵 ارزش فرضی پوزیشن: <b>{signal['notional']:.2f} USDT</b>\n"
        f"📦 مقدار فرضی: <code>{signal['quantity']:.8f}</code>\n"
        "⚠️ این پیام سیگنال آزمایشی است؛ سفارش ثبت نمی‌شود."
    )


# ============================================================
# MAIN
# ============================================================

def main():
    log.info("=" * 55)
    log.info("ETH WHALE BITPIN PAPER BOT STARTED")
    log.info("Paper mode: %s", PAPER_MODE)
    log.info("Real orders enabled: %s", REAL_ORDERS_ENABLED)
    log.info("Capital: %.2f USDT | Simulated leverage: %sx",
             CAPITAL_USDT, LEVERAGE)

    if REAL_ORDERS_ENABLED:
        raise RuntimeError(
            "Safety stop: real orders must remain disabled."
        )

    if not PAPER_MODE:
        raise RuntimeError(
            "Safety stop: PAPER_MODE must remain enabled."
        )

    markets = get_markets()
    tickers = get_tickers()

    if not markets:
        log.error("STOP: no markets returned by Bitpin.")
        telegram_send(
            header_message()
            + "\n\n🔴 <b>خطا:</b> دریافت فهرست بازارها ناموفق بود."
        )
        return

    if not tickers:
        log.error("STOP: no tickers returned by Bitpin.")
        telegram_send(
            header_message()
            + "\n\n🔴 <b>خطا:</b> دریافت قیمت‌ها ناموفق بود."
        )
        return

    available = build_markets(markets, tickers)
    candidates = sorted(
        available.values(),
        key=lambda item: item["symbol"]
    )[:MAX_MARKETS]

    log.info("Markets returned: %d", len(markets))
    log.info("Tickers returned: %d", len(unwrap_list(tickers)) if isinstance(tickers, list) else len(tickers))
    log.info("USDT markets selected: %d", len(candidates))

    signals = []
    analyzed = 0
    candle_failures = 0

    for index, item in enumerate(candidates, start=1):
        symbol = item["symbol"]

        log.info(
            "Scanning %d/%d: %s",
            index, len(candidates), symbol
        )

        candles15 = get_candles(symbol, "15m")
        candles1h = get_candles(symbol, "1h")

        if not candles15 or not candles1h:
            candle_failures += 1
            continue

        analyzed += 1
        signal = build_signal(symbol, candles15, candles1h)

        if signal:
            signals.append(signal)
            log.info(
                "Signal: %s %s score=%d",
                symbol, signal["direction"], signal["score"]
            )

        # Reduce request pressure on the public API.
        time.sleep(0.15)

    signals.sort(key=lambda item: item["score"], reverse=True)
    signals = signals[:MAX_SIGNALS]

    log.info("Markets analyzed: %d", analyzed)
    log.info("Candle failures/skips: %d", candle_failures)
    log.info("Signals found: %d", len(signals))

    summary = (
        header_message()
        + "\n\n"
        + "🧾 <b>گزارش اسکن</b>\n"
        + f"🔎 بازارهای انتخاب‌شده: <b>{len(candidates)}</b>\n"
        + f"✅ بازارهای تحلیل‌شده: <b>{analyzed}</b>\n"
        + f"⚠️ بازارهای بدون کندل معتبر: <b>{candle_failures}</b>\n"
        + f"🎯 سیگنال‌های معتبر: <b>{len(signals)}</b>\n"
    )

    if analyzed == 0:
        summary += (
            "\n🔴 <b>تحلیل انجام نشد.</b>\n"
            "مسیر API کندل‌ها یا ساختار پاسخ باید بررسی شود؛ "
            "هیچ داده‌ای به‌صورت ساختگی تولید نشده است."
        )
    elif not signals:
        summary += (
            "\n⏳ <b>فعلاً سیگنال مناسبی پیدا نشد.</b>\n"
            "فیلترها برای جلوگیری از ورود ضعیف فعال هستند."
        )

    telegram_send(summary)

    for signal in signals:
        telegram_send(signal_message(signal))
        time.sleep(0.3)

    log.info("Bot finished successfully.")


if __name__ == "__main__":
    main()
