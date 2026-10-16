
import os
import time
import logging
import requests
from datetime import datetime, timezone

# =========================================================
# BITPIN PAPER SIGNAL BOT
# PAPER TRADING ONLY - NO REAL ORDERS
# =========================================================

BASE_URL = "https://api.bitpin.ir"

CAPITAL = 48.0
LEVERAGE = 3
POSITION_SIZE = CAPITAL * LEVERAGE

MAX_MARKETS = 100
MAX_SIGNALS = 5
MIN_SCORE = 60
SCAN_INTERVAL = 300
TIMEOUT = 15

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

http = requests.Session()
http.headers.update({"User-Agent": "Bitpin-Paper-Bot/1.0"})


def api_get(path, params=None):
    response = http.get(
        BASE_URL + path,
        params=params,
        timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram not configured.")
        return

    try:
        response = requests.post(
            "https://api.telegram.org/bot"
            + TELEGRAM_TOKEN
            + "/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=TIMEOUT
        )
        response.raise_for_status()

        if not response.json().get("ok"):
            logging.error("Telegram did not accept message.")

    except Exception as exc:
        logging.error("Telegram error: %s", exc)


def as_float(value):
    try:
        result = float(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def extract_list(data, keys):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def get_markets():
    last_error = None

    for path in (
        "/v1/mkt/markets/",
        "/api/v1/mkt/markets/"
    ):
        try:
            data = api_get(path)
            markets = extract_list(
                data, ("results", "markets", "data")
            )
            if markets:
                return markets
        except Exception as exc:
            last_error = exc

    raise RuntimeError("Markets API failed: " + str(last_error))


def get_tickers():
    last_error = None

    for path in (
        "/v1/mkt/tickers/",
        "/api/v1/mkt/tickers/"
    ):
        try:
            data = api_get(path)

            if isinstance(data, dict):
                for key in ("tickers", "results", "data"):
                    value = data.get(key)

                    if isinstance(value, (dict, list)) and value:
                        return value

            if isinstance(data, list) and data:
                return data

        except Exception as exc:
            last_error = exc

    raise RuntimeError("Ticker API failed: " + str(last_error))


def get_symbol(market):
    if not isinstance(market, dict):
        return ""

    for key in ("symbol", "market", "code"):
        if market.get(key):
            return str(market[key]).upper()

    return ""


def is_usdt_market(market):
    symbol = get_symbol(market)

    quote = str(
        market.get("quote_currency")
        or market.get("quote")
        or ""
    ).upper()

    return (
        quote == "USDT"
        or symbol.endswith("-USDT")
        or symbol.endswith("_USDT")
        or symbol.endswith("/USDT")
    )


def normalize_symbol(symbol):
    return (
        symbol.upper()
        .replace("/", "_")
        .replace("-", "_")
    )


def make_ticker_map(data):
    result = {}

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                result[str(key).upper()] = value

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                symbol = (
                    item.get("symbol")
                    or item.get("market")
                    or item.get("code")
                )
                if symbol:
                    result[str(symbol).upper()] = item

    return result


def get_price(ticker):
    if not isinstance(ticker, dict):
        return None

    for key in (
        "last",
        "last_price",
        "price",
        "close",
        "lastPrice"
    ):
        value = as_float(ticker.get(key))
        if value:
            return value

    return None


def get_candles(symbol):
    """
    Try common candle endpoint formats.
    The endpoint and response format must be verified
    against the current Bitpin API.
    """

    market = normalize_symbol(symbol)

    paths = (
        "/v1/mkt/ohlcv/",
        "/v1/mkt/candles/",
        "/api/v1/mkt/candles/"
    )

    for path in paths:
        for params in (
            {"market": market, "interval": "1h", "limit": 100},
            {"symbol": market, "interval": "1h", "limit": 100}
        ):
            try:
                data = api_get(path, params)

                rows = extract_list(
                    data, ("results", "candles", "data", "ohlcv")
                )

                closes = []

                for row in rows:
                    if isinstance(row, dict):
                        value = row.get("close", row.get("c"))

                    elif isinstance(row, (list, tuple)) and len(row) >= 5:
                        value = row[4]

                    else:
                        continue

                    price = as_float(value)
                    if price:
                        closes.append(price)

                if len(closes) >= 30:
                    return closes

            except Exception:
                continue

    return None


def calculate_rsi(closes, period=14):
    if len(closes) <= period:
        return None

    changes = [
        closes[i] - closes[i - 1]
        for i in range(1, len(closes))
    ]

    recent = changes[-period:]

    gains = [max(x, 0) for x in recent]
    losses = [max(-x, 0) for x in recent]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ema(values, period):
    if len(values) < period:
        return None

    current = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for value in values[period:]:
        current = (
            value * multiplier
            + current * (1 - multiplier)
        )

    return current


def analyze_market(symbol, current_price):
    closes = get_candles(symbol)

    if not closes or len(closes) < 30:
        return None

    closes[-1] = current_price

    rsi_value = calculate_rsi(closes, 14)
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)

    if rsi_value is None or ema9 is None or ema21 is None:
        return None

    long_score = 0
    short_score = 0

    if ema9 > ema21:
        long_score += 30
    elif ema9 < ema21:
        short_score += 30

    if current_price > ema9:
        long_score += 20
    elif current_price < ema9:
        short_score += 20

    if 50 <= rsi_value <= 68:
        long_score += 25

    if 32 <= rsi_value < 50:
        short_score += 25

    if closes[-1] > closes[-2]:
        long_score += 15
    elif closes[-1] < closes[-2]:
        short_score += 15

    if closes[-1] > closes[-4]:
        long_score += 10
    elif closes[-1] < closes[-4]:
        short_score += 10

    if long_score >= short_score:
        direction = "LONG"
        score = long_score
    else:
        direction = "SHORT"
        score = short_score

    if score < MIN_SCORE:
        return None

    if direction == "LONG":
        stop = current_price * 0.985
        targets = [
            current_price * 1.02,
            current_price * 1.03,
            current_price * 1.045
        ]
    else:
        stop = current_price * 1.015
        targets = [
            current_price * 0.98,
            current_price * 0.97,
            current_price * 0.955
        ]

    # Approximate P/L on a 144 USDT notional position.
    # Do not multiply by leverage a second time.
    stop_loss = POSITION_SIZE * 0.015

    target_pnl = [
        POSITION_SIZE * abs(target / current_price - 1)
        for target in targets
    ]

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "price": current_price,
        "rsi": rsi_value,
        "ema9": ema9,
        "ema21": ema21,
        "stop": stop,
        "targets": targets,
        "stop_loss": stop_loss,
        "target_pnl": target_pnl
    }


def format_signal(s):
    t = s["targets"]
    p = s["target_pnl"]

    return (
        "BITPIN PAPER SIGNAL\n"
        "========================\n"
        f"Market: {s['symbol']}\n"
        f"Signal: {s['direction']}\n"
        f"Score: {s['score']}/100\n"
        f"Entry reference: {s['price']:.8g}\n"
        f"RSI 14: {s['rsi']:.2f}\n"
        f"EMA 9: {s['ema9']:.8g}\n"
        f"EMA 21: {s['ema21']:.8g}\n"
        "------------------------\n"
        f"Stop Loss: {s['stop']:.8g}\n"
        f"TP1: {t[0]:.8g}\n"
        f"TP2: {t[1]:.8g}\n"
        f"TP3: {t[2]:.8g}\n"
        "------------------------\n"
        f"Virtual capital: {CAPITAL:.2f} USDT\n"
        f"Simulated leverage: {LEVERAGE}x\n"
        f"Position notional: {POSITION_SIZE:.2f} USDT\n"
        f"Estimated SL P/L: -{s['stop_loss']:.2f} USDT\n"
        f"Estimated TP1 P/L: +{p[0]:.2f} USDT\n"
        f"Estimated TP2 P/L: +{p[1]:.2f} USDT\n"
        f"Estimated TP3 P/L: +{p[2]:.2f} USDT\n"
        "========================\n"
        "Mode: PAPER ONLY\n"
        "Real orders: OFF\n"
        "Fees and slippage excluded."
    )


def scan_once():
    print("\nStarting market scan...")
    print("UTC time:", datetime.now(timezone.utc).isoformat())

    markets = get_markets()
    tickers = make_ticker_map(get_tickers())

    selected = [
        market for market in markets
        if is_usdt_market(market)
    ][:MAX_MARKETS]

    print("Markets received:", len(markets))
    print("USDT markets selected:", len(selected))
    print("Ticker records:", len(tickers))

    signals = []

    for market in selected:
        symbol = get_symbol(market)

        if not symbol:
            continue

        ticker = tickers.get(symbol)
        if ticker is None:
            ticker = tickers.get(normalize_symbol(symbol))

        if ticker is None:
            continue

        price = get_price(ticker)
        if price is None:
            continue

        try:
            signal = analyze_market(symbol, price)

            if signal:
                signals.append(signal)
                print(
                    "Candidate:",
                    symbol,
                    signal["direction"],
                    signal["score"]
                )

        except Exception as exc:
            logging.warning("%s: %s", symbol, exc)

    signals.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    signals = signals[:MAX_SIGNALS]

    if not signals:
        message = (
            "BITPIN PAPER BOT\n"
            "Scan completed.\n"
            "No qualifying signals found.\n"
            "Real orders: OFF"
        )
        print(message)
        send_telegram(message)
        return

    for signal in signals:
        message = format_signal(signal)
        print("\n" + message)
        send_telegram(message)
        time.sleep(1)


def main():
    print("BITPIN PAPER SIGNAL BOT STARTED")
    print("Capital:", CAPITAL, "USDT")
    print("Leverage:", LEVERAGE, "x")
    print("Position notional:", POSITION_SIZE, "USDT")
    print("Real orders: OFF")

    while True:
        try:
            scan_once()

        except KeyboardInterrupt:
            print("Bot stopped.")
            break

        except Exception as exc:
            logging.exception("Scan failed: %s", exc)

            send_telegram(
                "BITPIN PAPER BOT\n"
                "Market scan failed.\n"
                "Check the execution log.\n"
                "Real orders: OFF"
            )

        print("Next scan in", SCAN_INTERVAL, "seconds.")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
