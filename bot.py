# ================================================================
# 🐋 ETH WHALE — OK-EX IRAN
# V11 — FINAL PAPER SIGNAL BOT
# ================================================================
# PAPER SIGNAL ONLY
# REAL ORDERS = OFF
#
# OK-EX IRAN API:
# https://sapi.ok-ex.io
#
# FEATURES:
# - ALL USDT MARKETS
# - TICKER + PAIR DISCOVERY
# - ROBUST MARKET FALLBACK
# - CANDLE SYMBOL FALLBACK
# - 1H CANDLES
# - EMA20 / EMA50
# - RSI14
# - MOMENTUM
# - VOLUME
# - BREAKOUT / BREAKDOWN
# - ATR STOP LOSS
# - TP1 / TP2 / TP3
# - TELEGRAM
#
# IMPORTANT:
# Liquidity/Volume Proxy is NOT real whale detection.
# No real orders are ever submitted.
#
# This script runs ONE scan and exits.
# GitHub Actions runs it every 5 minutes.
# ================================================================

import os
import time
import requests
from datetime import datetime


# ================================================================
# CONFIG
# ================================================================

BASE_URL = "https://sapi.ok-ex.io"

PAPER_MODE = True
REAL_ORDERS = False

CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100

MAX_MARKETS = 227
MAX_SIGNALS = 3

MIN_SCORE = 70
STRONG_SCORE = 80

MIN_VOLUME_RATIO = 1.20
STRONG_VOLUME_RATIO = 2.00

MIN_EDGE = 15

REQUEST_TIMEOUT = 20


# ================================================================
# TELEGRAM SECRETS
# ================================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")


# ================================================================
# HTTP SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Eth-Whale-OKEX-Iran-V11",
    "Accept": "application/json",
})


# ================================================================
# TELEGRAM
# ================================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN is missing")
        return False

    if not CHAT_ID:
        print("ERROR: CHAT_ID is missing")
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

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

        if response.status_code == 200:
            print("Telegram: OK")
            return True

        print(
            "Telegram ERROR:",
            response.status_code,
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "Telegram EXCEPTION:",
            repr(e)
        )

        return False


# ================================================================
# API REQUEST
# ================================================================

def api_get(path, params=None):

    url = BASE_URL + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            f"API {path} -> HTTP {response.status_code}"
        )

        if response.status_code != 200:

            print(
                response.text[:500]
            )

            return None

        try:
            return response.json()

        except Exception:

            print(
                "Invalid JSON:",
                response.text[:500]
            )

            return None

    except Exception as e:

        print(
            "API EXCEPTION:",
            path,
            repr(e)
        )

        return None


# ================================================================
# EXTRACT ROWS
# ================================================================

def extract_rows(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    keys = [
        "res",
        "data",
        "result",
        "rows",
        "list",
    ]

    for key in keys:

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            for key2 in keys:

                value2 = value.get(key2)

                if isinstance(value2, list):
                    return value2

    return []


# ================================================================
# SYMBOL NORMALIZATION
# ================================================================

def normalize_symbol(symbol):

    if symbol is None:
        return ""

    return (
        str(symbol)
        .upper()
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
        .replace(" ", "")
        .strip()
    )


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_rows(data)

    result = {}

    for row in rows:

        if not isinstance(row, dict):
            continue

        symbol = (
            row.get("symbol")
            or row.get("instId")
            or row.get("pair")
            or row.get("market")
        )

        symbol = normalize_symbol(symbol)

        if not symbol.endswith("USDT"):
            continue

        try:

            price = float(
                row.get("lastPrice")
                or row.get("last")
                or row.get("close")
                or row.get("price")
                or 0
            )

        except Exception:

            price = 0.0

        if price <= 0:
            continue

        try:

            quote_volume = float(
                row.get("quoteVolume")
                or row.get("quoteVol")
                or row.get("turnover")
                or 0
            )

        except Exception:

            quote_volume = 0.0

        result[symbol] = {
            "price": price,
            "quote_volume": quote_volume,
        }

    print(
        f"📡 Ticker USDT markets: {len(result)}"
    )

    return result


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    rows = extract_rows(data)

    result = []

    for row in rows:

        if isinstance(row, str):

            symbol = row

        elif isinstance(row, dict):

            symbol = (
                row.get("symbol")
                or row.get("instId")
                or row.get("pair")
                or row.get("market")
            )

        else:

            continue

        symbol = normalize_symbol(symbol)

        if symbol.endswith("USDT"):
            result.append(symbol)

    result = sorted(set(result))

    print(
        f"📋 Pair USDT markets: {len(result)}"
    )

    return result


# ================================================================
# MARKET DISCOVERY
# ================================================================

def discover_markets(tickers, pairs):

    ticker_set = set(tickers.keys())
    pair_set = set(pairs)

    print(
        f"Ticker set: {len(ticker_set)}"
    )

    print(
        f"Pair set: {len(pair_set)}"
    )

    # ------------------------------------------------------------
    # BOTH AVAILABLE
    # ------------------------------------------------------------

    if ticker_set and pair_set:

        intersection = (
            ticker_set &
            pair_set
        )

        print(
            f"Ticker/Pair intersection: "
            f"{len(intersection)}"
        )

        if len(intersection) >= 50:

            markets = intersection

        else:

            print(
                "⚠️ Intersection too small; "
                "using ticker markets."
            )

            markets = ticker_set

    # ------------------------------------------------------------
    # TICKER ONLY
    # ------------------------------------------------------------

    elif ticker_set:

        print(
            "⚠️ Pair API unavailable."
        )

        print(
            "Using ticker fallback."
        )

        markets = ticker_set

    # ------------------------------------------------------------
    # PAIR ONLY
    # ------------------------------------------------------------

    elif pair_set:

        print(
            "⚠️ Ticker API unavailable."
        )

        print(
            "Using pair fallback."
        )

        markets = pair_set

    else:

        markets = set()

    markets = sorted(
        x for x in markets
        if x.endswith("USDT")
    )

    return markets[:MAX_MARKETS]


# ================================================================
# CANDLE REQUEST
# ================================================================

def request_candles(symbol):

    now_ms = int(
        time.time() * 1000
    )

    start_ms = (
        now_ms
        -
        (
            120
            * 60
            * 60
            * 1000
        )
    )

    params = {
        "symbol": symbol,
        "interval": CANDLE_INTERVAL,
        "startTime": start_ms,
        "endTime": now_ms,
        "limit": CANDLE_LIMIT,
    }

    data = api_get(
        "/api/v1/spot/public/candles",
        params
    )

    return extract_rows(data)


# ================================================================
# PARSE CANDLES
# ================================================================

def parse_candles(rows):

    candles = []

    for row in rows:

        try:

            if isinstance(row, list):

                if len(row) < 5:
                    continue

                timestamp = row[0]
                op = row[1]
                high = row[2]
                low = row[3]
                close = row[4]

                volume = (
                    row[5]
                    if len(row) > 5
                    else 0
                )

            elif isinstance(row, dict):

                timestamp = (
                    row.get("timestamp")
                    or row.get("time")
                    or row.get("ts")
                )

                op = (
                    row.get("open")
                    or row.get("o")
                )

                high = (
                    row.get("high")
                    or row.get("h")
                )

                low = (
                    row.get("low")
                    or row.get("l")
                )

                close = (
                    row.get("close")
                    or row.get("c")
                )

                volume = (
                    row.get("volume")
                    or row.get("vol")
                    or row.get("v")
                    or 0
                )

            else:

                continue

            candles.append({
                "time": float(timestamp),
                "open": float(op),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
            })

        except Exception:

            continue

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ================================================================
# GET CANDLES WITH SYMBOL FALLBACK
# ================================================================

def get_candles(symbol):

    # First format:
    # BTCUSDT

    rows = request_candles(symbol)

    candles = parse_candles(rows)

    if candles:
        return candles

    # Second format:
    # BTC-USDT

    if symbol.endswith("USDT"):

        base = symbol[:-4]

        alternative = (
            base + "-USDT"
        )

        if alternative != symbol:

            print(
                f"🔁 Candle retry: "
                f"{alternative}"
            )

            rows = request_candles(
                alternative
            )

            candles = parse_candles(
                rows
            )

            if candles:
                return candles

    return []


# ================================================================
# EMA
# ================================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = (
        2 /
        (period + 1)
    )

    result = (
        sum(values[:period])
        /
        period
    )

    for value in values[period:]:

        result = (
            (
                value - result
            )
            * multiplier
        ) + result

    return result


# ================================================================
# RSI
# ================================================================

def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            -
            values[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(gains[:period])
        /
        period
    )

    avg_loss = (
        sum(losses[:period])
        /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                *
                (period - 1)
            )
            +
            gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                *
                (period - 1)
            )
            +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs_value = (
        avg_gain
        /
        avg_loss
    )

    return (
        100
        -
        (
            100 /
            (1 + rs_value)
        )
    )


# ================================================================
# ATR
# ================================================================

def atr(candles, period=14):

    if len(candles) <= period:
        return None

    true_ranges = []

    for i in range(
        1,
        len(candles)
    ):

        high = candles[i]["high"]
        low = candles[i]["low"]

        previous_close = (
            candles[i - 1]["close"]
        )

        tr = max(
            high - low,
            abs(
                high
                -
                previous_close
            ),
            abs(
                low
                -
                previous_close
            ),
        )

        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    return (
        sum(
            true_ranges[-period:]
        )
        /
        period
    )


# ================================================================
# ANALYSIS
# ================================================================

def analyze(
    symbol,
    candles,
    ticker
):

    if len(candles) < 60:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    highs = [
        x["high"]
        for x in candles
    ]

    lows = [
        x["low"]
        for x in candles
    ]

    volumes = [
        x["volume"]
        for x in candles
    ]

    price = ticker["price"]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    rsi_value = rsi(
        closes,
        14
    )

    atr_value = atr(
        candles,
        14
    )

    if (
        ema20 is None
        or
        ema50 is None
        or
        rsi_value is None
    ):
        return None

    # ------------------------------------------------------------
    # MOMENTUM
    # ------------------------------------------------------------

    momentum = (
        (
            closes[-1]
            -
            closes[-7]
        )
        /
        closes[-7]
    ) * 100

    # ------------------------------------------------------------
    # TREND
    # ------------------------------------------------------------

    trend10 = (
        (
            closes[-1]
            -
            closes[-11]
        )
        /
        closes[-11]
    ) * 100

    # ------------------------------------------------------------
    # VOLUME
    # ------------------------------------------------------------

    previous_volumes = (
        volumes[-21:-1]
    )

    if previous_volumes:

        avg_volume = (
            sum(previous_volumes)
            /
            len(previous_volumes)
        )

    else:

        avg_volume = 0

    if avg_volume > 0:

        volume_ratio = (
            volumes[-1]
            /
            avg_volume
        )

    else:

        volume_ratio = 0

    # ------------------------------------------------------------
    # BREAKOUT / BREAKDOWN
    # ------------------------------------------------------------

    previous_high = max(
        highs[-6:-1]
    )

    previous_low = min(
        lows[-6:-1]
    )

    breakout = (
        closes[-1]
        >
        previous_high
    )

    breakdown = (
        closes[-1]
        <
        previous_low
    )

    # ------------------------------------------------------------
    # SCORES
    # ------------------------------------------------------------

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # EMA20
    if price > ema20:

        long_score += 10

        long_reasons.append(
            "Price > EMA20"
        )

    else:

        short_score += 10

        short_reasons.append(
            "Price < EMA20"
        )

    # EMA50
    if ema20 > ema50:

        long_score += 15

        long_reasons.append(
            "EMA20 > EMA50"
        )

    else:

        short_score += 15

        short_reasons.append(
            "EMA20 < EMA50"
        )

    # RSI
    if 50 <= rsi_value <= 65:

        long_score += 10

        long_reasons.append(
            "Bullish RSI"
        )

    elif 35 <= rsi_value < 50:

        short_score += 10

        short_reasons.append(
            "Bearish RSI"
        )

    elif 65 < rsi_value <= 68:

        long_score += 5

        long_reasons.append(
            "Strong RSI"
        )

    elif 32 <= rsi_value < 35:

        short_score += 5

        short_reasons.append(
            "Weak RSI"
        )

    # MOMENTUM
    if 0 < momentum <= 12:

        long_score += 10

        long_reasons.append(
            f"Momentum +{momentum:.2f}%"
        )

    elif -12 <= momentum < 0:

        short_score += 10

        short_reasons.append(
            f"Momentum {momentum:.2f}%"
        )

    # TREND
    if trend10 > 0.5:

        long_score += 5

        long_reasons.append(
            "10-candle strength"
        )

    elif trend10 < -0.5:

        short_score += 5

        short_reasons.append(
            "10-candle weakness"
        )

    # VOLUME
    if volume_ratio >= STRONG_VOLUME_RATIO:

        if momentum > 0:

            long_score += 15

            long_reasons.append(
                f"Strong volume x{volume_ratio:.2f}"
            )

        elif momentum < 0:

            short_score += 15

            short_reasons.append(
                f"Strong volume x{volume_ratio:.2f}"
            )

    elif volume_ratio >= MIN_VOLUME_RATIO:

        if momentum > 0:

            long_score += 8

            long_reasons.append(
                f"Volume x{volume_ratio:.2f}"
            )

        elif momentum < 0:

            short_score += 8

            short_reasons.append(
                f"Volume x{volume_ratio:.2f}"
            )

    # BREAKOUT
    if breakout:

        long_score += 10

        long_reasons.append(
            "Breakout"
        )

    # BREAKDOWN
    if breakdown:

        short_score += 10

        short_reasons.append(
            "Breakdown"
        )

    # ------------------------------------------------------------
    # DIRECTION
    # ------------------------------------------------------------

    if long_score > short_score:

        direction = "LONG"
        score = long_score

        edge = (
            long_score
            -
            short_score
        )

        reasons = long_reasons

    elif short_score > long_score:

        direction = "SHORT"
        score = short_score

        edge = (
            short_score
            -
            long_score
        )

        reasons = short_reasons

    else:

        return None

    # ------------------------------------------------------------
    # STRICT FILTER
    # ------------------------------------------------------------

    if score < MIN_SCORE:
        return None

    if edge < MIN_EDGE:
        return None

    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    if direction == "LONG":

        if rsi_value < 50:
            return None

        if rsi_value > 68:
            return None

        if momentum <= 0:
            return None

        if momentum > 12:
            return None

        if ema20 <= ema50:
            return None

    else:

        if rsi_value < 32:
            return None

        if rsi_value > 50:
            return None

        if momentum >= 0:
            return None

        if abs(momentum) > 12:
            return None

        if ema20 >= ema50:
            return None

    # ------------------------------------------------------------
    # STOP DISTANCE
    # ------------------------------------------------------------

    if (
        atr_value is not None
        and
        price > 0
    ):

        atr_percent = (
            atr_value
            /
            price
        ) * 100

    else:

        atr_percent = 1.5

    stop_percent = max(
        1.5,
        min(
            atr_percent * 1.2,
            3.0
        )
    )

    stop_distance = (
        price
        *
        stop_percent
        /
        100
    )

    entry = price

    # ------------------------------------------------------------
    # LEVELS
    # ------------------------------------------------------------

    if direction == "LONG":

        sl = (
            entry
            -
            stop_distance
        )

        risk = (
            entry
            -
            sl
        )

        tp1 = (
            entry
            +
            risk
        )

        tp2 = (
            entry
            +
            risk * 2
        )

        tp3 = (
            entry
            +
            risk * 3
        )

    else:

        sl = (
            entry
            +
            stop_distance
        )

        risk = (
            sl
            -
            entry
        )

        tp1 = (
            entry
            -
            risk
        )

        tp2 = (
            entry
            -
            risk * 2
        )

        tp3 = (
            entry
            -
            risk * 3
        )

    rr = (
        abs(tp2 - entry)
        /
        abs(entry - sl)
    )

    if rr < 2:
        return None

    signal_type = (
        "🔥 STRONG"
        if score >= STRONG_SCORE
        else "⚡ SIGNAL"
    )

    return {
        "symbol": symbol,
        "direction": direction,
        "signal_type": signal_type,
        "score": score,
        "edge": edge,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "rsi": rsi_value,
        "ema20": ema20,
        "ema50": ema50,
        "momentum": momentum,
        "trend10": trend10,
        "volume_ratio": volume_ratio,
        "reasons": reasons,
    }


# ================================================================
# FORMAT PRICE
# ================================================================

def fmt(value):

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.6f}"

    if value >= 0.01:
        return f"{value:.6f}"

    if value >= 0.0001:
        return f"{value:.8f}"

    return f"{value:.10g}"


# ================================================================
# SIGNAL MESSAGE
# ================================================================

def make_signal_message(signal):

    if signal["direction"] == "LONG":
        direction_icon = "🟢"
    else:
        direction_icon = "🔴"

    reasons = "\n".join(
        "• " + x
        for x in signal["reasons"]
    )

    return f"""
{direction_icon} <b>{signal["signal_type"]} {signal["direction"]}</b>
━━━━━━━━━━━━━━━━━━

🪙 <b>{signal["symbol"]}</b>

📊 Score:
<b>{signal["score"]}/100</b>

📐 Edge:
<b>{signal["edge"]}</b>

🎯 Entry:
<b>{fmt(signal["entry"])}</b>

🛑 SL:
<b>{fmt(signal["sl"])}</b>

🥇 TP1:
<b>{fmt(signal["tp1"])}</b>

🥈 TP2:
<b>{fmt(signal["tp2"])}</b>

🥉 TP3:
<b>{fmt(signal["tp3"])}</b>

📐 R/R:
<b>1:{signal["rr"]:.2f}</b>

📈 RSI:
<b>{signal["rsi"]:.2f}</b>

EMA20:
<b>{fmt(signal["ema20"])}</b>

EMA50:
<b>{fmt(signal["ema50"])}</b>

🚀 Momentum:
<b>{signal["momentum"]:+.2f}%</b>

📊 Trend 10H:
<b>{signal["trend10"]:+.2f}%</b>

📊 Volume:
<b>x{signal["volume_ratio"]:.2f}</b>

🐋 Liquidity Proxy:
<b>ACTIVE</b>

🧠 <b>Reasons:</b>
{reasons}

━━━━━━━━━━━━━━━━━━

💵 <b>PAPER SIGNAL ONLY</b>
🔴 <b>REAL ORDERS: OFF</b>

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


# ================================================================
# SCAN
# ================================================================

def scan():

    print()
    print("=" * 70)
    print("🐋 ETH WHALE — OK-EX IRAN V11")
    print("=" * 70)

    print(
        "Paper Mode:",
        PAPER_MODE
    )

    print(
        "Real Orders:",
        REAL_ORDERS
    )

    tickers = get_tickers()

    pairs = get_pairs()

    markets = discover_markets(
        tickers,
        pairs
    )

    print()
    print(
        f"🪙 Markets checked: {len(markets)}"
    )

    # ------------------------------------------------------------
    # NO MARKET ERROR
    # ------------------------------------------------------------

    if not markets:

        message = """
⚠️ <b>OK-EX MARKET ERROR</b>

No USDT markets were returned.

Ticker discovery:
<b>0</b>

Pair discovery:
<b>0</b>

API:
<b>sapi.ok-ex.io</b>
"""

        print(message)

        send_telegram(message)

        return

    # ------------------------------------------------------------
    # CANDLE SCAN
    # ------------------------------------------------------------

    candle_ok = 0
    candle_failed = 0
    total_rows = 0

    analyses = []

    for index, symbol in enumerate(
        markets,
        1
    ):

        ticker = tickers.get(
            symbol
        )

        if not ticker:
            continue

        try:

            candles = get_candles(
                symbol
            )

        except Exception as e:

            print(
                "CANDLE ERROR:",
                symbol,
                repr(e)
            )

            candles = []

        if not candles:

            candle_failed += 1

            continue

        candle_ok += 1

        total_rows += len(
            candles
        )

        if len(candles) < 60:
            continue

        try:

            result = analyze(
                symbol,
                candles,
                ticker
            )

            if result:

                analyses.append(
                    result
                )

        except Exception as e:

            print(
                "ANALYSIS ERROR:",
                symbol,
                repr(e)
            )

        if index % 25 == 0:

            print(
                f"Progress: "
                f"{index}/{len(markets)}"
            )

    # ------------------------------------------------------------
    # SORT
    # ------------------------------------------------------------

    analyses.sort(
        key=lambda x: (
            x["score"],
            x["edge"],
            x["volume_ratio"],
        ),
        reverse=True
    )

    signals = analyses[
        :MAX_SIGNALS
    ]

    # ------------------------------------------------------------
    # SEND SIGNALS
    # ------------------------------------------------------------

    sent = 0

    for signal in signals:

        if send_telegram(
            make_signal_message(signal)
        ):

            sent += 1

        time.sleep(1)

    # ------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------

    average_candles = (
        total_rows / candle_ok
        if candle_ok
        else 0
    )

    summary = f"""
🔎 <b>SCAN COMPLETE — V11</b>
━━━━━━━━━━━━━━━━━━

🪙 Markets checked:
<b>{len(markets)}</b>

📡 Ticker markets:
<b>{len(tickers)}</b>

📋 Pair markets:
<b>{len(pairs)}</b>

🕯 Candle OK:
<b>{candle_ok}</b>

❌ Candle failed:
<b>{candle_failed}</b>

📚 Candle rows:
<b>{total_rows}</b>

📐 Avg candles:
<b>{average_candles:.1f}</b>

🧠 Analysis passed:
<b>{len(analyses)}</b>

🎯 Signals found:
<b>{len(signals)}</b>

📨 Signals sent:
<b>{sent}</b>

━━━━━━━━━━━━━━━━━━

🎯 Minimum Score:
<b>{MIN_SCORE}/100</b>

🔥 Strong Score:
<b>{STRONG_SCORE}/100</b>

📊 Minimum Volume:
<b>x{MIN_VOLUME_RATIO:.2f}</b>

📐 Minimum Edge:
<b>{MIN_EDGE}</b>

📐 Minimum R/R:
<b>1:2</b>

🟢 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    print(summary)

    send_telegram(summary)


# ================================================================
# MAIN
# ================================================================

if __name__ == "__main__":

    scan()

    print()
    print("✅ V11 SCAN FINISHED")
    print("No continuous loop.")
    print("GitHub Actions will run the next scan.")
