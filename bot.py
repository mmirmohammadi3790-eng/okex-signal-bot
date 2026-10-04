# ================================================================
# 🐋 OK-EX IRAN — V9 PRO
# ================================================================
# PAPER SIGNAL ONLY
# REAL ORDERS: OFF
#
# ALL OK-EX USDT MARKETS
# 1H CANDLES
# EMA20 / EMA50
# RSI14
# MOMENTUM
# VOLUME
# BREAKOUT / BREAKDOWN
# ATR STOP
# STRICT ENTRY FILTER
# TELEGRAM
#
# IMPORTANT:
# Whale/Liquidity Proxy is NOT real whale/order-book detection.
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

# ------------------------------------------------
# STRICT FILTERS
# ------------------------------------------------

MIN_SCORE = 70
STRONG_SCORE = 80

MIN_VOLUME_RATIO = 1.20
STRONG_VOLUME_RATIO = 2.00

MIN_SCORE_EDGE = 15

MIN_RR = 2.0

# ------------------------------------------------
# RSI
# ------------------------------------------------

LONG_RSI_MIN = 50
LONG_RSI_MAX = 68

SHORT_RSI_MIN = 32
SHORT_RSI_MAX = 50

# ------------------------------------------------
# Momentum
# ------------------------------------------------

MAX_LONG_MOMENTUM = 12.0
MAX_SHORT_MOMENTUM = 12.0

# ------------------------------------------------
# Candles
# ------------------------------------------------

CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100
CANDLE_HOURS = 120

REQUEST_TIMEOUT = 20


# ================================================================
# TELEGRAM
# ================================================================

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN",
    ""
)

CHAT_ID = os.getenv(
    "CHAT_ID",
    ""
)


# ================================================================
# HTTP SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 OKEX-IRAN-V9",
    "Accept": "application/json",
})


# ================================================================
# COOLDOWN MEMORY
# ================================================================

last_sent = {}


# ================================================================
# TELEGRAM SEND
# ================================================================

def telegram_send(message):

    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        return False

    if not CHAT_ID:
        print("❌ CHAT_ID missing")
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
            return True

        print(
            "❌ Telegram error:",
            response.status_code,
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "❌ Telegram exception:",
            repr(e)
        )

        return False


# ================================================================
# API GET
# ================================================================

def api_get(path, params=None):

    url = OKEX_BASE + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:

            print(
                "❌ API HTTP:",
                response.status_code,
                path
            )

            return None

        try:
            return response.json()

        except Exception:

            print(
                "❌ Invalid JSON:",
                path
            )

            return None

    except Exception as e:

        print(
            "❌ API ERROR:",
            path,
            repr(e)
        )

        return None


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

                for key2 in (
                    "res",
                    "data",
                    "result",
                    "rows",
                    "list",
                ):

                    value2 = value.get(key2)

                    if isinstance(value2, list):
                        return value2

    return []


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
# TICKERS
# ================================================================

def get_tickers():

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_rows(data)

    result = {}

    for item in rows:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("instId")
            or item.get("pair")
            or item.get("market")
        )

        symbol = normalize_symbol(symbol)

        if not symbol.endswith("USDT"):
            continue

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


        if price <= 0:
            continue


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


        result[symbol] = {
            "price": price,
            "quote_volume": quote_volume,
        }

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


        symbol = normalize_symbol(symbol)

        if symbol.endswith("USDT"):
            result.append(symbol)


    return list(
        dict.fromkeys(result)
    )


# ================================================================
# DISCOVER MARKETS
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


    if pair_symbols:

        markets = pair_symbols

    elif ticker_symbols:

        markets = ticker_symbols

    else:

        markets = set()


    markets = [
        x
        for x in markets
        if x.endswith("USDT")
    ]


    markets = sorted(
        set(markets)
    )


    return markets[:MAX_MARKETS]


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

    multiplier = 2 / (period + 1)

    value = (
        sum(values[:period])
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
            losses.append(abs(change))


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
            100
            /
            (1 + rs)
        )
    )


# ================================================================
# ATR
# ================================================================

def atr(candles, period=14):

    if len(candles) <= period:
        return None


    tr_values = []


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
            )
        )


        tr_values.append(tr)


    if len(tr_values) < period:
        return None


    return (
        sum(
            tr_values[-period:]
        )
        /
        period
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

    current_rsi = rsi(
        closes,
        14
    )

    current_atr = atr(
        candles,
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
    # 10-CANDLE TREND
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


    # ------------------------------------------------------------
    # EMA20
    # ------------------------------------------------------------

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


    # ------------------------------------------------------------
    # EMA20 / EMA50
    # ------------------------------------------------------------

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


    # ------------------------------------------------------------
    # RSI
    # ------------------------------------------------------------

    if (
        current_rsi >= 50
        and
        current_rsi <= 65
    ):

        long_score += 10

        long_reasons.append(
            "Bullish RSI"
        )


    elif (
        current_rsi >= 35
        and
        current_rsi < 50
    ):

        short_score += 10

        short_reasons.append(
            "Bearish RSI"
        )


    elif (
        current_rsi > 65
        and
        current_rsi <= 68
    ):

        long_score += 5

        long_reasons.append(
            "Strong RSI"
        )


    elif (
        current_rsi >= 32
        and
        current_rsi < 35
    ):

        short_score += 5

        short_reasons.append(
            "Weak RSI"
        )


    # ------------------------------------------------------------
    # MOMENTUM
    # ------------------------------------------------------------

    if momentum > 0:

        if (
            momentum
            <=
            MAX_LONG_MOMENTUM
        ):

            long_score += 10

            long_reasons.append(
                f"Momentum +{momentum:.2f}%"
            )


    elif momentum < 0:

        if (
            abs(momentum)
            <=
            MAX_SHORT_MOMENTUM
        ):

            short_score += 10

            short_reasons.append(
                f"Momentum {momentum:.2f}%"
            )


    # ------------------------------------------------------------
    # TREND
    # ------------------------------------------------------------

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


    # ------------------------------------------------------------
    # VOLUME
    # ------------------------------------------------------------

    if (
        volume_ratio
        >=
        STRONG_VOLUME_RATIO
    ):

        if momentum > 0:

            long_score += 15

            long_reasons.append(
                f"Strong volume x{volume_ratio:.1f}"
            )

        elif momentum < 0:

            short_score += 15

            short_reasons.append(
                f"Strong volume x{volume_ratio:.1f}"
            )


    elif (
        volume_ratio
        >=
        MIN_VOLUME_RATIO
    ):

        if momentum > 0:

            long_score += 8

            long_reasons.append(
                f"Volume x{volume_ratio:.1f}"
            )

        elif momentum < 0:

            short_score += 8

            short_reasons.append(
                f"Volume x{volume_ratio:.1f}"
            )


    # ------------------------------------------------------------
    # BREAKOUT / BREAKDOWN
    # ------------------------------------------------------------

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
    # DIRECTION
    # ============================================================

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

        direction = "WAIT"

        score = 0

        edge = 0

        reasons = []


    # ============================================================
    # STRICT ENTRY FILTER
    # ============================================================

    rejection = ""


    if direction == "LONG":

        if current_rsi < LONG_RSI_MIN:

            rejection = "RSI too low"

        elif current_rsi > LONG_RSI_MAX:

            rejection = "RSI overheated"

        elif momentum <= 0:

            rejection = "Momentum invalid"

        elif momentum > MAX_LONG_MOMENTUM:

            rejection = "Momentum overheated"

        elif volume_ratio < MIN_VOLUME_RATIO:

            rejection = "Volume too weak"

        elif ema20 <= ema50:

            rejection = "EMA trend invalid"

        elif edge < MIN_SCORE_EDGE:

            rejection = "Score edge too small"


    elif direction == "SHORT":

        if current_rsi < SHORT_RSI_MIN:

            rejection = "RSI too low"

        elif current_rsi > SHORT_RSI_MAX:

            rejection = "RSI too high"

        elif momentum >= 0:

            rejection = "Momentum invalid"

        elif abs(momentum) > MAX_SHORT_MOMENTUM:

            rejection = "Momentum overheated"

        elif volume_ratio < MIN_VOLUME_RATIO:

            rejection = "Volume too weak"

        elif ema20 >= ema50:

            rejection = "EMA trend invalid"

        elif edge < MIN_SCORE_EDGE:

            rejection = "Score edge too small"


    # ============================================================
    # ATR STOP
    # ============================================================

    if current_atr is not None:

        atr_percent = (
            current_atr
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


    # ============================================================
    # LEVELS
    # ============================================================

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


    elif direction == "SHORT":

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


    else:

        sl = entry
        tp1 = entry
        tp2 = entry
        tp3 = entry


    # ============================================================
    # R/R
    # ============================================================

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


    # ============================================================
    # FINAL VALIDATION
    # ============================================================

    valid = True


    if score < MIN_SCORE:
        valid = False


    if direction not in (
        "LONG",
        "SHORT"
    ):
        valid = False


    if edge < MIN_SCORE_EDGE:
        valid = False


    if volume_ratio < MIN_VOLUME_RATIO:
        valid = False


    if rr < MIN_RR:
        valid = False


    if rejection:
        valid = False


    # ============================================================
    # SIGNAL TYPE
    # ============================================================

    if valid:

        if score >= STRONG_SCORE:

            signal_type = "STRONG"

        else:

            signal_type = "SIGNAL"

    else:

        signal_type = "WAIT"


    return {

        "symbol": symbol,

        "direction": direction,

        "signal_type": signal_type,

        "valid": valid,

        "score": score,

        "long_score": long_score,

        "short_score": short_score,

        "edge": edge,

        "entry": entry,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "rr": rr,

        "rsi": current_rsi,

        "ema20": ema20,

        "ema50": ema50,

        "momentum": momentum,

        "trend10": trend10,

        "volume_ratio": volume_ratio,

        "atr": current_atr,

        "stop_percent": stop_percent,

        "rejection": rejection,

        "reasons": reasons,
    }


# ================================================================
# PRICE FORMAT
# ================================================================

def fmt_price(value):

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
        >=
        COOLDOWN
    )


# ================================================================
# SIGNAL MESSAGE
# ================================================================

def build_signal_message(a):

    if a["direction"] == "LONG":
        icon = "🟢"
    else:
        icon = "🔴"


    if a["signal_type"] == "STRONG":
        label = "🔥 STRONG"
    else:
        label = "⚡ SIGNAL"


    reasons = "\n".join(
        "• " + x
        for x in a["reasons"]
    )


    return f"""
{icon} <b>{label} {a["direction"]}</b>
━━━━━━━━━━━━━━━━━━

🪙 <b>{a["symbol"]}</b>

📊 Score:
<b>{a["score"]}/100</b>

🟢 Long Score:
<b>{a["long_score"]}</b>

🔴 Short Score:
<b>{a["short_score"]}</b>

📐 Edge:
<b>{a["edge"]}</b>

🎯 Entry:
<b>{fmt_price(a["entry"])}</b>

🛑 SL:
<b>{fmt_price(a["sl"])}</b>

🥇 TP1:
<b>{fmt_price(a["tp1"])}</b>

🥈 TP2:
<b>{fmt_price(a["tp2"])}</b>

🥉 TP3:
<b>{fmt_price(a["tp3"])}</b>

📐 R/R:
<b>1:{a["rr"]:.2f}</b>

📈 RSI:
<b>{a["rsi"]:.2f}</b>

EMA20:
<b>{fmt_price(a["ema20"])}</b>

EMA50:
<b>{fmt_price(a["ema50"])}</b>

🚀 Momentum:
<b>{a["momentum"]:+.2f}%</b>

📊 Trend 10H:
<b>{a["trend10"]:+.2f}%</b>

📊 Volume:
<b>x{a["volume_ratio"]:.2f}</b>

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
# SUMMARY
# ================================================================

def build_summary(
    markets_count,
    candle_ok,
    candle_failed,
    candle_rows,
    analyses_count,
    signals_count,
    sent_count,
):

    if candle_ok > 0:

        average = (
            candle_rows
            /
            candle_ok
        )

    else:

        average = 0


    return f"""
🔎 <b>SCAN COMPLETE — V9 PRO</b>
━━━━━━━━━━━━━━━━━━

🪙 Markets:
<b>{markets_count}</b>

🕯 Candle OK:
<b>{candle_ok}</b>

❌ Candle failed:
<b>{candle_failed}</b>

📚 Candle rows:
<b>{candle_rows}</b>

📐 Avg candles:
<b>{average:.1f}</b>

🧠 Analysis passed:
<b>{analyses_count}</b>

🎯 Valid signals:
<b>{signals_count}</b>

📨 Signals sent:
<b>{sent_count}</b>

━━━━━━━━━━━━━━━━━━

🎯 Minimum Score:
<b>{MIN_SCORE}/100</b>

🔥 Strong Score:
<b>{STRONG_SCORE}/100</b>

📊 Minimum Volume:
<b>x{MIN_VOLUME_RATIO:.2f}</b>

📐 Minimum Edge:
<b>{MIN_SCORE_EDGE}</b>

📐 Minimum R/R:
<b>1:{MIN_RR:.1f}</b>

🟢 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


# ================================================================
# SCAN
# ================================================================

def scan():

    print()
    print("=" * 70)
    print("🐋 OK-EX IRAN V9 PRO SCAN")
    print(datetime.now())
    print("=" * 70)


    # ============================================================
    # TICKERS
    # ============================================================

    tickers = get_tickers()

    print(
        f"📡 Ticker markets: {len(tickers)}"
    )


    # ============================================================
    # PAIRS
    # ============================================================

    pairs = get_pairs()

    print(
        f"📋 Pair markets: {len(pairs)}"
    )


    # ============================================================
    # DISCOVER
    # ============================================================

    markets = discover_markets(
        tickers,
        pairs
    )


    print(
        f"🪙 Markets checked: {len(markets)}"
    )


    if not markets:

        print(
            "❌ NO MARKETS"
        )

        telegram_send(
            """
🔴 <b>OK-EX ERROR</b>

No USDT markets discovered.
"""
        )

        return


    # ============================================================
    # ANALYSIS
    # ============================================================

    analyses = []

    candle_ok = 0
    candle_failed = 0
    candle_rows = 0


    for i, symbol in enumerate(
        markets,
        1
    ):

        ticker = tickers.get(
            symbol
        )


        if not ticker:
            continue


        candles = get_candles(
            symbol
        )


        if not candles:

            candle_failed += 1

            continue


        candle_ok += 1

        candle_rows += len(
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
                "❌ Analysis error:",
                symbol,
                repr(e)
            )


        if i % 25 == 0:

            print(
                f"Progress: "
                f"{i}/{len(markets)}"
            )


        time.sleep(
            0.03
        )


    # ============================================================
    # SORT
    # ============================================================

    analyses.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"],
            x["edge"]
        ),
        reverse=True
    )


    # ============================================================
    # VALID SIGNALS
    # ============================================================

    signals = [

        x

        for x in analyses

        if x["valid"]

    ]


    signals.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"],
            x["edge"]
        ),
        reverse=True
    )


    # ============================================================
    # TOP SIGNALS
    # ============================================================

    signals = signals[
        :MAX_SIGNALS_PER_SCAN
    ]


    # ============================================================
    # SEND
    # ============================================================

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


        message = build_signal_message(
            signal
        )


        if telegram_send(
            message
        ):

            last_sent[
                symbol
            ] = time.time()

            sent += 1


    # ============================================================
    # SUMMARY
    # ============================================================

    summary = build_summary(

        len(markets),

        candle_ok,

        candle_failed,

        candle_rows,

        len(analyses),

        len(signals),

        sent
    )


    print(summary)

    telegram_send(summary)


# ================================================================
# STARTUP
# ================================================================

def startup():

    print()
    print("=" * 70)
    print("🐋 OK-EX IRAN V9 PRO STARTED")
    print("=" * 70)

    print(
        "PAPER_MODE =",
        PAPER_MODE
    )

    print(
        "REAL_ORDERS =",
        REAL_ORDERS
    )

    print(
        "MIN_SCORE =",
        MIN_SCORE
    )

    print(
        "MIN_VOLUME_RATIO =",
        MIN_VOLUME_RATIO
    )

    print(
        "MIN_SCORE_EDGE =",
        MIN_SCORE_EDGE
    )


    telegram_send(
        f"""
🟢 <b>OK-EX IRAN V9 PRO STARTED</b>
━━━━━━━━━━━━━━━━━━

🪙 ALL USDT MARKETS

🕯 1H REAL CANDLES

🧠 EMA20 / EMA50
RSI14
MOMENTUM
VOLUME
BREAKOUT

🛡 <b>STRICT FILTER ON</b>

🎯 Minimum Score:
<b>{MIN_SCORE}</b>

📊 Minimum Volume:
<b>x{MIN_VOLUME_RATIO:.2f}</b>

📐 Minimum Edge:
<b>{MIN_SCORE_EDGE}</b>

📐 Minimum R/R:
<b>1:{MIN_RR:.1f}</b>

🔥 Strong:
<b>{STRONG_SCORE}</b>

🎯 Max Signals:
<b>{MAX_SIGNALS_PER_SCAN}</b>

🐋 Liquidity Proxy:
<b>ACTIVE</b>

💵 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

⚠️ هیچ معامله واقعی انجام نمی‌شود.
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

            print(
                "❌ MAIN ERROR:",
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
