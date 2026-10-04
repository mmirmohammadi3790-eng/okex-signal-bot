# ================================================================
# 🐋 OK-EX IRAN — V7 DIAGNOSTIC + PAPER SIGNAL BOT
# ================================================================
# OK-EX IRAN
# BASE: https://sapi.ok-ex.io
#
# PAPER SIGNAL ONLY
# REAL ORDERS: OFF
#
# FEATURES:
# - Auto market discovery
# - Ticker fallback
# - Pairs fallback
# - Real 1H candles
# - RSI14
# - EMA20 / EMA50 / EMA200
# - Momentum
# - Volume
# - Breakout / Breakdown
# - LONG / SHORT / WATCH / WAIT
# - Entry / SL / TP1 / TP2 / TP3
# - Telegram
# - Detailed diagnostics
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

MIN_SCORE = 50
STRONG_SCORE = 70

MAX_LONG_MOMENTUM = 12.0
MAX_SHORT_MOMENTUM = 12.0

MAX_LONG_RSI = 70
MIN_SHORT_RSI = 30

MIN_VOLUME_RATIO = 0.80

CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100
CANDLE_HOURS = 120

REQUEST_TIMEOUT = 20


# ================================================================
# TELEGRAM SECRETS
# ================================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")


# ================================================================
# SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 OKEX-Iran-PaperBot",
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
        print("❌ TELEGRAM_TOKEN is missing")
        return False

    if not CHAT_ID:
        print("❌ CHAT_ID is missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

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

        if response.status_code == 200:

            return True

        print(
            "❌ TELEGRAM ERROR",
            response.status_code,
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "❌ TELEGRAM EXCEPTION",
            repr(e)
        )

        return False


# ================================================================
# API REQUEST
# ================================================================

def api_get(path, params=None):

    url = OKEX_BASE + path

    print(
        f"🌐 GET {path}"
    )

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            f"   HTTP {response.status_code}"
        )

        if response.status_code != 200:

            print(
                "   RESPONSE:",
                response.text[:500]
            )

            return None

        try:

            data = response.json()

        except Exception:

            print(
                "   ❌ JSON decode failed"
            )

            print(
                response.text[:500]
            )

            return None

        return data

    except Exception as e:

        print(
            "   ❌ REQUEST FAILED:",
            repr(e)
        )

        return None


# ================================================================
# NORMALIZE SYMBOL
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
# EXTRACT ROWS
# ================================================================

def extract_rows(data):

    if data is None:

        return []

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        for key in (
            "res",
            "data",
            "result",
            "rows",
            "list",
        ):

            value = data.get(key)

            if isinstance(value, list):

                return value

            if isinstance(value, dict):

                for subkey in (
                    "res",
                    "data",
                    "result",
                    "rows",
                    "list",
                ):

                    subvalue = value.get(
                        subkey
                    )

                    if isinstance(
                        subvalue,
                        list
                    ):

                        return subvalue

    return []


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_rows(data)

    print(
        f"📊 Raw ticker rows: {len(rows)}"
    )

    result = {}

    for item in rows:

        if isinstance(item, str):

            symbol = item

            price = 0
            quote_volume = 0
            change = 0

        elif isinstance(item, dict):

            symbol = (
                item.get("symbol")
                or item.get("instId")
                or item.get("pair")
                or item.get("market")
            )

            try:

                price = float(
                    item.get("lastPrice")
                    or item.get("last")
                    or item.get("close")
                    or item.get("price")
                    or 0
                )

            except Exception:

                price = 0

            try:

                quote_volume = float(
                    item.get("quoteVolume")
                    or item.get("quoteVol")
                    or item.get("turnover")
                    or item.get("volume")
                    or 0
                )

            except Exception:

                quote_volume = 0

            try:

                change = float(
                    item.get(
                        "priceChangePercent"
                    )
                    or item.get(
                        "changePercent"
                    )
                    or item.get(
                        "change"
                    )
                    or 0
                )

            except Exception:

                change = 0

        else:

            continue

        symbol = normalize_symbol(
            symbol
        )

        if not symbol.endswith("USDT"):

            continue

        if price <= 0:

            continue

        result[symbol] = {

            "price": price,

            "quote_volume":
                quote_volume,

            "change":
                change,
        }

    print(
        f"✅ Valid USDT tickers: {len(result)}"
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

    print(
        f"📚 Raw pair rows: {len(rows)}"
    )

    result = []

    for item in rows:

        if isinstance(item, str):

            symbol = item

        elif isinstance(item, dict):

            symbol = (
                item.get("symbol")
                or item.get("instId")
                or item.get("pair")
                or item.get("market")
            )

        else:

            continue

        symbol = normalize_symbol(
            symbol
        )

        if symbol.endswith("USDT"):

            result.append(symbol)

    result = list(
        dict.fromkeys(result)
    )

    print(
        f"✅ Valid USDT pairs: {len(result)}"
    )

    return result


# ================================================================
# MARKET DISCOVERY
# ================================================================

def discover_markets(
    tickers,
    pairs
):

    ticker_symbols = set(
        tickers.keys()
    )

    pair_symbols = set(
        pairs
    )

    print(
        "--------------------------------"
    )

    print(
        f"Ticker symbols: {len(ticker_symbols)}"
    )

    print(
        f"Pair symbols:   {len(pair_symbols)}"
    )


    # ------------------------------------------------------------
    # BEST CASE
    # ------------------------------------------------------------

    if ticker_symbols and pair_symbols:

        common = (
            ticker_symbols
            &
            pair_symbols
        )

        print(
            f"Common symbols: {len(common)}"
        )

        if common:

            markets = common

        else:

            print(
                "⚠️ No common symbols."
            )

            print(
                "➡️ Using ticker symbols."
            )

            markets = ticker_symbols


    # ------------------------------------------------------------
    # TICKER FALLBACK
    # ------------------------------------------------------------

    elif ticker_symbols:

        print(
            "⚠️ Pairs unavailable."
        )

        print(
            "➡️ Using tickers only."
        )

        markets = ticker_symbols


    # ------------------------------------------------------------
    # PAIR FALLBACK
    # ------------------------------------------------------------

    elif pair_symbols:

        print(
            "⚠️ Tickers unavailable."
        )

        print(
            "➡️ Using pairs only."
        )

        markets = pair_symbols


    # ------------------------------------------------------------
    # NOTHING
    # ------------------------------------------------------------

    else:

        print(
            "❌ NO MARKETS AVAILABLE"
        )

        return []


    markets = [
        x
        for x in markets
        if x.endswith("USDT")
    ]

    markets = sorted(
        markets
    )

    print(
        f"🎯 FINAL USDT MARKETS: {len(markets)}"
    )

    print(
        "--------------------------------"
    )

    return markets[
        :MAX_MARKETS
    ]


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
        CANDLE_HOURS
        * 60
        * 60
        * 1000
    )

    params = {

        "symbol":
            normalize_symbol(symbol),

        "interval":
            CANDLE_INTERVAL,

        "startTime":
            start_time,

        "endTime":
            end_time,

        "limit":
            CANDLE_LIMIT,
    }

    data = api_get(
        "/api/v1/spot/public/candles",
        params
    )

    rows = extract_rows(data)

    candles = []

    for row in rows:

        try:

            if isinstance(row, dict):

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

                "time":
                    float(timestamp),

                "open":
                    float(op),

                "high":
                    float(high),

                "low":
                    float(low),

                "close":
                    float(close),

                "volume":
                    float(volume),
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

    multiplier = (
        2 /
        (period + 1)
    )

    value = (
        sum(
            values[:period]
        )
        /
        period
    )

    for price in values[period:]:

        value = (
            (
                price - value
            )
            * multiplier
        ) + value

    return value


# ================================================================
# RSI
# ================================================================

def rsi(
    values,
    period=14
):

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
        sum(
            gains[:period]
        )
        /
        period
    )

    avg_loss = (
        sum(
            losses[:period]
        )
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


    rs = (
        avg_gain
        /
        avg_loss
    )

    return (
        100
        -
        (
            100 /
            (1 + rs)
        )
    )


# ================================================================
# ANALYZE
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
        or
        ema50 is None
        or
        current_rsi is None
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
            sum(
                previous_volumes
            )
            /
            len(
                previous_volumes
            )
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


    # ------------------------------------------------------------
    # BREAKOUT
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
    # SCORE
    # ------------------------------------------------------------

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []


    # PRICE / EMA20

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


    # EMA20 / EMA50

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


    # EMA200

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


    # RSI

    if (
        current_rsi >= 50
        and
        current_rsi <= 65
    ):

        long_score += 10

        long_reasons.append(
            f"RSI {current_rsi:.1f}"
        )

    elif (
        current_rsi >= 35
        and
        current_rsi < 50
    ):

        short_score += 10

        short_reasons.append(
            f"RSI {current_rsi:.1f}"
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


    # MOMENTUM

    if momentum > 0:

        if momentum <= MAX_LONG_MOMENTUM:

            long_score += 10

            long_reasons.append(
                f"Momentum +{momentum:.2f}%"
            )

    elif momentum < 0:

        if abs(momentum) <= MAX_SHORT_MOMENTUM:

            short_score += 10

            short_reasons.append(
                f"Momentum {momentum:.2f}%"
            )


    # TREND10

    if trend10 > 0.5:

        long_score += 5

        long_reasons.append(
            f"Trend +{trend10:.2f}%"
        )

    elif trend10 < -0.5:

        short_score += 5

        short_reasons.append(
            f"Trend {trend10:.2f}%"
        )


    # VOLUME

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


    # LIQUIDITY PROXY

    if ticker.get(
        "quote_volume",
        0
    ) > 0:

        if momentum >= 0:

            long_score += 5

            long_reasons.append(
                "Liquidity"
            )

        else:

            short_score += 5

            short_reasons.append(
                "Liquidity"
            )


    # ------------------------------------------------------------
    # DIRECTION
    # ------------------------------------------------------------

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


    # ------------------------------------------------------------
    # REJECTION
    # ------------------------------------------------------------

    rejection = ""


    if direction == "LONG":

        if current_rsi > MAX_LONG_RSI:

            rejection = "RSI too high"

        elif momentum > MAX_LONG_MOMENTUM:

            rejection = "Momentum overheated"

        elif volume_ratio < MIN_VOLUME_RATIO:

            rejection = "Weak volume"


    elif direction == "SHORT":

        if current_rsi < MIN_SHORT_RSI:

            rejection = "RSI too low"

        elif abs(momentum) > MAX_SHORT_MOMENTUM:

            rejection = "Momentum overheated"

        elif volume_ratio < MIN_VOLUME_RATIO:

            rejection = "Weak volume"


    # ------------------------------------------------------------
    # LEVELS
    # ------------------------------------------------------------

    entry = price


    if direction == "LONG":

        sl = entry * 0.985

        risk = entry - sl

        tp1 = entry + risk

        tp2 = entry + (
            risk * 2
        )

        tp3 = entry + (
            risk * 3
        )

    elif direction == "SHORT":

        sl = entry * 1.015

        risk = sl - entry

        tp1 = entry - risk

        tp2 = entry - (
            risk * 2
        )

        tp3 = entry - (
            risk * 3
        )

    else:

        sl = entry
        tp1 = entry
        tp2 = entry
        tp3 = entry


    # ------------------------------------------------------------
    # R/R
    # ------------------------------------------------------------

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

        if risk_value > 0:

            rr = (
                reward_value
                /
                risk_value
            )

        else:

            rr = 0

    else:

        rr = 0


    # ------------------------------------------------------------
    # VALID
    # ------------------------------------------------------------

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


    if rr < 2:

        valid_signal = False


    if rejection:

        valid_signal = False


    # ------------------------------------------------------------
    # TYPE
    # ------------------------------------------------------------

    if valid_signal:

        if score >= STRONG_SCORE:

            signal_type = "STRONG"

        else:

            signal_type = "SIGNAL"

    elif (
        score >= 55
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

        "signal_type":
            signal_type,

        "valid_signal":
            valid_signal,

        "score":
            score,

        "long_score":
            long_score,

        "short_score":
            short_score,

        "price":
            price,

        "entry":
            entry,

        "sl":
            sl,

        "tp1":
            tp1,

        "tp2":
            tp2,

        "tp3":
            tp3,

        "rr":
            rr,

        "rsi":
            current_rsi,

        "ema20":
            ema20,

        "ema50":
            ema50,

        "ema200":
            ema200,

        "momentum":
            momentum,

        "trend10":
            trend10,

        "volume_ratio":
            volume_ratio,

        "quote_volume":
            ticker.get(
                "quote_volume",
                0
            ),

        "breakout":
            breakout,

        "breakdown":
            breakdown,

        "rejection":
            rejection,

        "reasons":
            reasons,
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

    icon = (
        "🟢"
        if a["direction"] == "LONG"
        else
        "🔴"
    )

    label = (
        "🔥 STRONG"
        if a["signal_type"] == "STRONG"
        else
        "⚡ SIGNAL"
    )

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
<b>1:{a["rr"]:.2f}</b>

📈 RSI:
<b>{a["rsi"]:.2f}</b>

📉 EMA20:
<b>{a["ema20"]:.8g}</b>

📉 EMA50:
<b>{a["ema50"]:.8g}</b>

🚀 Momentum:
<b>{a["momentum"]:+.2f}%</b>

📊 Volume:
<b>x{a["volume_ratio"]:.2f}</b>

🐋 Whale Proxy:
<b>Liquidity/Volume</b>

🧠 <b>Reasons</b>
{reasons}

💵 <b>PAPER SIGNAL ONLY</b>
🔴 <b>REAL ORDERS OFF</b>

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


# ================================================================
# WATCHLIST
# ================================================================

def watchlist_message(items):

    text = """
👀 <b>OK-EX WATCHLIST</b>
━━━━━━━━━━━━━━━━━━

کاندیداهای نزدیک به سیگنال:

"""

    for i, a in enumerate(
        items,
        1
    ):

        icon = (
            "🟢"
            if a["direction"] == "LONG"
            else
            "🔴"
        )

        text += (
            f"{i}. {icon} "
            f"<b>{a['symbol']}</b> "
            f"{a['direction']} "
            f"Score {a['score']}/100\n"
        )

        text += (
            f"   Price: "
            f"{a['price']:.8g}\n"
        )

        text += (
            f"   RSI: "
            f"{a['rsi']:.1f}"
            f" | Mom: "
            f"{a['momentum']:+.2f}%"
            f" | Vol: "
            f"x{a['volume_ratio']:.2f}\n"
        )

        if a["rejection"]:

            text += (
                f"   ⚠️ "
                f"{a['rejection']}\n"
            )

        text += "\n"


    text += """
━━━━━━━━━━━━━━━━━━

🎯 Minimum Score: 50
🔥 Strong Score: 70

🐋 Whale:
Liquidity Proxy

🟢 Paper Mode: ON
🔴 Real Orders: OFF
"""

    return text


# ================================================================
# DIAGNOSTIC TELEGRAM
# ================================================================

def send_diagnostic(
    tickers,
    pairs,
    markets
):

    text = f"""
🧪 <b>OK-EX API DIAGNOSTIC</b>
━━━━━━━━━━━━━━━━━━

🌐 API:
<b>{OKEX_BASE}</b>

📊 Tickers:
<b>{len(tickers)}</b>

📚 Pairs:
<b>{len(pairs)}</b>

🪙 Final USDT Markets:
<b>{len(markets)}</b>

🟢 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    telegram_send(text)


# ================================================================
# SCAN
# ================================================================

def scan():

    print()
    print("=" * 60)
    print("🔎 OK-EX V7 SCAN")
    print(datetime.now())
    print("=" * 60)


    # ------------------------------------------------------------
    # TICKERS
    # ------------------------------------------------------------

    tickers = get_tickers()


    # ------------------------------------------------------------
    # PAIRS
    # ------------------------------------------------------------

    pairs = get_pairs()


    # ------------------------------------------------------------
    # DISCOVER
    # ------------------------------------------------------------

    markets = discover_markets(
        tickers,
        pairs
    )


    # ------------------------------------------------------------
    # DIAGNOSTIC
    # ------------------------------------------------------------

    send_diagnostic(
        tickers,
        pairs,
        markets
    )


    # ------------------------------------------------------------
    # NO MARKET
    # ------------------------------------------------------------

    if not markets:

        print(
            "❌ STOP: MARKETS = 0"
        )

        telegram_send(
            """
🔴 <b>OK-EX MARKET ERROR</b>

Markets checked: <b>0</b>

API did not return usable USDT markets.

Please check the GitHub Actions log
for Tickers / Pairs / HTTP status.
"""
        )

        return


    # ------------------------------------------------------------
    # ANALYSIS
    # ------------------------------------------------------------

    analyses = []

    candle_ok = 0
    candle_failed = 0
    total_rows = 0


    for index, symbol in enumerate(
        markets,
        1
    ):

        ticker = tickers.get(
            symbol
        )


        if not ticker:

            continue


        candles = []


        try:

            candles = get_candles(
                symbol
            )

        except Exception as e:

            print(
                "❌ Candle exception:",
                symbol,
                repr(e)
            )


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
                "❌ Analysis error:",
                symbol,
                repr(e)
            )


        time.sleep(
            0.05
        )


        if index % 25 == 0:

            print(
                f"📈 Progress "
                f"{index}/{len(markets)}"
            )


    # ------------------------------------------------------------
    # SORT
    # ------------------------------------------------------------

    analyses.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    # ------------------------------------------------------------
    # SIGNALS
    # ------------------------------------------------------------

    signals = [

        x
        for x in analyses

        if x["valid_signal"]

    ]


    signals.sort(
        key=lambda x: (
            x["score"],
            x["rr"]
        ),
        reverse=True
    )


    signals = signals[
        :MAX_SIGNALS_PER_SCAN
    ]


    # ------------------------------------------------------------
    # SEND SIGNALS
    # ------------------------------------------------------------

    sent = 0


    for signal in signals:

        symbol = signal[
            "symbol"
        ]


        if not can_send(
            symbol
        ):

            print(
                "⏳ Cooldown:",
                symbol
            )

            continue


        if telegram_send(
            signal_message(
                signal
            )
        ):

            last_sent[
                symbol
            ] = time.time()

            sent += 1


    # ------------------------------------------------------------
    # WATCHLIST
    # ------------------------------------------------------------

    watchlist = [

        x
        for x in analyses

        if (
            x["direction"]
            in (
                "LONG",
                "SHORT"
            )

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


    # ------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------

    if candle_ok:

        avg_candles = (
            total_rows
            /
            candle_ok
        )

    else:

        avg_candles = 0


    summary = f"""
🔎 <b>SCAN COMPLETE</b>
━━━━━━━━━━━━━━━━━━

🪙 Markets checked:
<b>{len(markets)}</b>

📊 Tickers:
<b>{len(tickers)}</b>

📚 Pairs:
<b>{len(pairs)}</b>

🕯 Candle OK:
<b>{candle_ok}</b>

❌ Candle failed:
<b>{candle_failed}</b>

📚 Candle rows:
<b>{total_rows}</b>

📐 Avg candles:
<b>{avg_candles:.1f}</b>

🧠 Analysis passed:
<b>{len(analyses)}</b>

🎯 Signals found:
<b>{len(signals)}</b>

📨 Signals sent:
<b>{sent}</b>

🎯 Minimum score:
<b>{MIN_SCORE}/100</b>

🔥 Strong score:
<b>{STRONG_SCORE}/100</b>

🛡 Pump Protection:
<b>ON</b>

🟢 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

🐋 Whale:
<b>Liquidity Proxy</b>

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

    print()
    print("=" * 60)
    print("🐋 OK-EX IRAN V7")
    print("PAPER SIGNAL BOT")
    print("=" * 60)

    if TELEGRAM_TOKEN:

        print(
            "✅ Telegram token detected"
        )

    else:

        print(
            "❌ Telegram token missing"
        )


    if CHAT_ID:

        print(
            "✅ Chat ID detected"
        )

    else:

        print(
            "❌ Chat ID missing"
        )


    telegram_send(
        """
🟢 <b>OK-EX IRAN V7 STARTED</b>

📡 API:
<b>sapi.ok-ex.io</b>

🪙 All USDT Markets

🕯 Real 1H Candles

🧠 RSI + EMA + Momentum
+ Volume + Breakout

🎯 LONG / SHORT

💵 PAPER SIGNAL ONLY

🔴 REAL ORDERS OFF

🧪 Diagnostic Mode:
<b>ON</b>
"""
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

            print()
            print(
                "❌ MAIN ERROR"
            )

            print(
                repr(e)
            )

            telegram_send(
                f"""
🔴 <b>BOT ERROR</b>

<code>{str(e)[:1000]}</code>
"""
            )


        print()
        print(
            f"⏳ Next scan in "
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
