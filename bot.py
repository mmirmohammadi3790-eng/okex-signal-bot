# ================================================================
# 🐋 OK-EX IRAN — V8 PRO FILTERED FUTURES PAPER SIGNAL BOT
# ================================================================
# PAPER SIGNAL ONLY
# REAL ORDERS: OFF
#
# FEATURES:
# - ALL OK-EX USDT MARKETS
# - REAL 1H CANDLES
# - EMA20 / EMA50 / EMA200 when available
# - RSI14
# - Momentum
# - Volume confirmation
# - Breakout / Breakdown
# - Trend confirmation
# - Strict signal filter
# - LONG / SHORT
# - Entry / SL / TP1 / TP2 / TP3
# - R/R
# - Telegram
# - Cooldown
# - Maximum 3 signals per scan
#
# IMPORTANT:
# "WHALE PROXY" IS NOT REAL ORDER-BOOK WHALE DETECTION.
# It is only a liquidity/volume proxy.
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

# Maximum number of final signals per scan
MAX_SIGNALS_PER_SCAN = 3

# Minimum final score
MIN_SCORE = 70

# Strong signal score
STRONG_SCORE = 80

# Minimum volume confirmation
MIN_VOLUME_RATIO = 1.20

# Strong volume
STRONG_VOLUME_RATIO = 2.00

# Maximum acceptable LONG momentum
MAX_LONG_MOMENTUM = 12.0

# Maximum acceptable SHORT momentum
MAX_SHORT_MOMENTUM = 12.0

# RSI filters
LONG_RSI_MIN = 50
LONG_RSI_MAX = 68

SHORT_RSI_MIN = 32
SHORT_RSI_MAX = 50

# Minimum difference between LONG and SHORT score
MIN_SCORE_EDGE = 15

# Minimum R/R
MIN_RR = 2.0

# Candle settings
CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100
CANDLE_HOURS = 120

REQUEST_TIMEOUT = 20


# ================================================================
# TELEGRAM SECRETS
# ================================================================

# Put these in GitHub:
#
# Settings
# -> Secrets and variables
# -> Actions
#
# TELEGRAM_TOKEN
# CHAT_ID

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
    "User-Agent":
        "Mozilla/5.0 OKEX-Iran-V8",
    "Accept":
        "application/json",
})


# ================================================================
# MEMORY
# ================================================================

last_sent = {}


# ================================================================
# TELEGRAM SEND
# ================================================================

def telegram_send(text):

    if not TELEGRAM_TOKEN:

        print(
            "❌ TELEGRAM_TOKEN missing"
        )

        return False

    if not CHAT_ID:

        print(
            "❌ CHAT_ID missing"
        )

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:

        response = session.post(

            url,

            data={

                "chat_id":
                    CHAT_ID,

                "text":
                    text,

                "parse_mode":
                    "HTML",

                "disable_web_page_preview":
                    True,
            },

            timeout=
                REQUEST_TIMEOUT,
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

def api_get(
    path,
    params=None
):

    url = OKEX_BASE + path

    try:

        response = session.get(

            url,

            params=params,

            timeout=
                REQUEST_TIMEOUT,
        )

        if response.status_code != 200:

            print(
                "❌ API HTTP:",
                response.status_code,
                path
            )

            print(
                response.text[:500]
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
            "❌ API request error:",
            path,
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

            value = data.get(
                key
            )

            if isinstance(
                value,
                list
            ):

                return value

            if isinstance(
                value,
                dict
            ):

                for key2 in (
                    "res",
                    "data",
                    "result",
                    "rows",
                    "list",
                ):

                    value2 = value.get(
                        key2
                    )

                    if isinstance(
                        value2,
                        list
                    ):

                        return value2

    return []


# ================================================================
# GET TICKERS
# ================================================================

def get_tickers():

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_rows(
        data
    )

    result = {}

    for item in rows:

        if not isinstance(
            item,
            dict
        ):

            continue

        symbol = (

            item.get("symbol")

            or

            item.get("instId")

            or

            item.get("pair")

            or

            item.get("market")
        )

        symbol = normalize_symbol(
            symbol
        )

        if not symbol.endswith(
            "USDT"
        ):

            continue

        try:

            price = float(

                item.get(
                    "lastPrice"
                )

                or

                item.get(
                    "last"
                )

                or

                item.get(
                    "close"
                )

                or

                item.get(
                    "price"
                )

                or 0
            )

        except Exception:

            price = 0


        if price <= 0:

            continue


        try:

            quote_volume = float(

                item.get(
                    "quoteVolume"
                )

                or

                item.get(
                    "quoteVol"
                )

                or

                item.get(
                    "turnover"
                )

                or

                item.get(
                    "volume"
                )

                or 0
            )

        except Exception:

            quote_volume = 0


        try:

            change = float(

                item.get(
                    "priceChangePercent"
                )

                or

                item.get(
                    "changePercent"
                )

                or

                item.get(
                    "change"
                )

                or 0
            )

        except Exception:

            change = 0


        result[symbol] = {

            "price":
                price,

            "quote_volume":
                quote_volume,

            "change":
                change,
        }


    return result


# ================================================================
# GET PAIRS
# ================================================================

def get_pairs():

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    rows = extract_rows(
        data
    )

    result = []

    for item in rows:

        if isinstance(
            item,
            str
        ):

            symbol = item

        elif isinstance(
            item,
            dict
        ):

            symbol = (

                item.get("symbol")

                or

                item.get("instId")

                or

                item.get("pair")

                or

                item.get("market")
            )

        else:

            continue


        symbol = normalize_symbol(
            symbol
        )


        if symbol.endswith(
            "USDT"
        ):

            result.append(
                symbol
            )


    return list(
        dict.fromkeys(
            result
        )
    )


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


    if (
        ticker_symbols
        and
        pair_symbols
    ):

        common = (
            ticker_symbols
            &
            pair_symbols
        )

        if common:

            markets = common

        else:

            markets = ticker_symbols


    elif ticker_symbols:

        markets = ticker_symbols


    elif pair_symbols:

        markets = pair_symbols


    else:

        markets = []


    markets = [

        symbol

        for symbol in markets

        if symbol.endswith(
            "USDT"
        )

    ]


    markets = sorted(
        set(markets)
    )


    return markets[
        :MAX_MARKETS
    ]


# ================================================================
# GET CANDLES
# ================================================================

def get_candles(symbol):

    end_time = int(
        time.time()
        * 1000
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

        "symbol":
            normalize_symbol(
                symbol
            ),

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


    rows = extract_rows(
        data
    )


    candles = []


    for row in rows:

        try:

            if isinstance(
                row,
                dict
            ):

                timestamp = (

                    row.get(
                        "timestamp"
                    )

                    or

                    row.get(
                        "time"
                    )

                    or

                    row.get(
                        "ts"
                    )
                )

                op = (

                    row.get(
                        "open"
                    )

                    or

                    row.get(
                        "o"
                    )
                )

                high = (

                    row.get(
                        "high"
                    )

                    or

                    row.get(
                        "h"
                    )
                )

                low = (

                    row.get(
                        "low"
                    )

                    or

                    row.get(
                        "l"
                    )
                )

                close = (

                    row.get(
                        "close"
                    )

                    or

                    row.get(
                        "c"
                    )
                )

                volume = (

                    row.get(
                        "volume"
                    )

                    or

                    row.get(
                        "vol"
                    )

                    or

                    row.get(
                        "v"
                    )

                    or 0
                )


            elif isinstance(
                row,
                list
            ):

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
        key=lambda x:
            x["time"]
    )


    return candles


# ================================================================
# EMA
# ================================================================

def ema(
    values,
    period
):

    if len(values) < period:

        return None


    multiplier = (
        2
        /
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
                price
                -
                value
            )

            *
            multiplier

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

            gains.append(
                change
            )

            losses.append(
                0
            )

        else:

            gains.append(
                0
            )

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
            100
            /
            (1 + rs)
        )
    )


# ================================================================
# ATR
# ================================================================

def atr(
    candles,
    period=14
):

    if len(candles) <= period:

        return None


    true_ranges = []


    for i in range(
        1,
        len(candles)
    ):

        high = candles[i][
            "high"
        ]

        low = candles[i][
            "low"
        ]

        previous_close = (
            candles[i - 1][
                "close"
            ]
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


        true_ranges.append(
            tr
        )


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


    price = ticker[
        "price"
    ]


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


    # ============================================================
    # PRICE / EMA20
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
    # EMA20 / EMA50
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


    # ============================================================
    # MOMENTUM
    # ============================================================

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


    # ============================================================
    # TREND
    # ============================================================

    if trend10 > 0.5:

        long_score += 5

        long_reasons.append(
            f"10-candle strength"
        )


    elif trend10 < -0.5:

        short_score += 5

        short_reasons.append(
            f"10-candle weakness"
        )


    # ============================================================
    # VOLUME
    # ============================================================

    if (
        volume_ratio
        >=
        STRONG_VOLUME_RATIO
    ):

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


    elif (
        volume_ratio
        >=
        MIN_VOLUME_RATIO
    ):

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


    # ============================================================
    # BREAKOUT / BREAKDOWN
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
    # LIQUIDITY
    # ============================================================

    quote_volume = ticker.get(
        "quote_volume",
        0
    )


    if quote_volume > 0:

        if momentum > 0:

            long_score += 5

        elif momentum < 0:

            short_score += 5


    # ============================================================
    # DIRECTION
    # ============================================================

    if long_score > short_score:

        direction = "LONG"

        score = long_score

        reasons = long_reasons

        edge = (
            long_score
            -
            short_score
        )


    elif short_score > long_score:

        direction = "SHORT"

        score = short_score

        reasons = short_reasons

        edge = (
            short_score
            -
            long_score
        )


    else:

        direction = "WAIT"

        score = max(
            long_score,
            short_score
        )

        reasons = []

        edge = 0


    # ============================================================
    # STRICT FILTER
    # ============================================================

    rejection = ""


    if direction == "LONG":

        if current_rsi < LONG_RSI_MIN:

            rejection = (
                "LONG RSI too low"
            )

        elif current_rsi > LONG_RSI_MAX:

            rejection = (
                "LONG RSI too high"
            )

        elif momentum <= 0:

            rejection = (
                "LONG momentum not positive"
            )

        elif (
            momentum
            >
            MAX_LONG_MOMENTUM
        ):

            rejection = (
                "LONG momentum overheated"
            )

        elif (
            volume_ratio
            <
            MIN_VOLUME_RATIO
        ):

            rejection = (
                "LONG volume too weak"
            )

        elif ema20 <= ema50:

            rejection = (
                "LONG EMA trend invalid"
            )

        elif edge < MIN_SCORE_EDGE:

            rejection = (
                "LONG score edge too small"
            )


    elif direction == "SHORT":

        if current_rsi < SHORT_RSI_MIN:

            rejection = (
                "SHORT RSI too low"
            )

        elif current_rsi > SHORT_RSI_MAX:

            rejection = (
                "SHORT RSI too high"
            )

        elif momentum >= 0:

            rejection = (
                "SHORT momentum not negative"
            )

        elif (
            abs(momentum)
            >
            MAX_SHORT_MOMENTUM
        ):

            rejection = (
                "SHORT momentum overheated"
            )

        elif (
            volume_ratio
            <
            MIN_VOLUME_RATIO
        ):

            rejection = (
                "SHORT volume too weak"
            )

        elif ema20 >= ema50:

            rejection = (
                "SHORT EMA trend invalid"
            )

        elif edge < MIN_SCORE_EDGE:

            rejection = (
                "SHORT score edge too small"
            )


    # ============================================================
    # ATR STOP
    # ============================================================

    entry = price


    # Use ATR when available.
    # Minimum 1.5% distance protects very tight stops.

    if current_atr is not None:

        atr_percent = (

            current_atr
            /
            entry
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
        entry
        *
        stop_percent
        /
        100
    )


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

    if direction in (
        "LONG",
        "SHORT"
    ):

        risk_value = abs(
            entry
            -
            sl
        )

        reward_value = abs(
            tp2
            -
            entry
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


    # ============================================================
    # FINAL VALIDATION
    # ============================================================

    valid_signal = True


    if score < MIN_SCORE:

        valid_signal = False


    if direction not in (
        "LONG",
        "SHORT"
    ):

        valid_signal = False


    if edge < MIN_SCORE_EDGE:

        valid_signal = False


    if volume_ratio < MIN_VOLUME_RATIO:

        valid_signal = False


    if rr < MIN_RR:

        valid_signal = False


    if rejection:

        valid_signal = False


    # ============================================================
    # SIGNAL TYPE
    # ============================================================

    if valid_signal:

        if score >= STRONG_SCORE:

            signal_type = "STRONG"

        else:

            signal_type = "SIGNAL"

    else:

        signal_type = "WAIT"


    # ============================================================
    # RETURN
    # ============================================================

    return {

        "symbol":
            symbol,

        "direction":
            direction,

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

        "edge":
            edge,

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
            quote_volume,

        "atr":
            current_atr,

        "stop_percent":
            stop_percent,

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
        now
        -
        previous
        >=
        COOLDOWN
    )


# ================================================================
# FORMAT PRICE
# ================================================================

def fmt_price(value):

    if value == 0:

        return "0"

    if abs(value) >= 1000:

        return f"{value:.2f}"

    if abs(value) >= 1:

        return f"{value:.6f}"

    if abs(value) >= 0.01:

        return f"{value:.6f}"

    if abs(value) >= 0.0001:

        return f"{value:.8f}"

    return f"{value:.10g}"


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

        for x in a["reasons"][:8]
    )


    return f"""
{icon} <b>{label} {a["direction"]}</b>
━━━━━━━━━━━━━━━━━━

🪙 <b>{a["symbol"]}</b>

📊 Score:
<b>{a["score"]}/100</b>

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

📏 Stop:
<b>{a["stop_percent"]:.2f}%</b>

📈 RSI:
<b>{a["rsi"]:.2f}</b>

📉 EMA20:
<b>{fmt_price(a["ema20"])}</b>

📉 EMA50:
<b>{fmt_price(a["ema50"])}</b>

🚀 Momentum:
<b>{a["momentum"]:+.2f}%</b>

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
# SCAN SUMMARY
# ================================================================

def summary_message(
    markets,
    candle_ok,
    candle_failed,
    total_rows,
    analyses,
    signals,
    sent
):

    if candle_ok:

        avg_candles = (
            total_rows
            /
            candle_ok
        )

    else:

        avg_candles = 0


    return f"""
🔎 <b>SCAN COMPLETE</b>
━━━━━━━━━━━━━━━━━━

🪙 Markets checked:
<b>{len(markets)}</b>

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

🎯 Valid signals:
<b>{len(signals)}</b>

📨 Signals sent:
<b>{sent}</b>

🎯 Minimum score:
<b>{MIN_SCORE}/100</b>

🔥 Strong:
<b>{STRONG_SCORE}/100</b>

📊 Minimum volume:
<b>x{MIN_VOLUME_RATIO:.2f}</b>

📐 Minimum edge:
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
    print("🐋 OK-EX IRAN V8 PRO SCAN")
    print(datetime.now())
    print("=" * 70)


    # ============================================================
    # MARKETS
    # ============================================================

    tickers = get_tickers()

    pairs = get_pairs()

    markets = discover_markets(
        tickers,
        pairs
    )


    print(
        f"🪙 Markets: {len(markets)}"
    )


    if not markets:

        telegram_send(
            """
🔴 <b>OK-EX ERROR</b>

No USDT markets found.

Ticker / Pair discovery failed.
"""
        )

        return


    # ============================================================
    # ANALYSIS
    # ============================================================

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


            if result is not None:

                analyses.append(
                    result
                )


        except Exception as e:

            print(
                "Analysis error:",
                symbol,
                repr(e)
            )


        time.sleep(
            0.05
        )


        if index % 25 == 0:

            print(
                f"Progress "
                f"{index}/{len(markets)}"
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

        if x["valid_signal"]

    ]


    signals.sort(

        key=lambda x: (

            x["score"],

            x["volume_ratio"],

            x["edge"]

        ),

        reverse=True
    )


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


        success = telegram_send(

            signal_message(
                signal
            )
        )


        if success:

            last_sent[
                symbol
            ] = time.time()

            sent += 1


    # ============================================================
    # SUMMARY
    # ============================================================

    summary = summary_message(

        markets,

        candle_ok,

        candle_failed,

        total_rows,

        analyses,

        signals,

        sent
    )


    print(
        summary
    )


    telegram_send(
        summary
    )


# ================================================================
# STARTUP
# ================================================================

def startup():

    print(
        "🐋 OK-EX IRAN V8 STARTED"
    )

    print(
        "Paper Mode:",
        PAPER_MODE
    )

    print(
        "Real Orders:",
        REAL_ORDERS
    )


    telegram_send(
        """
🟢 <b>OK-EX IRAN V8 PRO STARTED</b>
━━━━━━━━━━━━━━━━━━

🪙 ALL USDT MARKETS

🕯 1H REAL CANDLES

🧠 EMA + RSI + MOMENTUM
+ VOLUME + TREND

🛡 STRICT FILTER:
<b>ON</b>

📊 Minimum Score:
<b>70</b>

📊 Minimum Volume:
<b>x1.20</b>

📐 Minimum Edge:
<b>15</b>

📐 Minimum R/R:
<b>1:2</b>

🎯 Max Signals:
<b>3</b>

🐋 Whale Proxy:
<b>Liquidity / Volume</b>

🟢 PAPER MODE:
<b>ON</b>

🔴 REAL ORDERS:
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


        print(
            f"⏳ Next scan "
            f"in {SCAN_INTERVAL} seconds..."
        )


        time.sleep(
            SCAN_INTERVAL
        )


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":

    main()
