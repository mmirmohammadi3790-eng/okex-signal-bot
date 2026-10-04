# ================================================================
# 🐋 ETH WHALE — OK-EX IRAN V13
# PAPER SIGNAL BOT — ALL USDT MARKETS
# ================================================================

import os
import time
import requests
from datetime import datetime, timedelta

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
MIN_EDGE = 15

REQUEST_TIMEOUT = 20

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
})


# ================================================================
# STATS
# ================================================================

STATS = {
    "pairs": 0,
    "tickers": 0,
    "ticker_failed": 0,
    "candle_ok": 0,
    "candle_failed": 0,
    "candle_rows": 0,
    "analysis_passed": 0,
    "signals_found": 0,
    "signals_sent": 0,
}


# ================================================================
# TIME
# ================================================================

def utc_now():
    return datetime.utcnow()


def now_text():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


# ================================================================
# HTTP
# ================================================================

def get_json(path, params=None):

    url = BASE_URL + path

    try:

        r = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code != 200:

            print(
                f"[HTTP ERROR] {path} -> "
                f"{r.status_code}"
            )

            print(r.text[:1000])

            return None

        try:
            return r.json()

        except Exception:

            print("[JSON ERROR]")
            print(r.text[:1000])

            return None

    except Exception as e:

        print(
            f"[REQUEST ERROR] "
            f"{path}: {e}"
        )

        return None


# ================================================================
# TELEGRAM
# ================================================================

def telegram(message):

    if not TELEGRAM_TOKEN or not CHAT_ID:

        print(
            "[TELEGRAM ERROR] "
            "Missing token/chat id"
        )

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:

        r = SESSION.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code == 200:

            STATS["signals_sent"] += 1

            return True

        print(
            "[TELEGRAM ERROR]",
            r.status_code
        )

        print(r.text[:500])

        return False

    except Exception as e:

        print(
            "[TELEGRAM REQUEST ERROR]",
            e
        )

        return False


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    print("")
    print("[1] Loading pairs...")

    data = get_json(
        "/api/v1/spot/public/pairs"
    )

    if not data:
        return []

    print(
        "[PAIR RESPONSE]",
        str(data)[:500]
    )

    result = None

    if isinstance(data, dict):

        result = (
            data.get("res")
            or data.get("data")
            or data.get("result")
        )

    elif isinstance(data, list):

        result = data

    if not isinstance(result, list):

        print(
            "[PAIR ERROR] "
            "Unknown format"
        )

        return []

    symbols = []

    for item in result:

        symbol = None

        if isinstance(item, dict):

            symbol = (
                item.get("symbol")
                or item.get("pair")
                or item.get("market")
                or item.get("instId")
            )

        elif isinstance(item, str):

            symbol = item

        if not symbol:
            continue

        symbol = str(symbol).upper()

        symbol = (
            symbol
            .replace("/", "-")
            .replace("_", "-")
        )

        # فقط USDT markets
        if not symbol.endswith("-USDT"):
            continue

        if symbol not in symbols:
            symbols.append(symbol)

    symbols = symbols[:MAX_MARKETS]

    STATS["pairs"] = len(symbols)

    print(
        f"[PAIR OK] "
        f"{len(symbols)} USDT markets"
    )

    return symbols


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    print("")
    print("[2] Loading tickers...")

    data = get_json(
        "/api/v1/spot/public/tickers"
    )

    if not data:

        STATS["ticker_failed"] += 1

        return {}

    print(
        "[TICKER RESPONSE]",
        str(data)[:500]
    )

    # ------------------------------------------------------------
    # IMPORTANT:
    # REAL OK-EX RESPONSE:
    #
    # {
    #   "tickers": [...]
    # }
    # ------------------------------------------------------------

    result = None

    if isinstance(data, dict):

        if isinstance(
            data.get("tickers"),
            list
        ):
            result = data["tickers"]

        elif isinstance(
            data.get("res"),
            list
        ):
            result = data["res"]

        elif isinstance(
            data.get("data"),
            list
        ):
            result = data["data"]

        elif isinstance(
            data.get("result"),
            list
        ):
            result = data["result"]

    elif isinstance(data, list):

        result = data

    if not isinstance(result, list):

        print(
            "[TICKER ERROR] "
            "Unknown format"
        )

        STATS["ticker_failed"] += 1

        return {}

    tickers = {}

    for item in result:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("pair")
            or item.get("market")
            or item.get("instId")
        )

        if not symbol:
            continue

        symbol = str(symbol).upper()

        symbol = (
            symbol
            .replace("/", "-")
            .replace("_", "-")
        )

        if not symbol.endswith("-USDT"):
            continue

        tickers[symbol] = item

    STATS["tickers"] = len(tickers)

    print(
        f"[TICKER OK] "
        f"{len(tickers)} USDT tickers"
    )

    return tickers


# ================================================================
# TICKER PRICE
# ================================================================

def get_price(ticker):

    if not isinstance(ticker, dict):
        return None

    fields = [
        "lastPrice",
        "last",
        "price",
        "close",
        "c"
    ]

    for field in fields:

        value = ticker.get(field)

        if value is None:
            continue

        try:

            price = float(value)

            if price > 0:
                return price

        except Exception:
            pass

    return None


# ================================================================
# CANDLES
# ================================================================

def get_candles(symbol):

    # ------------------------------------------------------------
    # OK-EX requires start_time + end_time
    # ------------------------------------------------------------

    end_dt = utc_now()

    start_dt = (
        end_dt -
        timedelta(
            hours=CANDLE_LIMIT + 5
        )
    )

    # milliseconds
    start_time = int(
        start_dt.timestamp() * 1000
    )

    end_time = int(
        end_dt.timestamp() * 1000
    )

    params = {
        "symbol": symbol,
        "interval": CANDLE_INTERVAL,
        "limit": CANDLE_LIMIT,
        "start_time": start_time,
        "end_time": end_time,
    }

    data = get_json(
        "/api/v1/spot/public/candles",
        params=params
    )

    if not data:
        return []

    result = None

    if isinstance(data, dict):

        result = data.get("res")

        if result is None:
            result = data.get("data")

        if result is None:
            result = data.get("result")

        if result is None:
            result = data.get("candles")

    elif isinstance(data, list):

        result = data

    if not isinstance(result, list):

        print(
            f"[CANDLE FORMAT ERROR] "
            f"{symbol}"
        )

        print(
            str(data)[:700]
        )

        return []

    candles = []

    for row in result:

        try:

            # ----------------------------------------------------
            # Array format
            # ----------------------------------------------------

            if isinstance(row, list):

                if len(row) < 5:
                    continue

                timestamp = float(row[0])

                open_price = float(row[1])
                high = float(row[2])
                low = float(row[3])
                close = float(row[4])

                volume = 0.0

                if len(row) >= 6:

                    try:
                        volume = float(row[5])

                    except Exception:
                        volume = 0.0

                candles.append({
                    "time": timestamp,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume
                })

            # ----------------------------------------------------
            # Dictionary format
            # ----------------------------------------------------

            elif isinstance(row, dict):

                open_price = (
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
                    or row.get("v")
                    or 0
                )

                if (
                    open_price is None
                    or high is None
                    or low is None
                    or close is None
                ):
                    continue

                candles.append({
                    "time": row.get(
                        "timestamp",
                        row.get("time", 0)
                    ),
                    "open": float(open_price),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume)
                })

        except Exception:

            continue

    return candles


# ================================================================
# EMA
# ================================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = (
        2 / (period + 1)
    )

    value = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        value = (
            (price - value)
            * multiplier
            + value
        )

    return value


# ================================================================
# RSI
# ================================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (100 / (1 + rs))
    )


# ================================================================
# ATR
# ================================================================

def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"]
            - current["low"],

            abs(
                current["high"]
                - previous["close"]
            ),

            abs(
                current["low"]
                - previous["close"]
            )
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return (
        sum(trs[-period:])
        / period
    )


# ================================================================
# ANALYSIS
# ================================================================

def analyze(symbol, candles):

    if len(candles) < 60:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    volumes = [
        x["volume"]
        for x in candles
    ]

    price = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    rsi14 = rsi(
        closes,
        14
    )

    atr14 = atr(
        candles,
        14
    )

    if (
        ema20 is None
        or ema50 is None
        or rsi14 is None
        or atr14 is None
        or atr14 <= 0
    ):
        return None

    # ------------------------------------------------------------
    # Momentum
    # ------------------------------------------------------------

    momentum = 0.0

    if len(closes) >= 11:

        old_price = closes[-11]

        if old_price > 0:

            momentum = (
                (price - old_price)
                / old_price
            ) * 100

    # ------------------------------------------------------------
    # Volume ratio
    # ------------------------------------------------------------

    previous_volumes = (
        volumes[-21:-1]
    )

    avg_volume = 0.0

    if previous_volumes:

        avg_volume = (
            sum(previous_volumes)
            / len(previous_volumes)
        )

    if avg_volume > 0:

        volume_ratio = (
            volumes[-1]
            / avg_volume
        )

    else:

        volume_ratio = 0.0

    # ------------------------------------------------------------
    # Trend
    # ------------------------------------------------------------

    score_long = 0
    score_short = 0

    if price > ema20:
        score_long += 15

    if ema20 > ema50:
        score_long += 15

    if price < ema20:
        score_short += 15

    if ema20 < ema50:
        score_short += 15

    # RSI

    if 50 <= rsi14 <= 70:
        score_long += 15

    if 30 <= rsi14 < 50:
        score_short += 15

    # Momentum

    if momentum > 1:
        score_long += 15

    if momentum < -1:
        score_short += 15

    # Volume

    if volume_ratio >= MIN_VOLUME_RATIO:

        if score_long > score_short:
            score_long += 15

        elif score_short > score_long:
            score_short += 15

    # Price action

    previous_high = max(
        closes[-11:-1]
    )

    previous_low = min(
        closes[-11:-1]
    )

    if price > previous_high:
        score_long += 15

    if price < previous_low:
        score_short += 15

    # ------------------------------------------------------------
    # Direction
    # ------------------------------------------------------------

    if score_long >= score_short:

        direction = "LONG"
        score = score_long

    else:

        direction = "SHORT"
        score = score_short

    edge = abs(
        score_long
        - score_short
    )

    # ------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------

    if score < MIN_SCORE:
        return None

    if edge < MIN_EDGE:
        return None

    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    # ------------------------------------------------------------
    # Entry / SL / TP
    # ------------------------------------------------------------

    risk = max(
        atr14 * 1.5,
        price * 0.008
    )

    entry = price

    if direction == "LONG":

        sl = entry - risk

        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3

    else:

        sl = entry + risk

        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    STATS[
        "analysis_passed"
    ] += 1

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "edge": edge,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": rsi14,
        "volume_ratio": volume_ratio,
        "momentum": momentum
    }


# ================================================================
# SIGNAL MESSAGE
# ================================================================

def make_signal_message(signal):

    if signal["direction"] == "LONG":

        emoji = "🟢"

    else:

        emoji = "🔴"

    if signal["score"] >= STRONG_SCORE:

        strength = "🔥 STRONG SIGNAL"

    else:

        strength = "⚡ SIGNAL"

    return f"""
🐋 <b>ETH WHALE — OK-EX IRAN V13</b>

{emoji} <b>{signal["direction"]}</b>
{strength}

🪙 <b>{signal["symbol"]}</b>

🎯 Score:
<b>{signal["score"]}/100</b>

📐 Edge:
<b>{signal["edge"]}</b>

💰 Entry:
<b>{signal["entry"]:.8g}</b>

🛑 SL:
<b>{signal["sl"]:.8g}</b>

🎯 TP1:
<b>{signal["tp1"]:.8g}</b>

🎯 TP2:
<b>{signal["tp2"]:.8g}</b>

🎯 TP3:
<b>{signal["tp3"]:.8g}</b>

📊 RSI:
<b>{signal["rsi"]:.2f}</b>

📈 Volume:
<b>x{signal["volume_ratio"]:.2f}</b>

📈 Momentum:
<b>{signal["momentum"]:.2f}%</b>

🟢 Paper Mode: ON
🔴 Real Orders: OFF

⏰ {now_text()}
"""


# ================================================================
# SCAN
# ================================================================

def scan():

    print("")
    print("=" * 60)
    print("🐋 OK-EX IRAN V13")
    print("=" * 60)

    symbols = get_pairs()

    if not symbols:

        telegram(
            "🚨 <b>OK-EX ERROR</b>\n\n"
            "No USDT markets found."
        )

        return

    tickers = get_tickers()

    signals = []

    # ------------------------------------------------------------
    # Scan all markets
    # ------------------------------------------------------------

    for index, symbol in enumerate(
        symbols,
        start=1
    ):

        print(
            f"[{index}/{len(symbols)}] "
            f"{symbol}"
        )

        # Candle

        candles = get_candles(
            symbol
        )

        if not candles:

            STATS[
                "candle_failed"
            ] += 1

            continue

        STATS[
            "candle_ok"
        ] += 1

        STATS[
            "candle_rows"
        ] += len(candles)

        # Analysis

        signal = analyze(
            symbol,
            candles
        )

        if signal:

            signals.append(
                signal
            )

            STATS[
                "signals_found"
            ] += 1

    # ------------------------------------------------------------
    # Sort
    # ------------------------------------------------------------

    signals.sort(
        key=lambda x: (
            x["score"],
            x["edge"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    # ------------------------------------------------------------
    # Send best signals
    # ------------------------------------------------------------

    selected = signals[
        :MAX_SIGNALS
    ]

    for signal in selected:

        telegram(
            make_signal_message(
                signal
            )
        )

    # ------------------------------------------------------------
    # Average candles
    # ------------------------------------------------------------

    if STATS["candle_ok"] > 0:

        avg_candles = (
            STATS["candle_rows"]
            / STATS["candle_ok"]
        )

    else:

        avg_candles = 0

    # ------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------

    summary = f"""
🔎 <b>SCAN COMPLETE — V13</b>
━━━━━━━━━━━━━━━━━━

🪙 Markets checked:
<b>{len(symbols)}</b>

📡 Ticker markets:
<b>{len(tickers)}</b>

📋 Pair markets:
<b>{STATS["pairs"]}</b>

🕯 Candle OK:
<b>{STATS["candle_ok"]}</b>

❌ Candle failed:
<b>{STATS["candle_failed"]}</b>

📚 Candle rows:
<b>{STATS["candle_rows"]}</b>

📐 Avg candles:
<b>{avg_candles:.1f}</b>

🧠 Analysis passed:
<b>{STATS["analysis_passed"]}</b>

🎯 Signals found:
<b>{STATS["signals_found"]}</b>

📨 Signals sent:
<b>{len(selected)}</b>

━━━━━━━━━━━━━━━━━━

🎯 Minimum Score:
<b>{MIN_SCORE}/100</b>

🔥 Strong Score:
<b>{STRONG_SCORE}/100</b>

📊 Minimum Volume:
<b>x{MIN_VOLUME_RATIO:.2f}</b>

📐 Minimum Edge:
<b>{MIN_EDGE}</b>

🟢 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

⏰ {now_text()}
"""

    telegram(summary)

    print(summary)


# ================================================================
# MAIN
# ================================================================

if __name__ == "__main__":

    print(
        "🐋 OK-EX IRAN V13 STARTED"
    )

    print(
        "PAPER MODE:",
        PAPER_MODE
    )

    print(
        "REAL ORDERS:",
        REAL_ORDERS
    )

    print(
        "BASE:",
        BASE_URL
    )

    try:

        scan()

    except Exception as e:

        print(
            "[FATAL ERROR]",
            repr(e)
        )

        telegram(
            "🚨 <b>BOT FATAL ERROR</b>\n\n"
            f"<code>{str(e)[:1000]}</code>"
        )

    print("")
    print(
        "🐋 BOT FINISHED"
    )
