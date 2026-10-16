
import os
import time
import logging
import requests
from datetime import datetime, timezone

# ==========================================================
# BITPIN PAPER SIGNAL BOT - DIAGNOSTIC VERSION
# PAPER ONLY - NO REAL ORDERS
# ==========================================================

BASE_URL = "https://api.bitpin.ir"

CAPITAL = 48.0
LEVERAGE = 3
POSITION_SIZE = CAPITAL * LEVERAGE

MAX_MARKETS = 30
MAX_SIGNALS = 5
MIN_SCORE = 60
TIMEOUT = 8

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-Paper-Diagnostic-Bot/2.0"
})


def api_get(path, params=None):
    response = session.get(
        BASE_URL + path,
        params=params,
        timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram credentials not configured.")
        return False

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

        if response.json().get("ok"):
            return True

        logging.error("Telegram API returned ok=false")
    except Exception as exc:
        logging.error("Telegram send failed: %s", exc)

    return False


def number(value):
    try:
        result = float(value)
        if result > 0:
            return result
    except (TypeError, ValueError):
        pass

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
    last_error = "Unknown error"

    for path in (
        "/v1/mkt/markets/",
        "/api/v1/mkt/markets/"
    ):
        try:
            data = api_get(path)
            rows = extract_list(
                data, ("results", "markets", "data")
            )

            if rows:
                logging.info("Markets endpoint: %s", path)
                return rows

        except Exception as exc:
            last_error = str(exc)

    raise RuntimeError("Markets API failed: " + last_error)


def get_tickers():
    last_error = "Unknown error"

    for path in (
        "/v1/mkt/tickers/",
        "/api/v1/mkt/tickers/"
    ):
        try:
            data = api_get(path)

            if isinstance(data, dict):
                for key in ("tickers", "results", "data"):
                    value = data.get(key)

                    if isinstance(value, (list, dict)) and value:
                        logging.info("Tickers endpoint: %s", path)
                        return value

            if isinstance(data, list) and data:
                return data

        except Exception as exc:
            last_error = str(exc)

    raise RuntimeError("Ticker API failed: " + last_error)


def market_symbol(market):
    if not isinstance(market, dict):
        return ""

    for key in ("symbol", "market", "code"):
        if market.get(key):
            return str(market[key]).upper()

    return ""


def is_usdt_market(market):
    symbol = market_symbol(market)
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


def build_ticker_map(data):
    result = {}

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                result[str(key).upper()] = value

    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue

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
        value = number(ticker.get(key))
        if value:
            return value

    return None


def parse_candles(data):
    rows = extract_list(
        data,
        ("results", "candles", "data", "ohlcv")
    )

    closes = []
    timestamps = []

    for row in rows:
        if isinstance(row, dict):
            close = row.get("close")
            if close is None:
                close = row.get("c")

            stamp = (
                row.get("timestamp")
                or row.get("time")
                or row.get("start_time")
            )

        elif isinstance(row, (list, tuple)) and len(row) >= 5:
            # Common OHLCV layout:
            # [timestamp, open, high, low, close, volume]
            stamp = row[0]
            close = row[4]

        else:
            continue

        price = number(close)

        if price is not None:
            closes.append(price)
            timestamps.append(stamp)

    # Put candles in chronological order when timestamps
    # are available and numeric.
    if len(closes) >= 2:
        try:
            first = float(timestamps[0])
            last = float(timestamps[-1])

            if first > last:
                closes.reverse()
        except (TypeError, ValueError):
            pass

    return closes


def get_candles(symbol):
    market = normalize_symbol(symbol)

    # API variations are attempted for diagnosis.
    attempts = [
        (
            "/v1/mkt/ohlcv/",
            {"market": market, "interval": "1h"}
        ),
        (
            "/v1/mkt/candles/",
            {"market": market, "interval": "1h"}
        ),
        (
            "/api/v1/mkt/candles/",
            {"market": market, "interval": "1h"}
        ),
        (
            "/v1/mkt/ohlcv/",
            {"symbol": market, "interval": "1h"}
        ),
        (
            "/v1/mkt/candles/",
            {"symbol": market, "interval": "1h"}
        )
    ]

    errors = []

    for path, params in attempts:
        try:
            data = api_get(path, params)
            closes = parse_candles(data)

            if len(closes) >= 30:
                return closes, None

            errors.append(
                path + ": response had fewer than 30 usable candles"
            )

        except Exception as exc:
            errors.append(path + ": " + str(exc)[:100])

    return None, "; ".join(errors[:3])


def calculate_rsi(closes, period=14):
    if len(closes) <= period:
        return None

    changes = [
        closes[i] - closes[i - 1]
        for i in range(1, len(closes))
    ]

    recent = changes[-period:]

    gains = [max(change, 0) for change in recent]
    losses = [max(-change, 0) for change in recent]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    relative_strength = avg_gain / avg_loss

    return 100 - (100 / (1 + relative_strength))


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


def analyze_market(symbol, price, closes):
    # Replace last candle close with current ticker price.
    closes = list(closes)
    closes[-1] = price

    rsi_value = calculate_rsi(closes)
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)

    if rsi_value is None or ema9 is None or ema21 is None:
        return None, "indicators unavailable"

    long_score = 0
    short_score = 0

    if ema9 > ema21:
        long_score += 30
    elif ema9 < ema21:
        short_score += 30

    if price > ema9:
        long_score += 20
    elif price < ema9:
        short_score += 20

    if 50 <= rsi_value <= 68:
        long_score += 25
    elif 32 <= rsi_value < 50:
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
        return None, (
            f"score below threshold "
            f"(long={long_score}, short={short_score})"
        )

    if direction == "LONG":
        stop = price * 0.985
        targets = [
            price * 1.02,
            price * 1.03,
            price * 1.045
        ]
    else:
        stop = price * 1.015
        targets = [
            price * 0.98,
            price * 0.97,
            price * 0.955
        ]

    # POSITION_SIZE already includes simulated leverage.
    # Do not multiply by leverage again.
    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "price": price,
        "rsi": rsi_value,
        "ema9": ema9,
        "ema21": ema21,
        "stop": stop,
        "targets": targets,
        "stop_loss": POSITION_SIZE * 0.015,
        "target_pnl": [
            POSITION_SIZE * abs(target / price - 1)
            for target in targets
        ]
    }, None


def format_signal(s):
    t = s["targets"]
    pnl = s["target_pnl"]

    return (
        "BITPIN PAPER SIGNAL\n"
        "====================\n"
        f"Market: {s['symbol']}\n"
        f"Direction: {s['direction']}\n"
        f"Score: {s['score']}/100\n"
        f"Entry reference: {s['price']:.8g}\n"
        f"RSI: {s['rsi']:.2f}\n"
        f"EMA9: {s['ema9']:.8g}\n"
        f"EMA21: {s['ema21']:.8g}\n"
        "--------------------\n"
        f"SL: {s['stop']:.8g}\n"
        f"TP1: {t[0]:.8g}\n"
        f"TP2: {t[1]:.8g}\n"
        f"TP3: {t[2]:.8g}\n"
        "--------------------\n"
        f"Virtual capital: {CAPITAL:.2f} USDT\n"
        f"Leverage: {LEVERAGE}x (simulation)\n"
        f"Position notional: {POSITION_SIZE:.2f} USDT\n"
        f"Estimated SL P/L: -{s['stop_loss']:.2f} USDT\n"
        f"Estimated TP1 P/L: +{pnl[0]:.2f} USDT\n"
        f"Estimated TP2 P/L: +{pnl[1]:.2f} USDT\n"
        f"Estimated TP3 P/L: +{pnl[2]:.2f} USDT\n"
        "====================\n"
        "PAPER ONLY - REAL ORDERS OFF\n"
        "Fees, funding and slippage excluded."
    )


def scan_once():
    stats = {
        "markets": 0,
        "selected": 0,
        "ticker_records": 0,
        "prices": 0,
        "candles_ok": 0,
        "candles_failed": 0,
        "analyzed": 0,
        "long": 0,
        "short": 0,
        "low_score": 0,
        "errors": 0
    }

    reasons = {}
    signals = []

    print("\n" + "=" * 50)
    print("BITPIN PAPER BOT - DIAGNOSTIC SCAN")
    print(datetime.now(timezone.utc).isoformat())
    print("=" * 50)

    markets = get_markets()
    tickers = build_ticker_map(get_tickers())

    stats["markets"] = len(markets)
    stats["ticker_records"] = len(tickers)

    selected = [
        market for market in markets
        if is_usdt_market(market)
    ][:MAX_MARKETS]

    stats["selected"] = len(selected)

    print("Markets received:", stats["markets"])
    print("Ticker records:", stats["ticker_records"])
    print("USDT markets selected:", stats["selected"])

    for market in selected:
        symbol = market_symbol(market)

        if not symbol:
            stats["errors"] += 1
            continue

        ticker = tickers.get(symbol)
        if ticker is None:
            ticker = tickers.get(normalize_symbol(symbol))

        if ticker is None:
            stats["errors"] += 1
            reasons["ticker missing"] = (
                reasons.get("ticker missing", 0) + 1
            )
            continue

        price = get_price(ticker)

        if price is None:
            stats["errors"] += 1
            reasons["price missing"] = (
                reasons.get("price missing", 0) + 1
            )
            continue

        stats["prices"] += 1

        closes, candle_error = get_candles(symbol)

        if not closes:
            stats["candles_failed"] += 1
            reasons["candles unavailable"] = (
                reasons.get("candles unavailable", 0) + 1
            )

            if stats["candles_failed"] <= 2:
                print(
                    "CANDLE DEBUG:",
                    symbol,
                    candle_error
                )

            continue

        stats["candles_ok"] += 1
        stats["analyzed"] += 1

        signal, reason = analyze_market(symbol, price, closes)

        if signal is None:
            stats["low_score"] += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            continue

        signals.append(signal)

        if signal["direction"] == "LONG":
            stats["long"] += 1
        else:
            stats["short"] += 1

        print(
            "SIGNAL:",
            symbol,
            signal["direction"],
            "score=" + str(signal["score"])
        )

    signals.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    signals = signals[:MAX_SIGNALS]

    summary = [
        "BITPIN PAPER BOT - SCAN REPORT",
        "Mode: PAPER ONLY",
        "Real orders: OFF",
        f"Virtual capital: {CAPITAL:.2f} USDT",
        f"Simulated leverage: {LEVERAGE}x",
        "--------------------",
        f"Markets received: {stats['markets']}",
        f"USDT markets selected: {stats['selected']}",
        f"Ticker records: {stats['ticker_records']}",
        f"Markets with prices: {stats['prices']}",
        f"Valid candle sets: {stats['candles_ok']}",
        f"Candle failures: {stats['candles_failed']}",
        f"Markets analyzed: {stats['analyzed']}",
        f"LONG candidates: {stats['long']}",
        f"SHORT candidates: {stats['short']}",
        f"Below threshold: {stats['low_score']}",
        f"Other errors: {stats['errors']}"
    ]

    if reasons:
        summary.append("--------------------")
        summary.append("Skip reasons:")

        for reason, count in sorted(
            reasons.items(),
            key=lambda item: item[1],
            reverse=True
        )[:5]:
            summary.append(f"{reason}: {count}")

    if signals:
        summary.append("--------------------")
        summary.append(f"Signals sent: {len(signals)}")
    elif stats["candles_ok"] == 0:
        summary.append("--------------------")
        summary.append(
            "WARNING: No valid candles were parsed. "
            "Verify the Bitpin candle API."
        )
    else:
        summary.append("--------------------")
        summary.append("No qualifying signals in this scan.")

    report = "\n".join(summary)

    print("\n" + report)
    send_telegram(report)

    for signal in signals:
        message = format_signal(signal)
        print("\n" + message)
        send_telegram(message)
        time.sleep(1)


def main():
    print("BITPIN DIAGNOSTIC BOT STARTED")
    print("One scan per workflow run.")
    print("Capital:", CAPITAL, "USDT")
    print("Simulated leverage:", LEVERAGE, "x")
    print("Real orders: OFF")

    try:
        scan_once()
    except Exception as exc:
        logging.exception("Scan failed: %s", exc)
        send_telegram(
            "BITPIN PAPER BOT - SCAN FAILED\n"
            + str(exc)[:500]
            + "\nReal orders: OFF"
        )
        raise


if __name__ == "__main__":
    main()
