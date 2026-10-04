# ================================================================
# 🐋 ETH WHALE — OK-EX IRAN V15
# PAPER SIGNAL BOT
# ALL USDT MARKETS
# LONG / SHORT / WAIT
# RSI / EMA / MOMENTUM / VOLUME / PRICE ACTION / WHALE PROXY
# NO REAL ORDERS
# ================================================================

import os
import time
import statistics
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

MIN_SCORE = 72
STRONG_SCORE = 82

MIN_VOLUME_RATIO = 1.25
MIN_EDGE = 15

REQUEST_TIMEOUT = 20
REQUEST_DELAY = 0.05

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})

# ================================================================
# STATS
# ================================================================

STATS = {
    "pairs": 0,
    "tickers": 0,
    "candle_ok": 0,
    "candle_failed": 0,
    "candle_rows": 0,
    "analysis_passed": 0,
    "signals_found": 0,
    "signals_sent": 0,
    "long_count": 0,
    "short_count": 0,
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
        response = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            print(
                f"[HTTP ERROR] {path} -> "
                f"{response.status_code}"
            )
            print(response.text[:1000])
            return None

        try:
            return response.json()

        except Exception:
            print("[JSON ERROR]")
            print(response.text[:1000])
            return None

    except Exception as e:
        print(
            f"[REQUEST ERROR] {path}: "
            f"{repr(e)}"
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
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        response = SESSION.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:

            STATS["signals_sent"] += 1
            return True

        print(
            "[TELEGRAM ERROR]",
            response.status_code
        )

        print(response.text[:500])

        return False

    except Exception as e:

        print(
            "[TELEGRAM REQUEST ERROR]",
            repr(e)
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

        print("[PAIR ERROR] Unknown format")
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

        symbol = (
            str(symbol)
            .upper()
            .replace("/", "-")
            .replace("_", "-")
        )

        if not symbol.endswith("-USDT"):
            continue

        if symbol not in symbols:
            symbols.append(symbol)

    symbols = symbols[:MAX_MARKETS]

    STATS["pairs"] = len(symbols)

    print(
        f"[PAIR OK] {len(symbols)} USDT markets"
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
        return {}

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

        print("[TICKER ERROR] Unknown format")
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

        symbol = (
            str(symbol)
            .upper()
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
# NUMERIC HELPERS
# ================================================================

def safe_float(value, default=0.0):

    try:
        number = float(value)

        if number != number:
            return default

        return number

    except Exception:
        return default


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

        price = safe_float(value)

        if price > 0:
            return price

    return None


def get_quote_volume(ticker):

    if not isinstance(ticker, dict):
        return 0.0

    fields = [
        "quoteVolume",
        "quoteVol",
        "turnover",
        "amount"
    ]

    for field in fields:

        value = ticker.get(field)

        if value is None:
            continue

        number = safe_float(value)

        if number > 0:
            return number

    return 0.0


# ================================================================
# CANDLES
# ================================================================

def get_candles(symbol):

    end_dt = utc_now()

    start_dt = (
        end_dt
        - timedelta(hours=CANDLE_LIMIT + 5)
    )

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
        "startTime": str(start_time),
        "endTime": str(end_time)
    }

    print(
        f"[CANDLE] {symbol}"
    )

    data = get_json(
        "/api/v1/spot/public/candles",
        params=params
    )

    if not data:
        return []

    result = None

    if isinstance(data, dict):

        result = (
            data.get("res")
            or data.get("data")
            or data.get("result")
            or data.get("candles")
        )

    elif isinstance(data, list):

        result = data

    if not isinstance(result, list):

        print(
            f"[CANDLE FORMAT ERROR] "
            f"{symbol}"
        )

        return []

    candles = []

    for row in result:

        try:

            if isinstance(row, list):

                if len(row) < 5:
                    continue

                timestamp = safe_float(row[0])
                open_price = safe_float(row[1])
                high = safe_float(row[2])
                low = safe_float(row[3])
                close = safe_float(row[4])

                volume = 0.0

                if len(row) >= 6:
                    volume = safe_float(row[5])

            elif isinstance(row, dict):

                open_price = safe_float(
                    row.get("open")
                    if row.get("open") is not None
                    else row.get("o")
                )

                high = safe_float(
                    row.get("high")
                    if row.get("high") is not None
                    else row.get("h")
                )

                low = safe_float(
                    row.get("low")
                    if row.get("low") is not None
                    else row.get("l")
                )

                close = safe_float(
                    row.get("close")
                    if row.get("close") is not None
                    else row.get("c")
                )

                volume = safe_float(
                    row.get("volume")
                    if row.get("volume") is not None
                    else row.get("v")
                )

                timestamp = safe_float(
                    row.get("time")
                    if row.get("time") is not None
                    else row.get("timestamp")
                )

            else:
                continue

            if (
                open_price <= 0
                or high <= 0
                or low <= 0
                or close <= 0
            ):
                continue

            candles.append({
                "time": timestamp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume
            })

        except Exception:
            continue

    # ============================================================
    # CRITICAL:
    # OK-EX returns newest candle first.
    # We need oldest -> newest for indicators.
    # ============================================================

    if len(candles) >= 2:

        try:

            if candles[0]["time"] > candles[-1]["time"]:

                candles.reverse()

                print(
                    f"[CANDLE ORDER FIXED] "
                    f"{symbol}"
                )

        except Exception:
            pass

    return candles


# ================================================================
# EMA
# ================================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    value = sum(
        values[:period]
    ) / period

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

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
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
# WHALE PROXY
# ================================================================

def whale_proxy(
    ticker,
    volume_ratio,
    market_median_volume
):

    quote_volume = get_quote_volume(
        ticker
    )

    score = 0

    # Volume spike
    if volume_ratio >= 4:
        score += 40

    elif volume_ratio >= 3:
        score += 30

    elif volume_ratio >= 2:
        score += 20

    elif volume_ratio >= 1.5:
        score += 10

    # Market liquidity
    if market_median_volume > 0:

        relative_liquidity = (
            quote_volume
            / market_median_volume
        )

        if relative_liquidity >= 10:
            score += 40

        elif relative_liquidity >= 5:
            score += 30

        elif relative_liquidity >= 2:
            score += 20

        elif relative_liquidity >= 1:
            score += 10

    return min(score, 80)


# ================================================================
# ANALYSIS
# ================================================================

def analyze(
    symbol,
    candles,
    ticker,
    market_median_volume
):

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

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

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

    # ============================================================
    # MOMENTUM
    # ============================================================

    momentum = 0.0

    if len(closes) >= 11:

        old_price = closes[-11]

        if old_price > 0:

            momentum = (
                (price - old_price)
                / old_price
            ) * 100

    # ============================================================
    # VOLUME RATIO
    # ============================================================

    previous_volumes = volumes[-21:-1]

    if previous_volumes:

        avg_volume = (
            sum(previous_volumes)
            / len(previous_volumes)
        )

    else:

        avg_volume = 0.0

    if avg_volume > 0:

        volume_ratio = (
            volumes[-1]
            / avg_volume
        )

    else:

        volume_ratio = 0.0

    # ============================================================
    # PRICE ACTION
    # ============================================================

    previous_high = max(
        closes[-11:-1]
    )

    previous_low = min(
        closes[-11:-1]
    )

    breakout_long = (
        price > previous_high
    )

    breakout_short = (
        price < previous_low
    )

    # ============================================================
    # BASE SCORE
    # ============================================================

    long_score = 0
    short_score = 0

    # EMA trend
    if price > ema20:
        long_score += 12

    if ema20 > ema50:
        long_score += 12

    if price < ema20:
        short_score += 12

    if ema20 < ema50:
        short_score += 12

    # RSI
    if 52 <= rsi14 <= 68:
        long_score += 12

    elif 45 <= rsi14 < 52:
        short_score += 5

    if 32 <= rsi14 <= 48:
        short_score += 12

    elif 48 < rsi14 <= 55:
        short_score += 5

    # Momentum
    if momentum >= 2:
        long_score += 12

    elif momentum >= 1:
        long_score += 6

    if momentum <= -2:
        short_score += 12

    elif momentum <= -1:
        short_score += 6

    # Volume
    if volume_ratio >= 4:
        if long_score >= short_score:
            long_score += 12
        else:
            short_score += 12

    elif volume_ratio >= 2:
        if long_score >= short_score:
            long_score += 8
        else:
            short_score += 8

    elif volume_ratio >= MIN_VOLUME_RATIO:
        if long_score >= short_score:
            long_score += 5
        else:
            short_score += 5

    # Breakout
    if breakout_long:
        long_score += 12

    if breakout_short:
        short_score += 12

    # ============================================================
    # WHALE PROXY
    # ============================================================

    whale_score = whale_proxy(
        ticker,
        volume_ratio,
        market_median_volume
    )

    if long_score > short_score:
        long_score += int(
            whale_score * 0.18
        )

    elif short_score > long_score:
        short_score += int(
            whale_score * 0.18
        )

    # ============================================================
    # LIMIT
    # ============================================================

    long_score = min(
        long_score,
        100
    )

    short_score = min(
        short_score,
        100
    )

    # ============================================================
    # DIRECTION
    # ============================================================

    if long_score > short_score:

        direction = "LONG"
        score = long_score

    elif short_score > long_score:

        direction = "SHORT"
        score = short_score

    else:

        return None

    edge = abs(
        long_score
        - short_score
    )

    # ============================================================
    # QUALITY FILTER
    # ============================================================

    if score < MIN_SCORE:
        return None

    if edge < MIN_EDGE:
        return None

    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    # ============================================================
    # ATR RISK
    # ============================================================

    risk = max(
        atr14 * 1.5,
        price * 0.008
    )

    # ============================================================
    # ENTRY / SL / TP
    # ============================================================

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

    # ============================================================
    # RISK REWARD
    # ============================================================

    rr1 = 1.0
    rr2 = 2.0
    rr3 = 3.0

    STATS["analysis_passed"] += 1
    STATS["signals_found"] += 1

    if direction == "LONG":
        STATS["long_count"] += 1
    else:
        STATS["short_count"] += 1

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
        "momentum": momentum,
        "whale_score": whale_score,
        "quote_volume": get_quote_volume(ticker),
        "rr1": rr1,
        "rr2": rr2,
        "rr3": rr3
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
🐋 <b>ETH WHALE — OK-EX IRAN V15</b>

{emoji} <b>{signal["direction"]}</b>
{strength}

🪙 <b>{signal["symbol"]}</b>

━━━━━━━━━━━━━━━━━━

🎯 Score:
<b>{signal["score"]}/100</b>

📐 Edge:
<b>{signal["edge"]}</b>

🐋 Whale Proxy:
<b>{signal["whale_score"]}/80</b>

📊 RSI:
<b>{signal["rsi"]:.2f}</b>

📈 Volume:
<b>x{signal["volume_ratio"]:.2f}</b>

📈 Momentum:
<b>{signal["momentum"]:.2f}%</b>

💧 Quote Volume:
<b>{signal["quote_volume"]:.2f} USDT</b>

━━━━━━━━━━━━━━━━━━

💰 Entry:
<b>{signal["entry"]:.8g}</b>

🛑 SL:
<b>{signal["sl"]:.8g}</b>

🎯 TP1:
<b>{signal["tp1"]:.8g}</b>
R/R: <b>1:1</b>

🎯 TP2:
<b>{signal["tp2"]:.8g}</b>
R/R: <b>1:2</b>

🎯 TP3:
<b>{signal["tp3"]:.8g}</b>
R/R: <b>1:3</b>

━━━━━━━━━━━━━━━━━━

🟢 Paper Mode: ON
🔴 Real Orders: OFF

⏰ {now_text()}
"""


# ================================================================
# SCAN
# ================================================================

def scan():

    print("")
    print("=" * 65)
    print("🐋 OK-EX IRAN V15")
    print("=" * 65)

    symbols = get_pairs()

    if not symbols:

        telegram(
            "🚨 <b>OK-EX ERROR</b>\n\n"
            "No USDT markets found."
        )

        return

    tickers = get_tickers()

    # ============================================================
    # MARKET MEDIAN QUOTE VOLUME
    # ============================================================

    market_volumes = []

    for ticker in tickers.values():

        volume = get_quote_volume(
            ticker
        )

        if volume > 0:
            market_volumes.append(volume)

    if market_volumes:

        market_median_volume = (
            statistics.median(
                market_volumes
            )
        )

    else:

        market_median_volume = 0.0

    print(
        "[MARKET MEDIAN QUOTE VOLUME]",
        market_median_volume
    )

    # ============================================================
    # ANALYZE MARKETS
    # ============================================================

    signals = []

    for index, symbol in enumerate(
        symbols,
        start=1
    ):

        print(
            f"[{index}/{len(symbols)}] "
            f"{symbol}"
        )

        ticker = tickers.get(
            symbol,
            {}
        )

        candles = get_candles(
            symbol
        )

        if not candles:

            STATS["candle_failed"] += 1
            continue

        STATS["candle_ok"] += 1

        STATS["candle_rows"] += len(
            candles
        )

        signal = analyze(
            symbol,
            candles,
            ticker,
            market_median_volume
        )

        if signal:

            signals.append(
                signal
            )

        time.sleep(
            REQUEST_DELAY
        )

    # ============================================================
    # SORT
    # ============================================================

    signals.sort(
        key=lambda x: (
            x["score"],
            x["edge"],
            x["whale_score"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    selected = signals[
        :MAX_SIGNALS
    ]

    # ============================================================
    # SEND TOP SIGNALS
    # ============================================================

    for signal in selected:

        telegram(
            make_signal_message(
                signal
            )
        )

        time.sleep(1)

    # ============================================================
    # AVG CANDLES
    # ============================================================

    if STATS["candle_ok"] > 0:

        avg_candles = (
            STATS["candle_rows"]
            / STATS["candle_ok"]
        )

    else:

        avg_candles = 0

    # ============================================================
    # TOP SIGNALS SUMMARY
    # ============================================================

    top_text = ""

    for i, signal in enumerate(
        selected,
        start=1
    ):

        top_text += (
            f"\n{i}. "
            f"{signal['direction']} "
            f"<b>{signal['symbol']}</b> "
            f"— {signal['score']}/100"
        )

    if not top_text:

        top_text = "\nNo qualifying signals."

    # ============================================================
    # SUMMARY
    # ============================================================

    summary = f"""
🔎 <b>SCAN COMPLETE — V15</b>
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

🟢 LONG:
<b>{STATS["long_count"]}</b>

🔴 SHORT:
<b>{STATS["short_count"]}</b>

📨 Signals sent:
<b>{len(selected)}</b>

━━━━━━━━━━━━━━━━━━

🏆 TOP SIGNALS
{top_text}

━━━━━━━━━━━━━━━━━━

🎯 Minimum Score:
<b>{MIN_SCORE}/100</b>

🔥 Strong Score:
<b>{STRONG_SCORE}/100</b>

📊 Minimum Volume:
<b>x{MIN_VOLUME_RATIO:.2f}</b>

📐 Minimum Edge:
<b>{MIN_EDGE}</b>

🐋 Whale Proxy:
<b>ON</b>

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
        "🐋 OK-EX IRAN V15 STARTED"
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
