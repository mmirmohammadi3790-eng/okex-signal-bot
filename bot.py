# ================================================================
# 🐋 OK-EX IRAN — V6 PRO PAPER SIGNAL BOT
# ================================================================
# ALL USDT MARKETS
# REAL 1H CANDLES
# LONG / SHORT / WATCH / WAIT
# EMA20 / EMA50 / EMA200
# RSI14
# MOMENTUM
# VOLUME
# BREAKOUT / BREAKDOWN
# PUMP PROTECTION
# R/R FILTER
# LIQUIDITY PROXY
# TELEGRAM
# PAPER ONLY
# NO REAL ORDERS
# ================================================================

import os
import time
import requests
from datetime import datetime


# ================================================================
# CONFIG
# ================================================================

OKEX_BASE = "https://sapi.ok-ex.io"

PAPER_MODE = True
REAL_ORDERS = False

SCAN_INTERVAL = 300
COOLDOWN = 1800

MAX_MARKETS = 9999
MAX_SIGNALS_PER_SCAN = 3
WATCHLIST_SIZE = 5

# Minimum raw score
MIN_SCORE = 50

# Strong signal
STRONG_SCORE = 70

# Professional filters
MIN_RR = 2.0

# Avoid chasing extreme momentum
MAX_LONG_MOMENTUM = 12.0
MAX_SHORT_MOMENTUM = 12.0

# RSI protection
MAX_LONG_RSI = 70
MIN_SHORT_RSI = 30

# Minimum volume confirmation
MIN_VOLUME_RATIO = 0.80

# Candle
CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100
CANDLE_HOURS = 120

REQUEST_TIMEOUT = 20


# ================================================================
# TELEGRAM
# ================================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")


# ================================================================
# SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "OKEX-Iran-PaperBot-V6",
    "Accept": "application/json",
})


# ================================================================
# MEMORY
# ================================================================

last_sent = {}


# ================================================================
# TELEGRAM
# ================================================================

def telegram_send(text):

    if not TELEGRAM_TOKEN:
        print("Telegram token missing")
        return False

    if not CHAT_ID:
        print("Chat ID missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:

        r = session.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if r.status_code == 200:
            return True

        print(
            "Telegram error:",
            r.status_code,
            r.text[:500]
        )

        return False

    except Exception as e:

        print(
            "Telegram exception:",
            repr(e)
        )

        return False


# ================================================================
# HTTP
# ================================================================

def get_json(path, params=None):

    url = OKEX_BASE + path

    try:

        r = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if r.status_code != 200:

            print(
                "HTTP ERROR:",
                r.status_code,
                r.text[:500]
            )

            return None

        return r.json()

    except Exception as e:

        print(
            "REQUEST ERROR:",
            repr(e)
        )

        return None


# ================================================================
# SYMBOL NORMALIZER
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
        .strip()
    )


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    data = get_json(
        "/api/v1/spot/public/tickers"
    )

    if not data:
        return {}

    rows = None

    if isinstance(data, dict):

        rows = data.get("res")

        if rows is None:
            rows = data.get("data")

        if rows is None:
            rows = data.get("result")

    if not isinstance(rows, list):
        return {}

    result = {}

    for item in rows:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("instId")
            or item.get("pair")
        )

        if not symbol:
            continue

        symbol = normalize_symbol(symbol)

        if not symbol.endswith("USDT"):
            continue

        try:

            price = float(
                item.get("lastPrice")
                or item.get("last")
                or item.get("close")
                or 0
            )

        except Exception:

            price = 0

        if price <= 0:
            continue

        try:

            quote_volume = float(
                item.get("quoteVolume")
                or item.get("quoteVol")
                or item.get("volume")
                or 0
            )

        except Exception:

            quote_volume = 0

        try:

            change = float(
                item.get("priceChangePercent")
                or item.get("changePercent")
                or item.get("change")
                or 0
            )

        except Exception:

            change = 0

        result[symbol] = {
            "price": price,
            "quote_volume": quote_volume,
            "change": change,
        }

    return result


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    data = get_json(
        "/api/v1/spot/public/pairs"
    )

    if not data:
        return []

    rows = None

    if isinstance(data, dict):

        rows = data.get("res")

        if rows is None:
            rows = data.get("data")

        if rows is None:
            rows = data.get("result")

    if not isinstance(rows, list):
        return []

    symbols = []

    for item in rows:

        if isinstance(item, str):

            symbol = item

        elif isinstance(item, dict):

            symbol = (
                item.get("symbol")
                or item.get("pair")
                or item.get("instId")
            )

        else:

            continue

        if not symbol:
            continue

        symbol = normalize_symbol(symbol)

        if symbol.endswith("USDT"):
            symbols.append(symbol)

    return list(
        dict.fromkeys(symbols)
    )


# ================================================================
# MARKET DISCOVERY
# ================================================================

def discover_markets(tickers, pairs):

    ticker_symbols = set(
        tickers.keys()
    )

    pair_symbols = set(
        pairs
    )

    if ticker_symbols and pair_symbols:

        common = (
            ticker_symbols &
            pair_symbols
        )

        if common:
            markets = common
        else:
            markets = ticker_symbols

    elif ticker_symbols:

        markets = ticker_symbols

    else:

        markets = pair_symbols

    markets = [
        x for x in markets
        if x.endswith("USDT")
    ]

    return sorted(markets)[:MAX_MARKETS]


# ================================================================
# CANDLES
# ================================================================

def get_candles(symbol):

    end_time = int(
        time.time() * 1000
    )

    start_time = (
        end_time
        -
        (
            CANDLE_HOURS
            * 60
            * 60
            * 1000
        )
    )

    params = {

        "symbol": normalize_symbol(symbol),

        "interval": CANDLE_INTERVAL,

        "startTime": start_time,

        "endTime": end_time,

        "limit": CANDLE_LIMIT,

    }

    data = get_json(
        "/api/v1/spot/public/candles",
        params=params,
    )

    if not data:
        return []

    if isinstance(data, dict):

        rows = data.get("res")

        if rows is None:
            rows = data.get("data")

        if rows is None:
            rows = data.get("result")

    elif isinstance(data, list):

        rows = data

    else:

        rows = []

    if not isinstance(rows, list):
        return []

    candles = []

    for row in rows:

        try:

            if isinstance(row, dict):

                timestamp = (
                    row.get("timestamp")
                    or row.get("time")
                    or row.get("ts")
                )

                op = row.get("open")
                high = row.get("high")
                low = row.get("low")
                close = row.get("close")

                volume = (
                    row.get("volume")
                    or row.get("vol")
                    or 0
                )

            elif isinstance(row, list):

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
# EMA
# ================================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (
        period + 1
    )

    value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        value = (
            (price - value)
            * multiplier
        ) + value

    return value


# ================================================================
# RSI
# ================================================================

def rsi(values, period=14):

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

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
            +
            gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = (
        avg_gain /
        avg_loss
    )

    return 100 - (
        100 /
        (1 + rs)
    )


# ================================================================
# ANALYSIS
# ================================================================

def analyze(symbol, candles, ticker):

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

    ema200 = ema(
        closes,
        200
    )

    current_rsi = rsi(
        closes,
        14
    )

    if (
        ema20 is None
        or ema50 is None
        or current_rsi is None
    ):
        return None

    # ============================================================
    # MOMENTUM
    # ============================================================

    momentum = (
        (
            closes[-1]
            -
            closes[-7]
        )
        /
        closes[-7]
    ) * 100


    # ============================================================
    # 10 CANDLE TREND
    # ============================================================

    trend10 = (
        (
            closes[-1]
            -
            closes[-11]
        )
        /
        closes[-11]
    ) * 100


    # ============================================================
    # VOLUME
    # ============================================================

    previous_volumes = volumes[-21:-1]

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

        volume_ratio = 1


    # ============================================================
    # BREAKOUT
    # ============================================================

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


    # ============================================================
    # SCORE
    # ============================================================

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []


    # ============================================================
    # EMA20
    # ============================================================

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


    # ============================================================
    # EMA50
    # ============================================================

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


    # ============================================================
    # EMA200
    # ============================================================

    if ema200 is not None:

        if price > ema200:

            long_score += 5

            long_reasons.append(
                "Price > EMA200"
            )

        else:

            short_score += 5

            short_reasons.append(
                "Price < EMA200"
            )


    # ============================================================
    # RSI
    # ============================================================

    if (
        current_rsi >= 50
        and
        current_rsi <= 65
    ):

        long_score += 10

        long_reasons.append(
            f"RSI bullish {current_rsi:.1f}"
        )

    elif (
        current_rsi >= 35
        and
        current_rsi < 50
    ):

        short_score += 10

        short_reasons.append(
            f"RSI bearish {current_rsi:.1f}"
        )

    elif (
        current_rsi > 65
        and
        current_rsi <= 70
    ):

        long_score += 5

        long_reasons.append(
            f"RSI strong {current_rsi:.1f}"
        )

    elif (
        current_rsi >= 30
        and
        current_rsi < 35
    ):

        short_score += 5

        short_reasons.append(
            f"RSI weak {current_rsi:.1f}"
        )


    # ============================================================
    # MOMENTUM
    # ============================================================

    if momentum > 0:

        if momentum <= MAX_LONG_MOMENTUM:

            long_score += 10

            long_reasons.append(
                f"Momentum +{momentum:.2f}%"
            )

        else:

            # Too hot: don't reward it
            long_reasons.append(
                f"Momentum overheated +{momentum:.2f}%"
            )

    elif momentum < 0:

        if abs(momentum) <= MAX_SHORT_MOMENTUM:

            short_score += 10

            short_reasons.append(
                f"Momentum {momentum:.2f}%"
            )

        else:

            short_reasons.append(
                f"Momentum oversold {momentum:.2f}%"
            )


    # ============================================================
    # TREND
    # ============================================================

    if trend10 > 0.5:

        long_score += 5

        long_reasons.append(
            f"10-candle strength +{trend10:.2f}%"
        )

    elif trend10 < -0.5:

        short_score += 5

        short_reasons.append(
            f"10-candle weakness {trend10:.2f}%"
        )


    # ============================================================
    # VOLUME
    # ============================================================

    if volume_ratio >= 2:

        if momentum > 0:

            long_score += 10

            long_reasons.append(
                f"Volume x{volume_ratio:.2f}"
            )

        elif momentum < 0:

            short_score += 10

            short_reasons.append(
                f"Volume x{volume_ratio:.2f}"
            )

    elif volume_ratio >= 1.2:

        if momentum > 0:

            long_score += 5

            long_reasons.append(
                f"Volume x{volume_ratio:.2f}"
            )

        elif momentum < 0:

            short_score += 5

            short_reasons.append(
                f"Volume x{volume_ratio:.2f}"
            )


    # ============================================================
    # BREAKOUT
    # ============================================================

    if breakout:

        long_score += 10

        long_reasons.append(
            "Breakout"
        )

    if breakdown:

        short_score += 10

        short_reasons.append(
            "Breakdown"
        )


    # ============================================================
    # LIQUIDITY PROXY
    # ============================================================

    quote_volume = ticker.get(
        "quote_volume",
        0
    )

    if quote_volume > 0:

        if momentum >= 0:

            long_score += 5

            long_reasons.append(
                "Liquidity proxy"
            )

        else:

            short_score += 5

            short_reasons.append(
                "Liquidity proxy"
            )


    # ============================================================
    # DIRECTION
    # ============================================================

    if long_score > short_score:

        direction = "LONG"
        score = long_score
        reasons = long_reasons

    elif short_score > long_score:

        direction = "SHORT"
        score = short_score
        reasons = short_reasons

    else:

        direction = "WAIT"
        score = max(
            long_score,
            short_score
        )

        reasons = []


    # ============================================================
    # PROFESSIONAL FILTERS
    # ============================================================

    rejection = ""

    # LONG protection
    if direction == "LONG":

        if current_rsi > MAX_LONG_RSI:

            rejection = (
                "RSI too high"
            )

        elif momentum > MAX_LONG_MOMENTUM:

            rejection = (
                "Momentum overheated"
            )

        elif volume_ratio < MIN_VOLUME_RATIO:

            rejection = (
                "Weak volume"
            )

    # SHORT protection
    elif direction == "SHORT":

        if current_rsi < MIN_SHORT_RSI:

            rejection = (
                "RSI too low"
            )

        elif abs(momentum) > MAX_SHORT_MOMENTUM:

            rejection = (
                "Momentum overheated"
            )

        elif volume_ratio < MIN_VOLUME_RATIO:

            rejection = (
                "Weak volume"
            )


    # ============================================================
    # PAPER LEVELS
    # ============================================================

    entry = price

    if direction == "LONG":

        # Dynamic-ish 1.5% base stop
        sl = entry * 0.985

        risk = entry - sl

        tp1 = entry + risk
        tp2 = entry + (risk * 2)
        tp3 = entry + (risk * 3)

    elif direction == "SHORT":

        sl = entry * 1.015

        risk = sl - entry

        tp1 = entry - risk
        tp2 = entry - (risk * 2)
        tp3 = entry - (risk * 3)

    else:

        sl = entry
        tp1 = entry
        tp2 = entry
        tp3 = entry


    # ============================================================
    # R/R
    # ============================================================

    if direction in (
        "LONG",
        "SHORT"
    ):

        risk_value = abs(
            entry - sl
        )

        reward_value = abs(
            tp2 - entry
        )

        rr = (
            reward_value /
            risk_value
            if risk_value > 0
            else 0
        )

    else:

        rr = 0


    # ============================================================
    # FINAL QUALITY
    # ============================================================

    valid_signal = True

    if score < MIN_SCORE:

        valid_signal = False

    if direction not in (
        "LONG",
        "SHORT"
    ):

        valid_signal = False

    if abs(
        long_score -
        short_score
    ) < 10:

        valid_signal = False

    if rr < MIN_RR:

        valid_signal = False

    if rejection:

        valid_signal = False


    # ============================================================
    # WATCH STATUS
    # ============================================================

    if valid_signal:

        if score >= STRONG_SCORE:

            signal_type = "STRONG"

        else:

            signal_type = "SIGNAL"

    else:

        if (
            score >= 60
            and
            direction in (
                "LONG",
                "SHORT"
            )
        ):

            signal_type = "WATCH"

        else:

            signal_type = "WAIT"


    return {

        "symbol": symbol,

        "direction": direction,

        "signal_type": signal_type,

        "valid_signal": valid_signal,

        "score": score,

        "long_score": long_score,

        "short_score": short_score,

        "price": price,

        "entry": entry,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "rr": rr,

        "rsi": current_rsi,

        "ema20": ema20,

        "ema50": ema50,

        "ema200": ema200,

        "momentum": momentum,

        "trend10": trend10,

        "volume_ratio": volume_ratio,

        "quote_volume": quote_volume,

        "breakout": breakout,

        "breakdown": breakdown,

        "rejection": rejection,

        "reasons": reasons,

    }


# ================================================================
# COOLDOWN
# ================================================================

def can_send(symbol):

    now = time.time()

    previous = last_sent.get(
        symbol,
        0
    )

    return (
        now - previous
        >= COOLDOWN
    )


# ================================================================
# SIGNAL MESSAGE
# ================================================================

def signal_message(a):

    if a["direction"] == "LONG":

        icon = "🟢"

    else:

        icon = "🔴"


    if a["signal_type"] == "STRONG":

        label = "🔥 STRONG"

    else:

        label = "⚡ SIGNAL"


    reasons = "\n".join(
        f"• {x}"
        for x in a["reasons"][:7]
    )


    return f"""
{icon} <b>{label} {a["direction"]}</b>
━━━━━━━━━━━━━━━━━━

🪙 <b>{a["symbol"]}</b>

📊 Score:
<b>{a["score"]}/100</b>

🎯 Entry:
<b>{a["entry"]:.8g}</b>

🛑 SL:
<b>{a["sl"]:.8g}</b>

🥇 TP1:
<b>{a["tp1"]:.8g}</b>

🥈 TP2:
<b>{a["tp2"]:.8g}</b>

🥉 TP3:
<b>{a["tp3"]:.8g}</b>

📐 R/R:
<b>1 : {a["rr"]:.2f}</b>

📈 RSI:
<b>{a["rsi"]:.2f}</b>

EMA20:
<b>{a["ema20"]:.8g}</b>

EMA50:
<b>{a["ema50"]:.8g}</b>

🚀 Momentum:
<b>{a["momentum"]:+.2f}%</b>

📊 Volume:
<b>x{a["volume_ratio"]:.2f}</b>

🐋 Liquidity Proxy:
<b>ACTIVE</b>

🧠 <b>Reasons:</b>
{reasons}

💵 <b>PAPER SIGNAL ONLY</b>
🔴 <b>REAL ORDERS: OFF</b>

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


# ================================================================
# WATCHLIST
# ================================================================

def watchlist_message(items):

    text = """
👀 <b>OK-EX PRO WATCHLIST</b>
━━━━━━━━━━━━━━━━━━

سیگنال قطعی نیست؛
این‌ها نزدیک‌ترین کاندیداها هستند:

"""

    for i, a in enumerate(
        items,
        1
    ):

        if a["direction"] == "LONG":

            icon = "🟢"

        elif a["direction"] == "SHORT":

            icon = "🔴"

        else:

            icon = "⚪"


        text += (
            f"{i}. {icon} "
            f"<b>{a['symbol']}</b> "
            f"{a['direction']} "
            f"Score {a['score']}/100\n"
        )

        text += (
            f"   💰 {a['price']:.8g}"
            f" | RSI {a['rsi']:.1f}"
            f" | Mom {a['momentum']:+.2f}%"
            f" | Vol x{a['volume_ratio']:.2f}\n"
        )

        if a["rejection"]:

            text += (
                f"   ⚠️ {a['rejection']}\n"
            )

        text += "\n"


    text += """
🎯 Min Score: 50
🔥 Strong: 70

🐋 Whale detection:
Liquidity Proxy

🟢 Paper Mode: ON
🔴 Real Orders: OFF
"""

    return text


# ================================================================
# SCAN
# ================================================================

def scan():

    print(
        "\n======================================"
    )

    print(
        "🔎 START SCAN"
    )

    print(
        datetime.now()
    )

    print(
        "======================================"
    )


    tickers = get_tickers()

    pairs = get_pairs()

    markets = discover_markets(
        tickers,
        pairs
    )


    if not markets:

        telegram_send(
            """
🔴 <b>SCAN ERROR</b>

No USDT markets found.
"""
        )

        return


    print(
        "Markets:",
        len(markets)
    )


    analyses = []

    candle_ok = 0
    candle_failed = 0
    total_rows = 0


    # ============================================================
    # SCAN MARKETS
    # ============================================================

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
                "Candle error:",
                symbol,
                repr(e)
            )

            candles = []


        if candles:

            candle_ok += 1

            total_rows += len(
                candles
            )

        else:

            candle_failed += 1

            continue


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
                "Analysis error:",
                symbol,
                repr(e)
            )


        # Small delay for API stability
        time.sleep(0.05)


    # ============================================================
    # SORT
    # ============================================================

    analyses.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    # ============================================================
    # VALID SIGNALS
    # ============================================================

    signals = [
        x for x in analyses
        if x["valid_signal"]
    ]


    signals.sort(
        key=lambda x: (
            x["score"],
            x["rr"]
        ),
        reverse=True
    )


    # Top 3 only
    signals = signals[
        :MAX_SIGNALS_PER_SCAN
    ]


    # ============================================================
    # SEND SIGNALS
    # ============================================================

    sent = 0

    for a in signals:

        symbol = a["symbol"]

        if not can_send(symbol):

            print(
                "Cooldown:",
                symbol
            )

            continue


        if telegram_send(
            signal_message(a)
        ):

            last_sent[
                symbol
            ] = time.time()

            sent += 1


    # ============================================================
    # WATCHLIST
    # ============================================================

    watchlist = [
        x for x in analyses
        if (
            x["direction"]
            in ("LONG", "SHORT")
            and
            x["score"] >= 55
        )
    ]


    watchlist.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    watchlist = watchlist[
        :WATCHLIST_SIZE
    ]


    if watchlist:

        telegram_send(
            watchlist_message(
                watchlist
            )
        )


    # ============================================================
    # SUMMARY
    # ============================================================

    summary = f"""
🔎 <b>SCAN COMPLETE</b>

🪙 Markets checked:
<b>{len(markets)}</b>

🕯 Candle OK:
<b>{candle_ok}</b>

❌ Candle failed:
<b>{candle_failed}</b>

📚 Candle rows:
<b>{total_rows}</b>

📐 Avg candles:
<b>{
    (total_rows / candle_ok)
    if candle_ok
    else 0
:.1f}</b>

🧠 Analysis passed:
<b>{len(analyses)}</b>

🎯 Valid signals:
<b>{len(signals)}</b>

📨 Signals sent:
<b>{sent}</b>

🎯 Minimum score:
<b>{MIN_SCORE}/100</b>

🔥 Strong score:
<b>{STRONG_SCORE}/100</b>

📐 Minimum R/R:
<b>1:{MIN_RR}</b>

🛡 Pump protection:
<b>ON</b>

🟢 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


    print(summary)

    telegram_send(
        summary
    )


# ================================================================
# STARTUP
# ================================================================

def startup():

    message = """
🟢 <b>OK-EX IRAN — V6 PRO</b>
━━━━━━━━━━━━━━━━━━

📡 API:
<b>ONLINE</b>

🕯 Real 1H Candle:
<b>ON</b>

📊 Markets:
<b>ALL USDT</b>

🧠 Strategy:
<b>EMA + RSI + Momentum + Volume</b>

🛡 Pump Protection:
<b>ON</b>

📐 R/R Filter:
<b>1:2 MINIMUM</b>

🔥 Strong Score:
<b>70/100</b>

📨 Max Signals:
<b>3</b>

🐋 Whale:
<b>Liquidity Proxy</b>

🟢 PAPER MODE:
<b>ON</b>

🔴 REAL ORDERS:
<b>OFF</b>

⚠️ هیچ معامله واقعی انجام نمی‌شود.
"""


    print(message)

    telegram_send(
        message
    )


# ================================================================
# MAIN
# ================================================================

def main():

    startup()

    while True:

        try:

            scan()

        except Exception as e:

            print(
                "\nMAIN ERROR:",
                repr(e)
            )

            telegram_send(
                f"""
🔴 <b>BOT ERROR</b>

<code>{str(e)[:1000]}</code>
"""
            )


        print(
            f"\n⏳ Next scan in "
            f"{SCAN_INTERVAL} seconds..."
        )

        time.sleep(
            SCAN_INTERVAL
        )


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":

    main()
