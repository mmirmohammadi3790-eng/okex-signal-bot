
# ============================================================
# ETH WHALE - BITPIN SMART MARKET WATCH
# PAPER SIGNALS ONLY - NO REAL ORDERS
# Capital: 48 USDT | Simulated leverage: 3x
# Timeframes: 15m + 1h
# ============================================================

import os
import time
import html
import logging
from datetime import datetime, timezone

import requests

# ---------------- CONFIGURATION ----------------

BOT_NAME = "ETH WHALE"
BITPIN_BASE = "https://api.bitpin.ir"
TELEGRAM_API = "https://api.telegram.org"

PAPER_MODE = True
REAL_ORDERS_ENABLED = False

PAPER_CAPITAL = 48.0
LEVERAGE = 3
POSITION_VALUE = PAPER_CAPITAL * LEVERAGE

EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14

MIN_SIGNAL_SCORE = 60
STRONG_SIGNAL_SCORE = 75

MAX_MARKETS = 30
MAX_SIGNALS_PER_SCAN = 5
CANDLE_LIMIT = 100
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 0.15

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("ETH_WHALE")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-PaperSignalBot/2.0",
    "Accept": "application/json",
})

# Safety locks: this bot must never place real orders.
if not PAPER_MODE or REAL_ORDERS_ENABLED:
    raise RuntimeError("Safety stop: paper-only mode is mandatory.")


# ---------------- GENERAL HELPERS ----------------

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def get_json(url, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def telegram_send(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.error("Telegram credentials are missing.")
        return False

    url = f"{TELEGRAM_API}/bot{TELEGRAM_TOKEN}/sendMessage"

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
            logger.error("Telegram rejected the message.")
            return False

        logger.info("Telegram message sent.")
        return True

    except Exception as exc:
        logger.error("Telegram error: %s", type(exc).__name__)
        return False


def fmt_price(value):
    try:
        value = float(value)
        if value >= 1000:
            return f"{value:,.2f}"
        if value >= 1:
            return f"{value:.5f}".rstrip("0").rstrip(".")
        return f"{value:.8f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def unwrap_list(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "results", "data", "tickers", "markets",
            "pairs", "list", "result",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                nested = unwrap_list(value)
                if nested:
                    return nested

        if data and all(isinstance(v, dict) for v in data.values()):
            return [
                dict(v, symbol=v.get("symbol", k))
                for k, v in data.items()
            ]

    return []


# ---------------- MARKETS AND TICKERS ----------------

def get_markets():
    for path in (
        "/v1/mkt/markets/",
        "/api/v1/mkt/markets/",
    ):
        try:
            data = get_json(BITPIN_BASE + path)
            markets = unwrap_list(data)

            if markets:
                logger.info(
                    "Markets endpoint OK: %s (%d items)",
                    path, len(markets),
                )
                return markets

        except Exception as exc:
            logger.warning(
                "Markets endpoint failed: %s (%s)",
                path, type(exc).__name__,
            )

    return []


def get_tickers():
    for path in (
        "/v1/mkt/tickers/",
        "/api/v1/mkt/tickers/",
    ):
        try:
            data = get_json(BITPIN_BASE + path)
            tickers = unwrap_list(data)

            if tickers:
                logger.info(
                    "Ticker endpoint OK: %s (%d items)",
                    path, len(tickers),
                )
                return tickers

        except Exception as exc:
            logger.warning(
                "Ticker endpoint failed: %s (%s)",
                path, type(exc).__name__,
            )

    return []


def norm_symbol(value):
    return str(value or "").upper().strip().replace("/", "_").replace("-", "_")


def item_symbol(item):
    if isinstance(item, str):
        return norm_symbol(item)

    if not isinstance(item, dict):
        return ""

    # Bitpin market objects may provide the symbol as "code".
    if item.get("code"):
        return norm_symbol(item["code"])

    for key in ("symbol", "market", "pair", "name"):
        if item.get(key):
            return norm_symbol(item[key])

    # Support market objects with nested currency definitions.
    c1 = item.get("currency1")
    c2 = item.get("currency2")

    if isinstance(c1, dict) and isinstance(c2, dict):
        a = c1.get("code", "")
        b = c2.get("code", "")
        if a and b:
            return norm_symbol(f"{a}_{b}")

    return ""


def ticker_price(item):
    if not isinstance(item, dict):
        return 0.0

    for key in (
        "price", "last", "last_price", "lastPrice",
        "close", "last_traded_price",
    ):
        try:
            price = float(item.get(key))
            if price > 0:
                return price
        except (TypeError, ValueError):
            pass

    return 0.0


def build_markets(markets, tickers):
    ticker_map = {}

    for item in tickers:
        symbol = item_symbol(item)
        if symbol:
            ticker_map[symbol] = item
            ticker_map[symbol.replace("_", "")] = item

    output = []
    seen = set()

    for market in markets:
        symbol = item_symbol(market)

        if not symbol:
            continue

        # Only USDT-quoted markets.
        if not (symbol.endswith("_USDT") or symbol.endswith("USDT")):
            continue

        if symbol in seen:
            continue

        ticker = (
            ticker_map.get(symbol)
            or ticker_map.get(symbol.replace("_", ""))
        )

        if not ticker:
            continue

        price = ticker_price(ticker)
        if price <= 0:
            continue

        output.append({
            "symbol": symbol,
            "price": price,
        })
        seen.add(symbol)

    # Scan a manageable number per run to avoid excessive API calls.
    output.sort(key=lambda x: x["symbol"])
    logger.info("Valid USDT markets with prices: %d", len(output))

    return output[:MAX_MARKETS]


# ---------------- CANDLE DATA ----------------

def parse_candle(row):
    if isinstance(row, dict):
        def pick(*keys):
            for key in keys:
                if row.get(key) is not None:
                    return row[key]
            return None

        try:
            candle = {
                "open": float(pick("open", "o")),
                "high": float(pick("high", "h")),
                "low": float(pick("low", "l")),
                "close": float(pick("close", "c")),
                "volume": float(pick("volume", "v", "base_volume") or 0),
            }
        except (TypeError, ValueError):
            return None

    elif isinstance(row, (list, tuple)) and len(row) >= 5:
        try:
            # Common layout: timestamp, open, high, low, close, volume
            candle = {
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 else 0.0,
            }
        except (TypeError, ValueError):
            return None
    else:
        return None

    if any(candle[k] <= 0 for k in ("open", "high", "low", "close")):
        return None

    if candle["high"] < candle["low"] or candle["volume"] < 0:
        return None

    return candle


def candle_rows(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("results", "data", "candles", "ohlc", "klines", "result"):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                nested = candle_rows(value)
                if nested:
                    return nested

    return []


def get_candles(symbol, timeframe):
    """
    Try known-style public OHLC routes and log the response status.
    Bitpin's live candle route/parameters may vary; this function
    intentionally reports failures rather than pretending data exists.
    """
    clean_symbol = symbol.replace("/", "_")
    attempts = [
        (
            "/v1/mkt/ohlc/",
            {"market": clean_symbol, "interval": timeframe},
        ),
        (
            "/v1/mkt/ohlc/",
            {"symbol": clean_symbol, "interval": timeframe},
        ),
        (
            "/v1/mkt/candles/",
            {"market": clean_symbol, "interval": timeframe},
        ),
        (
            "/v1/mkt/candles/",
            {"symbol": clean_symbol, "interval": timeframe},
        ),
        (
            "/api/v1/mkt/ohlc/",
            {"market": clean_symbol, "interval": timeframe},
        ),
    ]

    for path, params in attempts:
        try:
            data = get_json(BITPIN_BASE + path, params=params)
            rows = candle_rows(data)
            parsed = []

            for row in rows:
                candle = parse_candle(row)
                if candle:
                    parsed.append(candle)

            if len(parsed) >= EMA_SLOW + 2:
                logger.info(
                    "Candles OK: %s %s (%d candles) via %s",
                    symbol, timeframe, len(parsed), path,
                )
                return parsed[-CANDLE_LIMIT:]

            logger.warning(
                "Candle response unusable: %s %s path=%s rows=%d",
                symbol, timeframe, path, len(rows),
            )

        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning(
                "Candle HTTP error: %s %s path=%s status=%s",
                symbol, timeframe, path, status,
            )
        except Exception as exc:
            logger.warning(
                "Candle request failed: %s %s path=%s error=%s",
                symbol, timeframe, path, type(exc).__name__,
            )

        time.sleep(REQUEST_DELAY)

    return []


# ---------------- INDICATORS ----------------

def ema(values, period):
    if len(values) < period:
        return []

    alpha = 2.0 / (period + 1.0)
    result = [sum(values[:period]) / period]

    for value in values[period:]:
        result.append(value * alpha + result[-1] * (1 - alpha))

    # Align the result with the tail of the input series.
    return result


def rsi(values, period=14):
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
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


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

    return sum(ranges[-period:]) / period


def analyze_timeframe(candles):
    if len(candles) < EMA_SLOW + 2:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    fast = ema(closes, EMA_FAST)
    slow = ema(closes, EMA_SLOW)
    current_rsi = rsi(closes, RSI_PERIOD)
    current_atr = atr(candles)

    if not fast or not slow or current_rsi is None or current_atr is None:
        return None

    # Compare the latest aligned EMA values.
    ema20 = fast[-1]
    ema50 = slow[-1]
    close = closes[-1]

    recent_volumes = volumes[-21:-1]
    avg_volume = (
        sum(recent_volumes) / len(recent_volumes)
        if recent_volumes else 0.0
    )
    volume_ratio = volumes[-1] / avg_volume if avg_volume > 0 else 0.0

    return {
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": current_rsi,
        "atr": current_atr,
        "volume_ratio": volume_ratio,
    }


# ---------------- SIGNAL ENGINE ----------------

def evaluate_signal(symbol, candles15, candles1h):
    fast = analyze_timeframe(candles15)
    slow = analyze_timeframe(candles1h)

    if not fast or not slow:
        return None

    score_long = 0
    score_short = 0

    if fast["ema20"] > fast["ema50"]:
        score_long += 25
    elif fast["ema20"] < fast["ema50"]:
        score_short += 25

    if slow["ema20"] > slow["ema50"]:
        score_long += 25
    elif slow["ema20"] < slow["ema50"]:
        score_short += 25

    if fast["close"] > fast["ema20"]:
        score_long += 10
    elif fast["close"] < fast["ema20"]:
        score_short += 10

    if 50 <= fast["rsi"] <= 68:
        score_long += 15
    elif 32 <= fast["rsi"] < 50:
        score_short += 15

    if fast["volume_ratio"] >= 1.15:
        if fast["close"] > fast["ema20"]:
            score_long += 10
        elif fast["close"] < fast["ema20"]:
            score_short += 10

    if fast["rsi"] > 75:
        score_long -= 10
    if fast["rsi"] < 25:
        score_short -= 10

    if score_long >= score_short:
        side, score = "LONG", score_long
    else:
        side, score = "SHORT", score_short

    # Both timeframes must point in the same direction.
    if side == "LONG":
        if not (
            fast["ema20"] > fast["ema50"]
            and slow["ema20"] > slow["ema50"]
        ):
            return None
        if not 40 <= fast["rsi"] <= 75:
            return None
    else:
        if not (
            fast["ema20"] < fast["ema50"]
            and slow["ema20"] < slow["ema50"]
        ):
            return None
        if not 25 <= fast["rsi"] <= 60:
            return None

    if score < MIN_SIGNAL_SCORE:
        return None

    entry = fast["close"]
    risk = max(fast["atr"] * 1.5, entry * 0.003)

    if side == "LONG":
        sl = entry - risk
        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3
    else:
        sl = entry + risk
        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    return {
        "symbol": symbol,
        "side": side,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": fast["rsi"],
        "volume_ratio": fast["volume_ratio"],
        "price_1h": slow["close"],
    }


# ---------------- TELEGRAM FORMAT ----------------

def signal_message(signal):
    icon = "🟢" if signal["side"] == "LONG" else "🔴"
    strength = (
        "🔥 STRONG SIGNAL"
        if signal["score"] >= STRONG_SIGNAL_SCORE
        else "⚡ SIGNAL"
    )

    symbol = html.escape(signal["symbol"])

    return (
        "🐋 <b>ETH WHALE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>BITPIN SMART MARKET WATCH</b>\n"
        "🧪 <b>PAPER TRADING ONLY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{icon} <b>{signal['side']} | {symbol}</b>\n"
        f"{strength} • Score: <b>{signal['score']}/100</b>\n\n"
        f"🎯 Entry: <code>{fmt_price(signal['entry'])}</code>\n"
        f"🛑 Stop Loss: <code>{fmt_price(signal['sl'])}</code>\n"
        f"🥇 TP1: <code>{fmt_price(signal['tp1'])}</code>\n"
        f"🥈 TP2: <code>{fmt_price(signal['tp2'])}</code>\n"
        f"🥉 TP3: <code>{fmt_price(signal['tp3'])}</code>\n\n"
        f"📈 RSI (15m): <b>{signal['rsi']:.1f}</b>\n"
        f"📦 Volume ratio: <b>{signal['volume_ratio']:.2f}x</b>\n"
        f"💵 Simulated capital: <b>{PAPER_CAPITAL:.2f} USDT</b>\n"
        f"⚙️ Simulated leverage: <b>{LEVERAGE}x</b>\n"
        f"📐 Hypothetical position value: <b>{POSITION_VALUE:.2f} USDT</b>\n\n"
        "⚠️ اعداد صرفاً آزمایشی‌اند؛ سفارش واقعی ارسال نمی‌شود.\n"
        f"🕒 {now_utc()}"
    )


def status_message(
    market_count,
    analyzed,
    errors,
    signals,
):
    return (
        "🐋 <b>ETH WHALE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>BITPIN SMART MARKET WATCH</b>\n"
        "🧪 PAPER MODE • REAL ORDERS OFF\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 Markets selected: <b>{market_count}</b>\n"
        f"🔎 Analyzed: <b>{analyzed}</b>\n"
        f"⚠️ Missing/error candle data: <b>{errors}</b>\n"
        f"📡 Signals found: <b>{signals}</b>\n\n"
        f"💵 Capital: <b>{PAPER_CAPITAL:.2f} USDT</b>\n"
        f"⚙️ Simulated leverage: <b>{LEVERAGE}x</b>\n"
        f"📐 Hypothetical position: <b>{POSITION_VALUE:.2f} USDT</b>\n"
        f"🕒 {now_utc()}\n\n"
        "اگر کندل‌ها دریافت نشوند، مسیر و قالب پاسخ API باید بررسی شود."
    )


# ---------------- MAIN ----------------

def main():
    logger.info("Starting %s", BOT_NAME)
    logger.info("Mode: PAPER ONLY | Real orders disabled")
    logger.info("Capital %.2f USDT | leverage %dx", PAPER_CAPITAL, LEVERAGE)

    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.error(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID."
        )
        raise SystemExit(1)

    try:
        markets = get_markets()
        tickers = get_tickers()

        if not markets:
            telegram_send(
                "🐋 <b>ETH WHALE</b>\n"
                "❌ دریافت فهرست بازارهای بیت‌پین ناموفق بود.\n"
                "گزارش GitHub Actions را بررسی کنید."
            )
            raise RuntimeError("No markets returned from Bitpin API.")

        if not tickers:
            telegram_send(
                "🐋 <b>ETH WHALE</b>\n"
                "❌ دریافت قیمت‌های بازار ناموفق بود."
            )
            raise RuntimeError("No tickers returned from Bitpin API.")

        market_list = build_markets(markets, tickers)
        logger.info("Markets chosen for analysis: %d", len(market_list))

        if not market_list:
            telegram_send(
                "🐋 <b>ETH WHALE</b>\n"
                "⚠️ هیچ بازار USDT با قیمت معتبر پیدا نشد.\n"
                "قالب پاسخ بازارها و تیکرها باید بررسی شود."
            )
            raise RuntimeError("No valid USDT markets.")

        signals = []
        analyzed = 0
        errors = 0

        for market in market_list:
            symbol = market["symbol"]

            candles15 = get_candles(symbol, "15m")
            time.sleep(REQUEST_DELAY)
            candles1h = get_candles(symbol, "1h")
            time.sleep(REQUEST_DELAY)

            if not candles15 or not candles1h:
                errors += 1
                continue

            analyzed += 1
            signal = evaluate_signal(symbol, candles15, candles1h)

            if signal:
                signals.append(signal)
                logger.info(
                    "Signal: %s %s score=%d",
                    symbol, signal["side"], signal["score"],
                )

        signals.sort(key=lambda s: s["score"], reverse=True)
        signals = signals[:MAX_SIGNALS_PER_SCAN]

        logger.info(
            "Scan complete: selected=%d analyzed=%d errors=%d signals=%d",
            len(market_list), analyzed, errors, len(signals),
        )

        # Send a scan summary every run.
        telegram_send(
            status_message(
                len(market_list),
                analyzed,
                errors,
                len(signals),
            )
        )

        if signals:
            for signal in signals:
                telegram_send(signal_message(signal))
                time.sleep(0.5)
        else:
            telegram_send(
                "🐋 <b>ETH WHALE</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "⏳ <b>WAIT — فعلاً سیگنال تأییدشده‌ای نیست</b>\n\n"
                "یا شروط روند هم‌جهت برقرار نیستند، یا دادهٔ کندل کافی نیست.\n"
                "برای تصمیم‌گیری، سیگنال اجباری تولید نمی‌شود."
            )

    except Exception:
        logger.exception("Bot run failed.")
        raise


if __name__ == "__main__":
    main()
