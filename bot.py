
# ============================================================
# ETH WHALE | BITPIN SPOT BOT
# Version 7.0
# Default: PAPER ONLY
# Real orders: disabled unless explicitly approved
# Spot only - no leverage - no withdrawals
# ============================================================

import os
import sys
import time
import json
import logging
import secrets
import statistics
from datetime import datetime, timezone

import requests

BOT_NAME = "🐋 ETH WHALE"
BASE_URL = "https://api.bitpin.ir"

# ---------------- CONFIGURATION ----------------

CAPITAL_USDT = 48.0
MAX_ORDER_USDT = 5.0
MAX_DAILY_ORDERS = 3
MAX_DAILY_LOSS_USDT = 2.0

MIN_SCORE = 65
MAX_MARKETS = 40
REQUEST_TIMEOUT = 20
RETRIES = 2

# Both values must be explicitly configured to allow live orders.
# Never enable these before paper testing.
LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "NO").strip().upper() == "YES"
)
LIVE_CONFIRMATION = os.getenv(
    "LIVE_CONFIRMATION", ""
).strip()

REQUIRED_CONFIRMATION = "I_APPROVE_SPOT_ORDERS"

API_KEY = os.getenv("BITPIN_API_KEY", "").strip()
API_SECRET = os.getenv("BITPIN_API_SECRET", "").strip()

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)
CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID", "").strip()
    or os.getenv("CHAT_ID", "").strip()
)

# Public API paths may change. Verify them against current
# Bitpin documentation before relying on live execution.
MARKETS_URLS = [
    f"{BASE_URL}/v1/mkt/markets/",
    f"{BASE_URL}/api/v1/mkt/markets/",
]

TICKER_URLS = [
    f"{BASE_URL}/v1/mkt/tickers/",
    f"{BASE_URL}/api/v1/mkt/tickers/",
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE/7.0",
    "Accept": "application/json",
})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ---------------- UTILITIES ----------------

def utc_now():
    return datetime.now(timezone.utc)


def notify(message):
    logging.info(message.replace("\n", " | "))

    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False

    try:
        response = SESSION.post(
            "https://api.telegram.org/bot"
            + TELEGRAM_TOKEN + "/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get("ok", False)
    except Exception as exc:
        logging.error("Telegram send failed: %s", exc)
        return False


def http_json(url, params=None):
    last_error = "Unknown error"

    for attempt in range(RETRIES + 1):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code in (400, 404, 405, 422):
                return None, f"HTTP {response.status_code}"

            response.raise_for_status()
            return response.json(), None

        except Exception as exc:
            last_error = str(exc)
            if attempt < RETRIES:
                time.sleep(1 + attempt * 2)

    return None, last_error


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_rows(data, keys):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

        for key in ("data", "result", "results"):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for subkey in keys:
                    if isinstance(value.get(subkey), list):
                        return value[subkey]

    return []


def normalize_symbol(value):
    return str(value or "").upper().strip().replace("/", "_")


def is_usdt_spot_symbol(symbol):
    symbol = normalize_symbol(symbol)

    if not symbol.endswith("_USDT"):
        return False

    if symbol in {
        "USDT_USDT", "USDC_USDT", "DAI_USDT",
        "TUSD_USDT", "FDUSD_USDT",
    }:
        return False

    return True


# ---------------- MARKET DATA ----------------

def get_markets():
    errors = []

    for url in MARKETS_URLS:
        data, error = http_json(url)

        if data is None:
            errors.append(f"{url}: {error}")
            continue

        rows = get_rows(
            data, ("markets", "pairs", "results", "data")
        )

        markets = []

        for item in rows:
            if isinstance(item, str):
                symbol = normalize_symbol(item)
                active = True
            elif isinstance(item, dict):
                symbol = normalize_symbol(
                    item.get("symbol")
                    or item.get("code")
                    or item.get("market")
                    or item.get("name")
                )

                status = str(item.get("status", "")).lower()
                active = (
                    item.get("is_active") is not False
                    and item.get("active") is not False
                    and status not in {
                        "inactive", "disabled", "closed",
                        "delisted",
                    }
                )

                quote = str(
                    item.get("quote_currency")
                    or item.get("quote")
                    or ""
                ).upper()

                if quote and quote != "USDT":
                    continue
            else:
                continue

            if active and is_usdt_spot_symbol(symbol):
                markets.append(symbol)

        if markets:
            return list(dict.fromkeys(markets))

    raise RuntimeError(
        "Could not retrieve markets: " + " | ".join(errors)
    )


def get_tickers():
    errors = []

    for url in TICKER_URLS:
        data, error = http_json(url)

        if data is None:
            errors.append(f"{url}: {error}")
            continue

        raw = data

        if isinstance(data, dict):
            raw = (
                data.get("tickers")
                or data.get("data")
                or data.get("results")
                or data.get("result")
                or data
            )

        result = {}

        if isinstance(raw, dict):
            items = []
            for symbol, value in raw.items():
                if isinstance(value, dict):
                    row = dict(value)
                    row.setdefault("symbol", symbol)
                    items.append(row)
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue

            symbol = normalize_symbol(
                item.get("symbol")
                or item.get("market")
                or item.get("name")
                or item.get("pair")
            )

            price = as_float(
                item.get("last_price")
                or item.get("last")
                or item.get("price")
                or item.get("close")
            )

            volume = as_float(
                item.get("quote_volume")
                or item.get("quoteVolume")
                or item.get("volume_quote")
                or item.get("volume")
            )

            if symbol and price > 0:
                result[symbol] = {
                    "price": price,
                    "volume": volume,
                }

        if result:
            return result

    raise RuntimeError(
        "Could not retrieve tickers: " + " | ".join(errors)
    )


# ---------------- CANDLES ----------------

def get_candles(symbol, timeframe):
    # Candle endpoint and response schema must be verified
    # against the current Bitpin API before live trading.
    compact = symbol.replace("_", "")
    interval = "15m" if timeframe == "15m" else "1h"

    urls = [
        f"{BASE_URL}/v1/mkt/ohlcv/{symbol}/",
        f"{BASE_URL}/v1/mkt/candles/{symbol}/",
        f"{BASE_URL}/api/v1/mkt/ohlcv/{symbol}/",
        f"{BASE_URL}/api/v1/mkt/candles/{symbol}/",
        f"{BASE_URL}/v1/mkt/ohlcv/{compact}/",
    ]

    last_error = "No valid candle response"

    for url in urls:
        for params in (
            {"interval": interval},
            {"timeframe": interval},
            {"resolution": interval},
        ):
            data, error = http_json(url, params)

            if data is None:
                last_error = error or last_error
                continue

            rows = get_rows(
                data, ("candles", "ohlcv", "klines", "data", "results")
            )

            candles = []

            for row in rows:
                try:
                    if isinstance(row, dict):
                        o = as_float(row.get("open", row.get("o")))
                        h = as_float(row.get("high", row.get("h")))
                        l = as_float(row.get("low", row.get("l")))
                        c = as_float(row.get("close", row.get("c")))
                        v = as_float(
                            row.get("volume", row.get("v"))
                        )
                    elif isinstance(row, (list, tuple)) and len(row) >= 5:
                        # Expected order: timestamp, open, high,
                        # low, close, volume
                        o, h, l, c = map(float, row[1:5])
                        v = as_float(row[5]) if len(row) > 5 else 0.0
                    else:
                        continue

                    if min(o, h, l, c) <= 0:
                        continue

                    candles.append({
                        "open": o, "high": h, "low": l,
                        "close": c, "volume": max(v, 0.0),
                    })
                except (TypeError, ValueError, IndexError):
                    continue

            if len(candles) >= 55:
                return candles[-100:]

            last_error = (
                f"Insufficient candles for {symbol} {timeframe}"
            )

    raise RuntimeError(
        f"Candle API failed for {symbol} {timeframe}: {last_error}"
    )


# ---------------- INDICATORS ----------------

def ema(values, period):
    if len(values) < period:
        return None

    result = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)

    for value in values[period:]:
        result = value * alpha + result * (1 - alpha)

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

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
        return 100.0

    return 100 - 100 / (1 + avg_gain / avg_loss)


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    ranges = []

    for i in range(1, len(candles)):
        cur = candles[i]
        prev = candles[i - 1]

        ranges.append(max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        ))

    return sum(ranges[-period:]) / period


def analyze(candles):
    closes = [x["close"] for x in candles]
    volumes = [x["volume"] for x in candles]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    r = rsi(closes)
    a = atr(candles)

    avg_volume = (
        statistics.mean(volumes[-21:-1])
        if len(volumes) >= 21 else 0
    )

    volume_ratio = (
        volumes[-1] / avg_volume if avg_volume > 0 else 0
    )

    return {
        "price": closes[-1],
        "ema20": e20,
        "ema50": e50,
        "rsi": r,
        "atr": a,
        "volume_ratio": volume_ratio,
    }


def build_signal(symbol, ticker):
    c15 = get_candles(symbol, "15m")
    c1h = get_candles(symbol, "1h")

    a = analyze(c15)
    b = analyze(c1h)

    long_score = 0
    short_score = 0

    if b["ema20"] > b["ema50"]:
        long_score += 25
    elif b["ema20"] < b["ema50"]:
        short_score += 25

    if a["ema20"] > a["ema50"]:
        long_score += 20
    elif a["ema20"] < a["ema50"]:
        short_score += 20

    if a["price"] > a["ema20"]:
        long_score += 10
    elif a["price"] < a["ema20"]:
        short_score += 10

    if 50 <= a["rsi"] <= 68:
        long_score += 15
    if 32 <= a["rsi"] <= 50:
        short_score += 15

    if 45 <= b["rsi"] <= 68:
        long_score += 10
    if 32 <= b["rsi"] <= 55:
        short_score += 10

    if a["volume_ratio"] >= 1.15:
        long_score += 10
        short_score += 10

    if a["rsi"] >= 75:
        long_score -= 15
    if a["rsi"] <= 25:
        short_score -= 15

    side = "BUY" if long_score >= short_score else "WAIT"
    score = max(long_score, short_score)

    if side != "BUY" or score < MIN_SCORE:
        return None

    price = a["price"]
    volatility = a["atr"] or price * 0.015

    stop = price - 1.5 * volatility
    target1 = price + 1.5 * volatility
    target2 = price + 2.5 * volatility

    # Never risk the entire account on one trade.
    # This is a paper plan, not a guaranteed loss limit.
    order_value = min(MAX_ORDER_USDT, CAPITAL_USDT * 0.10)

    return {
        "symbol": symbol,
        "side": side,
        "score": score,
        "price": price,
        "stop": stop,
        "tp1": target1,
        "tp2": target2,
        "order_value": order_value,
        "rsi15": a["rsi"],
        "volume_ratio": a["volume_ratio"],
    }


# ---------------- PAPER TRADING ----------------

def paper_message(signal):
    return (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧪 PAPER SPOT SIGNAL\n"
        f"Market: {signal['symbol']}\n"
        f"Signal: {signal['side']}\n"
        f"Score: {signal['score']}/100\n"
        f"Price: {signal['price']:.8g}\n"
        f"Virtual order value: {signal['order_value']:.2f} USDT\n"
        f"Stop reference: {signal['stop']:.8g}\n"
        f"TP1 reference: {signal['tp1']:.8g}\n"
        f"TP2 reference: {signal['tp2']:.8g}\n"
        f"RSI 15m: {signal['rsi15']:.1f}\n"
        f"Volume ratio: {signal['volume_ratio']:.2f}x\n"
        "Real order: OFF\n"
        "━━━━━━━━━━━━━━━━━━"
    )


# ---------------- LIVE TRADING GATE ----------------

def live_is_approved():
    return (
        LIVE_TRADING
        and LIVE_CONFIRMATION == REQUIRED_CONFIRMATION
        and bool(API_KEY)
        and bool(API_SECRET)
    )


def place_live_order(signal):
    """
    Deliberately fail closed.

    Before enabling live orders, the current Bitpin API must be
    verified for:
      - authentication and permissions
      - spot market ID and market precision
      - available USDT balance
      - minimum order value and amount
      - current ask price / slippage
      - duplicate-order protection
      - order status verification

    The bot does not submit an order until this function is
    connected to a verified and tested Bitpin SDK integration.
    """
    if not live_is_approved():
        return {
            "ok": False,
            "reason": "Live trading is not approved",
        }

    # No guessed endpoint, market ID, or order payload.
    # Safe default: refuse to place a real order.
    return {
        "ok": False,
        "reason": (
            "LIVE ORDER BLOCKED: Bitpin market metadata, "
            "balance, precision and order flow must be verified "
            "before real execution is enabled."
        ),
    }


# ---------------- MAIN SCAN ----------------

def main():
    mode = "LIVE REQUESTED" if LIVE_TRADING else "PAPER ONLY"

    startup = (
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "BITPIN SPOT MARKET WATCH\n"
        f"Mode: {mode}\n"
        f"Capital reference: {CAPITAL_USDT:.2f} USDT\n"
        f"Maximum order: {MAX_ORDER_USDT:.2f} USDT\n"
        "Leverage: OFF\n"
        "Withdrawals: NOT USED\n"
        f"Time: {utc_now().strftime('%Y-%m-%d %H:%M UTC')}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    notify(startup)

    try:
        markets = get_markets()
        tickers = get_tickers()

        candidates = [
            symbol for symbol in markets
            if symbol in tickers and tickers[symbol]["price"] > 0
        ]

        # Prioritize higher quote volume when the API provides it.
        candidates.sort(
            key=lambda s: tickers[s]["volume"],
            reverse=True,
        )
        candidates = candidates[:MAX_MARKETS]

        logging.info(
            "Markets=%d | tickers=%d | scanning=%d",
            len(markets), len(tickers), len(candidates),
        )

    except Exception as exc:
        notify(
            f"{BOT_NAME}\n"
            "❌ SCAN FAILED\n"
            f"Reason: {exc}\n"
            "Real orders: OFF"
        )
        raise

    signals = []
    errors = 0

    for symbol in candidates:
        try:
            signal = build_signal(symbol, tickers[symbol])

            if signal:
                signals.append(signal)

        except Exception as exc:
            errors += 1
            logging.warning(
                "Skipped %s: %s", symbol, exc
            )

        # Respect the API and reduce rate-limit risk.
        time.sleep(0.2)

    signals.sort(
        key=lambda x: x["score"],
        reverse=True,
    )
    signals = signals[:MAX_DAILY_ORDERS]

    if not signals:
        notify(
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 SCAN COMPLETED\n"
            f"Markets scanned: {len(candidates)}\n"
            f"Data errors: {errors}\n"
            "No signal passed the filter.\n"
            "🧪 Paper mode active\n"
            "🚫 No real order submitted"
        )
        return

    for signal in signals:
        if live_is_approved():
            result = place_live_order(signal)

            notify(
                paper_message(signal)
                + "\n\nLIVE EXECUTION RESULT:\n"
                + json.dumps(result, ensure_ascii=False)
            )
        else:
            notify(paper_message(signal))

    notify(
        f"{BOT_NAME}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "✅ SCAN COMPLETED\n"
        f"Signals: {len(signals)}\n"
        f"Markets scanned: {len(candidates)}\n"
        f"Data errors: {errors}\n"
        "Real order execution: BLOCKED\n"
        "━━━━━━━━━━━━━━━━━━"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Fatal bot error")
        sys.exit(1)
