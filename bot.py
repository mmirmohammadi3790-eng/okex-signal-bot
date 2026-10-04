# ================================================================
# 🐋 OK-EX IRAN — FINAL PAPER SIGNAL BOT
# GitHub Actions
#
# ALL USDT MARKETS
# LONG / SHORT / WAIT
# ENTRY / SL / TP1 / TP2 / TP3
#
# REAL OK-EX CANDLES
# start_time + end_time
#
# RSI / EMA20 / EMA50 / MOMENTUM
# VOLUME SPIKE / PRICE ACTION
# LIQUIDITY / WHALE PROXY
#
# PAPER MODE ONLY
# NO REAL ORDERS
# ================================================================

import os
import time
import requests
from datetime import datetime, timezone


# ================================================================
# CONFIG
# ================================================================

OKEX_BASE = "https://sapi.ok-ex.io"

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ================================================================
# BOT SETTINGS
# ================================================================

PAPER_MODE = True
REAL_ORDERS = False

SCAN_INTERVAL = 300

COOLDOWN = 1800

MAX_MARKETS = 9999

MAX_SIGNALS_PER_SCAN = 5

MIN_SCORE = 50

STRONG_SCORE = 70

REQUEST_TIMEOUT = 25

CANDLE_LIMIT = 100

CANDLE_INTERVAL = "1h"

# How many hours of candles to request
CANDLE_HOURS = 100


# ================================================================
# HTTP
# ================================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


session = requests.Session()

session.headers.update(
    HEADERS
)


# ================================================================
# GLOBALS
# ================================================================

last_signal_time = {}

stats = {
    "markets": 0,
    "candle_ok": 0,
    "candle_failed": 0,
    "candle_rows": 0,
    "analysis_ok": 0,
    "candidates": 0,
    "signals_sent": 0,
    "api_errors": 0,
}


# ================================================================
# TIME
# ================================================================

def now_text():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def unix_ms():

    return int(
        time.time() * 1000
    )


def unix_seconds():

    return int(
        time.time()
    )


# ================================================================
# TELEGRAM
# ================================================================

def send_telegram(
    message
):

    if not BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN missing"
        )

        return False

    if not CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID missing"
        )

        return False

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
    }

    try:

        response = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        print(
            "Telegram:",
            response.status_code
        )

        if response.ok:

            return True

        print(
            "Telegram error:",
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "Telegram exception:",
            repr(e)
        )

        return False


# ================================================================
# API REQUEST
# ================================================================

def api_get(
    path,
    params=None,
    quiet=False
):

    url = (
        OKEX_BASE
        + path
    )

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if not quiet:

            print()
            print(
                "GET:",
                response.url
            )

            print(
                "STATUS:",
                response.status_code
            )

        if not response.ok:

            stats[
                "api_errors"
            ] += 1

            if not quiet:

                print(
                    "API ERROR:",
                    response.text[:1000]
                )

            return None

        try:

            return response.json()

        except Exception as e:

            stats[
                "api_errors"
            ] += 1

            print(
                "JSON ERROR:",
                repr(e)
            )

            print(
                "RAW:",
                response.text[:1000]
            )

            return None

    except Exception as e:

        stats[
            "api_errors"
        ] += 1

        print(
            "REQUEST ERROR:",
            path,
            repr(e)
        )

        return None


# ================================================================
# EXTRACT LIST
# ================================================================

def extract_list(
    data
):

    if data is None:

        return []

    if isinstance(
        data,
        list
    ):

        return data

    if not isinstance(
        data,
        dict
    ):

        return []

    keys = [
        "res",
        "data",
        "result",
        "rows",
        "list",
        "items",
        "records",
    ]

    for key in keys:

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

            for subkey in keys:

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
# NORMALIZE SYMBOL
# ================================================================

def normalize_symbol(
    symbol
):

    if symbol is None:

        return None

    value = str(
        symbol
    ).upper().strip()

    value = value.replace(
        "_",
        "-"
    )

    value = value.replace(
        "/",
        "-"
    )

    if value.endswith(
        "-USDT"
    ):

        return value

    if value.endswith(
        "USDT"
    ):

        base = value[:-4]

        if base:

            return (
                base
                + "-USDT"
            )

    return value


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    print()
    print(
        "📡 Loading OK-EX tickers..."
    )

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_list(
        data
    )

    print(
        "Raw ticker rows:",
        len(rows)
    )

    result = {}

    for row in rows:

        if not isinstance(
            row,
            dict
        ):

            continue

        symbol = (
            row.get("symbol")
            or row.get("instId")
            or row.get("market")
            or row.get("pair")
            or row.get("code")
        )

        symbol = normalize_symbol(
            symbol
        )

        if not symbol:

            continue

        if not symbol.endswith(
            "-USDT"
        ):

            continue

        price = (
            row.get("last")
            or row.get("lastPrice")
            or row.get("close")
            or row.get("price")
        )

        try:

            price = float(
                price
            )

        except Exception:

            continue

        if price <= 0:

            continue

        volume = (
            row.get("volume")
            or row.get("vol")
            or row.get("baseVolume")
            or 0
        )

        quote_volume = (
            row.get("quoteVolume")
            or row.get("quoteVol")
            or row.get("turnover")
            or row.get("amount")
            or 0
        )

        change = (
            row.get("change")
            or row.get("changeRate")
            or row.get("priceChangePercent")
            or 0
        )

        try:

            volume = float(
                volume
            )

        except Exception:

            volume = 0.0

        try:

            quote_volume = float(
                quote_volume
            )

        except Exception:

            quote_volume = 0.0

        try:

            change = float(
                change
            )

        except Exception:

            change = 0.0

        result[
            symbol
        ] = {
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "quote_volume": quote_volume,
            "change": change,
        }

    print(
        "Valid USDT tickers:",
        len(result)
    )

    return result


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    print()
    print(
        "📋 Loading OK-EX pairs..."
    )

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    rows = extract_list(
        data
    )

    print(
        "Raw pair rows:",
        len(rows)
    )

    symbols = set()

    for row in rows:

        if isinstance(
            row,
            str
        ):

            symbol = normalize_symbol(
                row
            )

        elif isinstance(
            row,
            dict
        ):

            symbol = (
                row.get("symbol")
                or row.get("instId")
                or row.get("market")
                or row.get("pair")
                or row.get("code")
            )

            symbol = normalize_symbol(
                symbol
            )

        else:

            symbol = None

        if (
            symbol
            and symbol.endswith(
                "-USDT"
            )
        ):

            symbols.add(
                symbol
            )

    print(
        "Valid USDT pairs:",
        len(symbols)
    )

    return symbols


# ================================================================
# SAFE FLOAT
# ================================================================

def safe_float(
    value
):

    try:

        if value is None:

            return None

        return float(
            value
        )

    except Exception:

        return None


# ================================================================
# PARSE CANDLE
# ================================================================

def parse_candle(
    row
):

    # ------------------------------------------------------------
    # DICTIONARY FORMAT
    # ------------------------------------------------------------

    if isinstance(
        row,
        dict
    ):

        close = (
            row.get("close")
            or row.get("c")
            or row.get("last")
        )

        high = (
            row.get("high")
            or row.get("h")
        )

        low = (
            row.get("low")
            or row.get("l")
        )

        volume = (
            row.get("volume")
            or row.get("vol")
            or row.get("v")
            or 0
        )

        close = safe_float(
            close
        )

        high = safe_float(
            high
        )

        low = safe_float(
            low
        )

        volume = safe_float(
            volume
        )

        if volume is None:

            volume = 0.0

        if (
            close is not None
            and high is not None
            and low is not None
        ):

            return {
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
            }

        return None

    # ------------------------------------------------------------
    # ARRAY FORMAT
    # ------------------------------------------------------------

    if isinstance(
        row,
        list
    ):

        if len(row) < 6:

            return None

        # Expected:
        # timestamp
        # open
        # high
        # low
        # close
        # volume

        close = safe_float(
            row[4]
        )

        high = safe_float(
            row[2]
        )

        low = safe_float(
            row[3]
        )

        volume = safe_float(
            row[5]
        )

        if volume is None:

            volume = 0.0

        if (
            close is not None
            and high is not None
            and low is not None
        ):

            return {
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
            }

    return None


# ================================================================
# GET CANDLES
# ================================================================

def get_candles(
    symbol,
    interval="1h",
    limit=100
):

    print(
        "🕯 Candle:",
        symbol
    )

    # ------------------------------------------------------------
    # CURRENT TIME
    # ------------------------------------------------------------

    end_ms = unix_ms()

    start_ms = (
        end_ms
        - (
            CANDLE_HOURS
            * 60
            * 60
            * 1000
        )
    )

    # ------------------------------------------------------------
    # FIRST ATTEMPT
    # MILLISECONDS
    # ------------------------------------------------------------

    params_ms = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
        "start_time": start_ms,
        "end_time": end_ms,
    }

    data = api_get(
        "/api/v1/spot/public/candles",
        params=params_ms,
        quiet=True
    )

    rows = extract_list(
        data
    )

    # ------------------------------------------------------------
    # SECOND ATTEMPT
    # SECONDS
    # ------------------------------------------------------------

    if not rows:

        end_sec = unix_seconds()

        start_sec = (
            end_sec
            - (
                CANDLE_HOURS
                * 60
                * 60
            )
        )

        params_sec = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
            "start_time": start_sec,
            "end_time": end_sec,
        }

        print(
            "↪ Candle retry using seconds:",
            symbol
        )

        data = api_get(
            "/api/v1/spot/public/candles",
            params=params_sec,
            quiet=True
        )

        rows = extract_list(
            data
        )

    # ------------------------------------------------------------
    # NOTHING
    # ------------------------------------------------------------

    if not rows:

        stats[
            "candle_failed"
        ] += 1

        # Print the actual response for first failures
        print(
            "❌ No candle rows:",
            symbol
        )

        if isinstance(
            data,
            dict
        ):

            print(
                "Candle response:",
                str(data)[:1500]
            )

        return []

    # ------------------------------------------------------------
    # PARSE
    # ------------------------------------------------------------

    candles = []

    for row in rows:

        parsed = parse_candle(
            row
        )

        if parsed:

            candles.append(
                parsed
            )

    # ------------------------------------------------------------
    # RESULT
    # ------------------------------------------------------------

    if len(candles) >= 30:

        stats[
            "candle_ok"
        ] += 1

        stats[
            "candle_rows"
        ] += len(candles)

        print(
            "✅ Candle OK:",
            symbol,
            len(candles)
        )

    else:

        stats[
            "candle_failed"
        ] += 1

        print(
            "⚠️ Not enough candles:",
            symbol,
            len(candles)
        )

    return candles


# ================================================================
# EMA
# ================================================================

def calculate_ema(
    values,
    period
):

    if len(values) < period:

        return None

    multiplier = (
        2.0
        / (
            period
            + 1.0
        )
    )

    value = (
        sum(
            values[:period]
        )
        / period
    )

    for price in values[period:]:

        value = (
            (
                price
                - value
            )
            * multiplier
        ) + value

    return value


# ================================================================
# RSI
# ================================================================

def calculate_rsi(
    values,
    period=14
):

    if len(values) < (
        period + 1
    ):

        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        if change > 0:

            gains.append(
                change
            )

            losses.append(
                0.0
            )

        else:

            gains.append(
                0.0
            )

            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(
            gains[:period]
        )
        / period
    )

    avg_loss = (
        sum(
            losses[:period]
        )
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
        100.0
        - (
            100.0
            / (
                1.0 + rs
            )
        )
    )


# ================================================================
# MARKET ANALYSIS
# ================================================================

def analyze_market(
    symbol,
    ticker
):

    candles = get_candles(
        symbol,
        CANDLE_INTERVAL,
        CANDLE_LIMIT
    )

    if len(candles) < 30:

        return None

    closes = [
        c["close"]
        for c in candles
    ]

    highs = [
        c["high"]
        for c in candles
    ]

    lows = [
        c["low"]
        for c in candles
    ]

    volumes = [
        c["volume"]
        for c in candles
    ]

    price = float(
        ticker[
            "price"
        ]
    )

    # ------------------------------------------------------------
    # INDICATORS
    # ------------------------------------------------------------

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    rsi = calculate_rsi(
        closes,
        14
    )

    if (
        ema20 is None
        or ema50 is None
        or rsi is None
    ):

        return None

    long_score = 0

    short_score = 0

    long_reasons = []

    short_reasons = []

    # ============================================================
    # PRICE VS EMA20
    # ============================================================

    if price > ema20:

        long_score += 15

        long_reasons.append(
            "Price > EMA20"
        )

    else:

        short_score += 15

        short_reasons.append(
            "Price < EMA20"
        )

    # ============================================================
    # EMA20 VS EMA50
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
    # RSI
    # ============================================================

    if (
        rsi >= 52
        and rsi <= 70
    ):

        long_score += 15

        long_reasons.append(
            "Bullish RSI"
        )

    elif (
        rsi >= 30
        and rsi <= 48
    ):

        short_score += 15

        short_reasons.append(
            "Bearish RSI"
        )

    elif rsi < 30:

        long_score += 10

        long_reasons.append(
            "RSI Oversold"
        )

    elif rsi > 70:

        short_score += 10

        short_reasons.append(
            "RSI Overbought"
        )

    # ============================================================
    # MOMENTUM
    # ============================================================

    momentum = 0.0

    if len(closes) >= 6:

        old_price = closes[-6]

        if old_price > 0:

            momentum = (
                (
                    closes[-1]
                    / old_price
                )
                - 1.0
            ) * 100

            if momentum > 0.30:

                long_score += 15

                long_reasons.append(
                    f"Momentum +{momentum:.2f}%"
                )

            elif momentum < -0.30:

                short_score += 15

                short_reasons.append(
                    f"Momentum {momentum:.2f}%"
                )

    # ============================================================
    # VOLUME
    # ============================================================

    volume_ratio = 1.0

    if len(volumes) >= 21:

        avg_volume = (
            sum(
                volumes[-21:-1]
            )
            / 20
        )

        if avg_volume > 0:

            volume_ratio = (
                volumes[-1]
                / avg_volume
            )

            if volume_ratio >= 1.20:

                if price > ema20:

                    long_score += 10

                    long_reasons.append(
                        f"Volume x{volume_ratio:.1f}"
                    )

                else:

                    short_score += 10

                    short_reasons.append(
                        f"Volume x{volume_ratio:.1f}"
                    )

    # ============================================================
    # BREAKOUT
    # ============================================================

    if len(candles) >= 3:

        previous_high = highs[-2]

        previous_low = lows[-2]

        current_close = closes[-1]

        if current_close > previous_high:

            long_score += 10

            long_reasons.append(
                "Breakout"
            )

        elif current_close < previous_low:

            short_score += 10

            short_reasons.append(
                "Breakdown"
            )

    # ============================================================
    # SHORT TERM TREND
    # ============================================================

    if len(closes) >= 10:

        old = closes[-10]

        if old > 0:

            trend10 = (
                (
                    closes[-1]
                    / old
                )
                - 1
            ) * 100

            if trend10 > 0.70:

                long_score += 5

                long_reasons.append(
                    "10-candle strength"
                )

            elif trend10 < -0.70:

                short_score += 5

                short_reasons.append(
                    "10-candle weakness"
                )

    # ============================================================
    # LIQUIDITY / WHALE PROXY
    # ============================================================

    quote_volume = ticker.get(
        "quote_volume",
        0
    )

    if quote_volume >= 50000:

        if long_score > short_score:

            long_score += 5

            long_reasons.append(
                "Liquidity proxy"
            )

        elif short_score > long_score:

            short_score += 5

            short_reasons.append(
                "Liquidity proxy"
            )

    # ============================================================
    # SELECT DIRECTION
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

        return None

    # ============================================================
    # MINIMUM SCORE
    # ============================================================

    if score < MIN_SCORE:

        return None

    # ============================================================
    # SCORE DIFFERENCE
    # ============================================================

    difference = abs(
        long_score
        - short_score
    )

    if difference < 10:

        return None

    # ============================================================
    # ENTRY
    # ============================================================

    entry = price

    # ============================================================
    # LONG
    # ============================================================

    if direction == "LONG":

        sl = (
            entry
            * 0.985
        )

        risk = (
            entry
            - sl
        )

        tp1 = (
            entry
            + risk
        )

        tp2 = (
            entry
            + risk * 2
        )

        tp3 = (
            entry
            + risk * 3
        )

    # ============================================================
    # SHORT
    # ============================================================

    else:

        sl = (
            entry
            * 1.015
        )

        risk = (
            sl
            - entry
        )

        tp1 = (
            entry
            - risk
        )

        tp2 = (
            entry
            - risk * 2
        )

        tp3 = (
            entry
            - risk * 3
        )

    stats[
        "analysis_ok"
    ] += 1

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "momentum": momentum,
        "volume_ratio": volume_ratio,
        "change": ticker.get(
            "change",
            0
        ),
        "reasons": reasons,
    }


# ================================================================
# SIGNAL MESSAGE
# ================================================================

def make_signal_message(
    signal
):

    direction = signal[
        "direction"
    ]

    if direction == "LONG":

        emoji = "🟢"

    else:

        emoji = "🔴"

    if signal[
        "score"
    ] >= STRONG_SCORE:

        strength = "🔥 STRONG"

    else:

        strength = "⚡ SIGNAL"

    reasons = ", ".join(
        signal[
            "reasons"
        ][:6]
    )

    return (
        f"{emoji} {strength} {direction}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 {signal['symbol']}\n"
        f"📊 Score: {signal['score']}/100\n\n"

        f"🎯 Entry: {signal['entry']:.8g}\n"
        f"🛑 SL: {signal['sl']:.8g}\n"
        f"🥇 TP1: {signal['tp1']:.8g}\n"
        f"🥈 TP2: {signal['tp2']:.8g}\n"
        f"🥉 TP3: {signal['tp3']:.8g}\n\n"

        f"📈 RSI: {signal['rsi']:.2f}\n"
        f"EMA20: {signal['ema20']:.8g}\n"
        f"EMA50: {signal['ema50']:.8g}\n"
        f"Momentum: {signal['momentum']:.2f}%\n"
        f"Volume: x{signal['volume_ratio']:.2f}\n\n"

        f"🐋 Whale/Liquidity Proxy: ACTIVE\n\n"

        f"🧠 Reasons:\n"
        f"{reasons}\n\n"

        f"💵 PAPER SIGNAL ONLY\n"
        f"🔴 REAL ORDERS: OFF\n\n"

        f"⏰ {now_text()}"
    )


# ================================================================
# STARTUP MESSAGE
# ================================================================

def send_startup():

    message = (
        "🟢 OK-EX BOT STARTED\n\n"

        "📡 OK-EX API: ONLINE\n"
        "🐋 Scanner: ONLINE\n"
        "🟢 Paper Mode: ON\n"
        "🔴 Real Orders: OFF\n\n"

        "🔎 Market discovery starting...\n\n"

        f"🎯 Minimum Score: {MIN_SCORE}/100\n"
        f"🔥 Strong Score: {STRONG_SCORE}/100\n"
        f"📨 Max signals/scan: {MAX_SIGNALS_PER_SCAN}\n\n"

        "🕯 Real Candle: ON\n"
        "⏱ start_time/end_time: ON\n\n"

        f"⏰ {now_text()}"
    )

    send_telegram(
        message
    )


# ================================================================
# SUMMARY
# ================================================================

def make_summary():

    avg_candles = 0

    if stats[
        "candle_ok"
    ] > 0:

        avg_candles = (
            stats[
                "candle_rows"
            ]
            /
            stats[
                "candle_ok"
            ]
        )

    return (
        "🔎 SCAN COMPLETE\n\n"

        f"🪙 Markets checked: "
        f"{stats['markets']}\n"

        f"🕯 Candle OK: "
        f"{stats['candle_ok']}\n"

        f"❌ Candle failed: "
        f"{stats['candle_failed']}\n"

        f"📚 Candle rows: "
        f"{stats['candle_rows']}\n"

        f"📐 Avg candles: "
        f"{avg_candles:.1f}\n\n"

        f"🧠 Analysis passed: "
        f"{stats['analysis_ok']}\n"

        f"🎯 Signals found: "
        f"{stats['candidates']}\n"

        f"📨 Signals sent: "
        f"{stats['signals_sent']}\n\n"

        f"🎯 Minimum score: "
        f"{MIN_SCORE}/100\n"

        f"🔥 Strong score: "
        f"{STRONG_SCORE}/100\n\n"

        "🟢 Paper Mode: ON\n"
        "🔴 Real Orders: OFF\n\n"

        f"⏰ {now_text()}"
    )


# ================================================================
# SCAN
# ================================================================

def scan():

    print()
    print("=" * 80)
    print(
        "🚀 SCAN START",
        now_text()
    )
    print("=" * 80)

    # ------------------------------------------------------------
    # RESET
    # ------------------------------------------------------------

    stats[
        "candle_ok"
    ] = 0

    stats[
        "candle_failed"
    ] = 0

    stats[
        "candle_rows"
    ] = 0

    stats[
        "analysis_ok"
    ] = 0

    stats[
        "candidates"
    ] = 0

    stats[
        "signals_sent"
    ] = 0

    # ------------------------------------------------------------
    # LOAD
    # ------------------------------------------------------------

    tickers = get_tickers()

    pairs = get_pairs()

    # ------------------------------------------------------------
    # MARKET SELECTION
    # ------------------------------------------------------------

    symbols = set()

    if tickers and pairs:

        symbols = (
            set(
                tickers.keys()
            )
            &
            pairs
        )

    if not symbols:

        symbols = set(
            tickers.keys()
        )

    if not symbols:

        symbols = set(
            pairs
        )

    # ------------------------------------------------------------
    # NO MARKET
    # ------------------------------------------------------------

    if not symbols:

        send_telegram(
            "⚠️ OK-EX MARKET ERROR\n\n"
            "No USDT markets returned by API."
        )

        return

    # ------------------------------------------------------------
    # SORT BY LIQUIDITY
    # ------------------------------------------------------------

    symbols = list(
        symbols
    )

    symbols.sort(
        key=lambda x:
        tickers.get(
            x,
            {}
        ).get(
            "quote_volume",
            0
        ),
        reverse=True
    )

    if MAX_MARKETS > 0:

        symbols = symbols[
            :MAX_MARKETS
        ]

    stats[
        "markets"
    ] = len(symbols)

    print()
    print(
        "📊 Markets:",
        len(symbols)
    )

    # ------------------------------------------------------------
    # ANALYZE
    # ------------------------------------------------------------

    candidates = []

    for index, symbol in enumerate(
        symbols
    ):

        print(
            f"[{index + 1}/{len(symbols)}] "
            f"{symbol}"
        )

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            continue

        try:

            signal = analyze_market(
                symbol,
                ticker
            )

            if signal:

                print(
                    "🎯 CANDIDATE:",
                    symbol,
                    signal[
                        "direction"
                    ],
                    signal[
                        "score"
                    ]
                )

                candidates.append(
                    signal
                )

        except Exception as e:

            stats[
                "api_errors"
            ] += 1

            print(
                "❌ Analysis error:",
                symbol,
                repr(e)
            )

        time.sleep(
            0.08
        )

    # ------------------------------------------------------------
    # SORT
    # ------------------------------------------------------------

    candidates.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    stats[
        "candidates"
    ] = len(
        candidates
    )

    # ------------------------------------------------------------
    # SEND
    # ------------------------------------------------------------

    sent = 0

    for signal in candidates:

        symbol = signal[
            "symbol"
        ]

        last_time = (
            last_signal_time.get(
                symbol,
                0
            )
        )

        if (
            time.time()
            - last_time
            < COOLDOWN
        ):

            print(
                "⏳ Cooldown:",
                symbol
            )

            continue

        message = make_signal_message(
            signal
        )

        if send_telegram(
            message
        ):

            last_signal_time[
                symbol
            ] = time.time()

            sent += 1

            stats[
                "signals_sent"
            ] += 1

        if sent >= MAX_SIGNALS_PER_SCAN:

            break

    # ------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------

    summary = make_summary()

    print()
    print(summary)

    send_telegram(
        summary
    )


# ================================================================
# MAIN
# ================================================================

def main():

    print()
    print("=" * 80)
    print(
        "🐋 OK-EX IRAN PAPER SIGNAL BOT"
    )
    print("=" * 80)

    print(
        "Telegram token:",
        "SET"
        if BOT_TOKEN
        else "MISSING"
    )

    print(
        "Telegram chat ID:",
        "SET"
        if CHAT_ID
        else "MISSING"
    )

    print(
        "OK-EX:",
        OKEX_BASE
    )

    print(
        "Paper mode:",
        PAPER_MODE
    )

    print(
        "Real orders:",
        REAL_ORDERS
    )

    # ------------------------------------------------------------
    # CHECK SECRETS
    # ------------------------------------------------------------

    if not BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN missing"
        )

        return

    if not CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID missing"
        )

        return

    # ------------------------------------------------------------
    # START
    # ------------------------------------------------------------

    send_startup()

    # ------------------------------------------------------------
    # FIRST SCAN
    # ------------------------------------------------------------

    scan()

    # ------------------------------------------------------------
    # LOOP
    # ------------------------------------------------------------

    while True:

        try:

            print()
            print(
                f"⏳ Next scan in "
                f"{SCAN_INTERVAL} seconds..."
            )

            time.sleep(
                SCAN_INTERVAL
            )

            scan()

        except KeyboardInterrupt:

            print(
                "🛑 BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "❌ MAIN LOOP ERROR:",
                repr(e)
            )

            send_telegram(
                "⚠️ BOT ERROR\n\n"
                + str(e)[:1000]
            )

            time.sleep(
                30
            )


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":

    main()
