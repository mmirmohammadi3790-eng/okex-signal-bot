
import os
import sys
import time
import logging
import requests
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# ETH WHALE | BITPIN SMART MARKET WATCH
# PAPER TRADING ONLY - NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
BASE_URL = "https://api.bitpin.ir"

CAPITAL_USDT = 48.0
LEVERAGE = 3
MARGIN_PER_TRADE = 16.0
POSITION_VALUE = MARGIN_PER_TRADE * LEVERAGE

MAX_MARKETS = 220
MAX_SIGNALS = 3
MIN_SCORE = 60
STRONG_SCORE = 75

CANDLE_LIMIT = 100
MIN_QUOTE_VOLUME = 10000.0
REQUEST_TIMEOUT = (8, 20)

PAPER_MODE = True
REAL_ORDERS_ENABLED = False

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
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/2.0",
    "Accept": "application/json",
})

retry = Retry(
    total=2,
    connect=2,
    read=2,
    backoff_factor=0.7,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)

adapter = HTTPAdapter(max_retries=retry)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram credentials missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = SESSION.post(
            url,
            json={
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
            logging.error("Telegram rejected message.")
            return False

        logging.info("Telegram message sent.")
        return True

    except Exception as exc:
        logging.error("Telegram error: %s", exc)
        return False


# ============================================================
# HTTP HELPERS
# ============================================================

def api_get(path, params=None):
    url = BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def extract_list(data, keys=()):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

        for key in ("results", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def first_value(obj, *keys):
    if not isinstance(obj, dict):
        return None

    for key in keys:
        value = obj.get(key)
        if value is not None and value != "":
            return value

    return None


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(value):
    if not value:
        return ""

    return (
        str(value)
        .upper()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "")
    )


def currency_code(value):
    if isinstance(value, dict):
        return first_value(value, "code", "symbol", "name")
    return value


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():
    paths = (
        "/v1/mkt/markets/",
        "/api/v1/mkt/markets/",
        "/api/v1/spot/public/pairs",
    )

    last_error = None

    for path in paths:
        for attempt in range(2):
            try:
                logging.info(
                    "Requesting markets: %s attempt=%d",
                    path, attempt + 1,
                )

                data = api_get(path)
                rows = extract_list(
                    data,
                    ("results", "markets", "pairs", "data"),
                )

                if not rows:
                    logging.warning(
                        "No market rows returned by %s", path
                    )
                    break

                unique = {}

                for row in rows:
                    if not isinstance(row, dict):
                        continue

                    symbol = first_value(
                        row, "symbol", "code", "name", "market"
                    )

                    if not symbol:
                        base = currency_code(first_value(
                            row, "base_currency", "base", "currency1"
                        ))
                        quote = currency_code(first_value(
                            row, "quote_currency", "quote", "currency2"
                        ))

                        if base and quote:
                            symbol = f"{base}_{quote}"

                    symbol = normalize_symbol(symbol)

                    if not symbol:
                        continue

                    if not (
                        symbol.endswith("_USDT")
                        or symbol.endswith("USDT")
                    ):
                        continue

                    base_symbol = (
                        symbol[:-5]
                        if symbol.endswith("_USDT")
                        else symbol[:-4]
                    )

                    if base_symbol in {
                        "USDT", "USDC", "BUSD", "DAI",
                        "TUSD", "FDUSD", "USDE",
                    }:
                        continue

                    unique[symbol] = {
                        "symbol": symbol,
                        "raw": row,
                    }

                markets = list(unique.values())

                if markets:
                    logging.info(
                        "Markets discovered: %d via %s",
                        len(markets), path,
                    )
                    return markets[:MAX_MARKETS]

                logging.warning(
                    "No USDT markets parsed from %s", path
                )
                break

            except Exception as exc:
                last_error = exc
                logging.warning(
                    "Market endpoint failed: %s | %s",
                    path, exc,
                )
                if attempt == 0:
                    time.sleep(2)

    raise RuntimeError(
        "Could not retrieve Bitpin markets. Last error: "
        + str(last_error)
    )


# ============================================================
# TICKERS
# ============================================================

def get_tickers():
    paths = (
        "/v1/mkt/tickers/",
        "/api/v1/mkt/tickers/",
        "/api/v1/spot/public/tickers",
    )

    last_error = None

    for path in paths:
        try:
            data = api_get(path)

            if isinstance(data, dict):
                rows = extract_list(
                    data, ("tickers", "results", "data")
                )

                if not rows and isinstance(
                    data.get("tickers"), dict
                ):
                    rows = list(data["tickers"].values())
            else:
                rows = extract_list(data)

            if not rows:
                logging.warning(
                    "No ticker rows from %s", path
                )
                continue

            output = {}

            for row in rows:
                if not isinstance(row, dict):
                    continue

                symbol = first_value(
                    row, "symbol", "market", "code", "name"
                )

                if not symbol:
                    continue

                output[normalize_symbol(symbol)] = row

            if output:
                logging.info(
                    "Tickers received: %d via %s",
                    len(output), path,
                )
                return output

        except Exception as exc:
            last_error = exc
            logging.warning(
                "Ticker endpoint failed: %s | %s",
                path, exc,
            )

    raise RuntimeError(
        "Could not retrieve Bitpin tickers. Last error: "
        + str(last_error)
    )


def ticker_for(symbol, tickers):
    if symbol in tickers:
        return tickers[symbol]

    compact = symbol.replace("_", "").replace("-", "")

    for key, value in tickers.items():
        if key.replace("_", "").replace("-", "") == compact:
            return value

    return {}


def get_quote_volume(symbol, ticker):
    value = first_value(
        ticker,
        "quote_volume",
        "quoteVolume",
        "volume_quote",
        "quote_asset_volume",
        "turnover",
        "quoteVolume24h",
    )

    if value is not None:
        return as_float(value)

    base_volume = as_float(first_value(
        ticker, "volume", "base_volume", "baseVolume", "volume24h"
    ))

    price = as_float(first_value(
        ticker, "last", "last_price", "price", "close", "lastPrice"
    ))

    return base_volume * price


# ============================================================
# CANDLES
# ============================================================

def parse_candle_rows(data):
    rows = extract_list(
        data, ("results", "candles", "data", "items")
    )

    if not rows and isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                rows = value
                break

    candles = []

    for row in rows:
        try:
            if isinstance(row, dict):
                o = first_value(row, "open", "o")
                h = first_value(row, "high", "h")
                low = first_value(row, "low", "l")
                c = first_value(row, "close", "c")
                v = first_value(
                    row, "volume", "v", "base_volume"
                )

            elif isinstance(row, (list, tuple)) and len(row) >= 5:
                # Expected ordering:
                # timestamp, open, high, low, close, volume
                _, o, h, low, c = row[:5]
                v = row[5] if len(row) > 5 else 0

            else:
                continue

            o = as_float(o)
            h = as_float(h)
            low = as_float(low)
            c = as_float(c)
            v = as_float(v)

            if min(o, h, low, c) <= 0:
                continue

            candles.append({
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": max(v, 0.0),
            })

        except Exception:
            continue

    return candles


def get_candles(symbol, timeframe):
    interval_candidates = {
        "15m": ("15m", "15", "15min"),
        "1h": ("1h", "60"),
    }

    paths = (
        "/v1/mkt/ohlcv/",
        "/api/v1/mkt/ohlcv/",
        "/api/v1/mkt/candles/",
        "/api/v1/spot/public/candles",
    )

    last_error = None

    for path in paths:
        for interval in interval_candidates[timeframe]:
            # Try the most common parameter format first.
            params_candidates = (
                {
                    "market": symbol,
                    "interval": interval,
                    "limit": CANDLE_LIMIT,
                },
                {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": CANDLE_LIMIT,
                },
                {
                    "market": symbol,
                    "resolution": interval,
                    "limit": CANDLE_LIMIT,
                },
            )

            for params in params_candidates:
                try:
                    data = api_get(path, params=params)
                    candles = parse_candle_rows(data)

                    if len(candles) >= 55:
                        return candles[-CANDLE_LIMIT:]

                    logging.debug(
                        "Insufficient candles: %s %s %d",
                        symbol, timeframe, len(candles),
                    )

                except Exception as exc:
                    last_error = exc

    raise RuntimeError(
        f"No usable candles for {symbol} {timeframe}: "
        f"{last_error}"
    )


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    result = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)

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

    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]

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
    return 100.0 - 100.0 / (1.0 + rs)


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close),
        ))

    recent = ranges[-period:]
    return sum(recent) / len(recent)


def analyse_timeframe(candles):
    if len(candles) < 55:
        raise ValueError("Not enough candles")

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    current_rsi = rsi(closes, 14)
    current_atr = atr(candles, 14)

    if any(x is None for x in (
        ema20, ema50, current_rsi, current_atr
    )):
        raise ValueError("Indicator calculation failed")

    average_volume = (
        sum(volumes[-21:-1]) / max(len(volumes[-21:-1]), 1)
    )

    current_volume = volumes[-1]
    volume_ratio = (
        current_volume / average_volume
        if average_volume > 0 else 0.0
    )

    return {
        "close": closes[-1],
        "previous_close": closes[-2],
        "ema20": ema20,
        "ema50": ema50,
        "rsi": current_rsi,
        "atr": current_atr,
        "volume_ratio": volume_ratio,
    }


# ============================================================
# SIGNAL ENGINE
# ============================================================

def build_signal(symbol, ticker, candles15, candles1h):
    a15 = analyse_timeframe(candles15)
    a1h = analyse_timeframe(candles1h)

    price = a15["close"]

    if price <= 0:
        return None

    score_long = 0
    score_short = 0
    reasons_long = []
    reasons_short = []

    if a15["ema20"] > a15["ema50"]:
        score_long += 20
        reasons_long.append("EMA20 بالاتر از EMA50 در 15m")
    elif a15["ema20"] < a15["ema50"]:
        score_short += 20
        reasons_short.append("EMA20 پایین‌تر از EMA50 در 15m")

    if a1h["ema20"] > a1h["ema50"]:
        score_long += 25
        reasons_long.append("روند 1h صعودی")
    elif a1h["ema20"] < a1h["ema50"]:
        score_short += 25
        reasons_short.append("روند 1h نزولی")

    rsi15 = a15["rsi"]
    rsi1h = a1h["rsi"]

    if 50 <= rsi15 <= 68:
        score_long += 15
        reasons_long.append("RSI مناسب خرید")
    elif 32 <= rsi15 < 50:
        score_short += 15
        reasons_short.append("RSI مناسب فروش")

    if 45 <= rsi1h <= 70:
        score_long += 10

    if 30 <= rsi1h <= 55:
        score_short += 10

    if price > a15["ema20"]:
        score_long += 10
    elif price < a15["ema20"]:
        score_short += 10

    volume_ratio = a15["volume_ratio"]

    if volume_ratio >= 1.15:
        score_long += 10
        score_short += 10

    if price > a15["previous_close"]:
        score_long += 5
    elif price < a15["previous_close"]:
        score_short += 5

    quote_volume = get_quote_volume(symbol, ticker)

    if quote_volume and quote_volume < MIN_QUOTE_VOLUME:
        return None

    difference = abs(score_long - score_short)

    if score_long >= MIN_SCORE and score_long > score_short:
        side = "LONG"
        score = score_long
        reasons = reasons_long

    elif score_short >= MIN_SCORE and score_short > score_long:
        side = "SHORT"
        score = score_short
        reasons = reasons_short

    else:
        return None

    if difference < 10:
        return None

    volatility = a15["atr"] / price
    volatility = max(0.002, min(0.04, volatility))

    stop_pct = max(
        0.8, min(2.0, volatility * 100.0 * 1.4)
    )

    target1_pct = stop_pct * 1.2
    target2_pct = stop_pct * 2.0
    target3_pct = stop_pct * 3.0

    if side == "LONG":
        stop = price * (1 - stop_pct / 100)
        tp1 = price * (1 + target1_pct / 100)
        tp2 = price * (1 + target2_pct / 100)
        tp3 = price * (1 + target3_pct / 100)
    else:
        stop = price * (1 + stop_pct / 100)
        tp1 = price * (1 - target1_pct / 100)
        tp2 = price * (1 - target2_pct / 100)
        tp3 = price * (1 - target3_pct / 100)

    notional = POSITION_VALUE
    quantity = notional / price

    def pnl_at(target):
        move = (
            (target - price) / price
            if side == "LONG"
            else (price - target) / price
        )
        return notional * move

    return {
        "symbol": symbol,
        "side": side,
        "score": score,
        "price": price,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "quantity": quantity,
        "stop_pct": stop_pct,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "volume_ratio": volume_ratio,
        "quote_volume": quote_volume,
        "pnl1": pnl_at(tp1),
        "pnl2": pnl_at(tp2),
        "pnl3": pnl_at(tp3),
        "reasons": reasons,
    }


# ============================================================
# FORMATTING
# ============================================================

def fmt_price(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def fmt_usdt(value):
    return f"{value:+.2f} USDT"


def signal_message(signal):
    direction = (
        "🟢 LONG" if signal["side"] == "LONG"
        else "🔴 SHORT"
    )

    strength = (
        "🔥 قوی"
        if signal["score"] >= STRONG_SCORE
        else "⚡ متوسط"
    )

    reasons = "\n".join(
        "• " + reason for reason in signal["reasons"]
    )

    return (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>{signal['symbol']}</b>\n"
        f"🎯 جهت: <b>{direction}</b>\n"
        f"⭐ امتیاز: <b>{signal['score']}/100</b> | {strength}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💵 ورود فرضی: <code>{fmt_price(signal['price'])}</code>\n"
        f"🛑 حد ضرر: <code>{fmt_price(signal['stop'])}</code>\n"
        f"🥇 TP1: <code>{fmt_price(signal['tp1'])}</code>"
        f" | P/L: {fmt_usdt(signal['pnl1'])}\n"
        f"🥈 TP2: <code>{fmt_price(signal['tp2'])}</code>"
        f" | P/L: {fmt_usdt(signal['pnl2'])}\n"
        f"🥉 TP3: <code>{fmt_price(signal['tp3'])}</code>"
        f" | P/L: {fmt_usdt(signal['pnl3'])}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📈 RSI 15m: {signal['rsi15']:.1f}\n"
        f"📈 RSI 1h: {signal['rsi1h']:.1f}\n"
        f"📦 نسبت حجم: {signal['volume_ratio']:.2f}x\n"
        f"💰 مارجین فرضی: {MARGIN_PER_TRADE:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"📦 ارزش فرضی موقعیت: {POSITION_VALUE:.2f} USDT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 دلایل سیگنال:\n"
        f"{reasons}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧪 <b>PAPER TRADING ONLY</b>\n"
        "🚫 سفارش واقعی: <b>خاموش</b>\n"
        "⚠️ کارمزد و لغزش قیمت لحاظ نشده است."
    )


def status_message():
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    return (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>BITPIN SMART MARKET WATCH</b>\n"
        "🧪 <b>PAPER SIGNALS ONLY</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"💵 مارجین فرضی: {MARGIN_PER_TRADE:.2f} USDT\n"
        f"📦 ارزش فرضی: {POSITION_VALUE:.2f} USDT\n"
        f"🎯 حداقل امتیاز: {MIN_SCORE}\n"
        "📡 تایم‌فریم‌ها: 15m + 1h\n"
        "📈 شاخص‌ها: EMA20/EMA50 + RSI + Volume + ATR\n"
        f"🔢 حداکثر بازارها: {MAX_MARKETS}\n"
        f"🔔 حداکثر سیگنال: {MAX_SIGNALS}\n"
        "🚫 سفارش واقعی: غیرفعال\n"
        f"🕒 {now}\n"
        "━━━━━━━━━━━━━━━━━━"
    )


# ============================================================
# MARKET SCAN
# ============================================================

def run_scan():
    if not PAPER_MODE or REAL_ORDERS_ENABLED:
        raise RuntimeError(
            "Safety check failed: paper mode must be enabled "
            "and real orders must remain disabled."
        )

    started = time.time()
    errors = 0
    checked = 0
    signals = []

    telegram_send(
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔄 <b>شروع بررسی بازار بیت‌پین</b>\n"
        "🧪 حالت آزمایشی؛ بدون سفارش واقعی"
    )

    markets = get_markets()
    tickers = get_tickers()

    for index, market in enumerate(markets, start=1):
        symbol = market["symbol"]
        ticker = ticker_for(symbol, tickers)

        try:
            quote_volume = get_quote_volume(symbol, ticker)

            if quote_volume and quote_volume < MIN_QUOTE_VOLUME:
                continue

            candles15 = get_candles(symbol, "15m")
            candles1h = get_candles(symbol, "1h")

            checked += 1

            signal = build_signal(
                symbol, ticker, candles15, candles1h
            )

            if signal:
                signals.append(signal)

            if index % 20 == 0:
                logging.info(
                    "Scan progress: %d/%d markets",
                    index, len(markets),
                )

        except Exception as exc:
            errors += 1
            logging.warning("Skipped %s: %s", symbol, exc)

    signals.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    selected = signals[:MAX_SIGNALS]
    elapsed = time.time() - started
    sent = 0

    for signal in selected:
        if telegram_send(signal_message(signal)):
            sent += 1
        time.sleep(0.4)

    summary = (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>گزارش پایان اسکن</b>\n"
        f"🔎 بازارهای تحلیل‌شده: {checked}\n"
        f"📡 بازارهای دریافت‌شده: {len(markets)}\n"
        f"🎯 سیگنال‌های واجد شرایط: {len(signals)}\n"
        f"📨 پیام‌های سیگنال ارسال‌شده: {sent}\n"
        f"⚠️ بازارهای دارای خطا: {errors}\n"
        f"⏱ مدت اجرا: {elapsed:.1f} ثانیه\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        "🧪 PAPER ONLY | 🚫 REAL ORDERS OFF"
    )

    telegram_send(summary)

    logging.info(
        "Scan completed: markets=%d checked=%d "
        "signals=%d errors=%d duration=%.1fs",
        len(markets), checked, len(selected), errors, elapsed,
    )

    if checked == 0:
        raise RuntimeError(
            "No market completed candle analysis. "
            "Check Bitpin candle API and logs."
        )


# ============================================================
# MAIN
# ============================================================

def main():
    logging.info("ETH WHALE Bitpin paper bot starting.")
    logging.info(
        "Paper mode=%s | Real orders=%s",
        PAPER_MODE, REAL_ORDERS_ENABLED,
    )

    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning(
            "Telegram credentials missing. Check GitHub Secrets."
        )

    telegram_send(status_message())

    try:
        run_scan()

    except Exception as exc:
        logging.exception("Scan failed")

        telegram_send(
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ <b>اسکن کامل نشد</b>\n"
            f"علت: <code>{str(exc)[:700]}</code>\n"
            "🧪 حالت آزمایشی فعال است.\n"
            "🚫 هیچ سفارش واقعی ثبت نشده است."
        )

        raise


if __name__ == "__main__":
    main()
