# ================================================================
# 🐋 OK-EX IRAN — V4 FINAL STABLE
# GitHub Actions / PAPER SIGNAL ONLY
#
# ALL USDT MARKETS
# REAL OK-EX CANDLES
# LONG / SHORT / WAIT
# ENTRY / SL / TP1 / TP2 / TP3
# RSI / EMA20 / EMA50 / MOMENTUM / VOLUME
#
# PAPER MODE ONLY
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

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

# ------------------------------------------------
# SAFETY
# ------------------------------------------------

PAPER_MODE = True
REAL_ORDERS = False

# ------------------------------------------------
# SCANNER
# ------------------------------------------------

SCAN_INTERVAL = 300
COOLDOWN = 1800

MAX_MARKETS = 9999
MAX_SIGNALS_PER_SCAN = 5

# ------------------------------------------------
# SCORE
# ------------------------------------------------

MIN_SCORE = 50
STRONG_SCORE = 70

# ------------------------------------------------
# HTTP
# ------------------------------------------------

REQUEST_TIMEOUT = 20

# ------------------------------------------------
# CANDLES
# ------------------------------------------------

CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100
CANDLE_HOURS = 120


# ================================================================
# HTTP SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "OKEX-Iran-Paper-Bot/4.0",
    "Accept": "application/json",
})


# ================================================================
# GLOBALS
# ================================================================

last_signal_time = {}

stats = {
    "markets": 0,
    "ticker_markets": 0,
    "pair_markets": 0,
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


# ================================================================
# TELEGRAM
# ================================================================

def send_telegram(message):

    if not BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN missing"
        )

        return False

    if not CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID missing"
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
            response.text[:1000]
        )

        return False

    except Exception as e:

        print(
            "Telegram exception:",
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
            timeout=REQUEST_TIMEOUT
        )

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

            stats["api_errors"] += 1

            print(
                "❌ API ERROR:"
            )

            print(
                response.text[:3000]
            )

            return None

        try:

            return response.json()

        except Exception:

            stats["api_errors"] += 1

            print(
                "❌ JSON ERROR"
            )

            print(
                response.text[:3000]
            )

            return None

    except Exception as e:

        stats["api_errors"] += 1

        print(
            "❌ REQUEST ERROR:",
            repr(e)
        )

        return None


# ================================================================
# EXTRACT LIST
# ================================================================

def extract_list(data):

    if data is None:

        return []

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
        "items",
        "records",
        "candles",
        "tickers",
        "pairs",
    ]

    # Direct search
    for key in keys:

        value = data.get(key)

        if isinstance(
            value,
            list
        ):

            return value

    # Nested search
    for key in keys:

        value = data.get(key)

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
# SYMBOL NORMALIZATION
# ================================================================

def normalize_symbol(symbol):

    if symbol is None:

        return None

    value = str(
        symbol
    ).upper().strip()

    value = value.replace(
        "_",
        ""
    )

    value = value.replace(
        "/",
        ""
    )

    value = value.replace(
        "-",
        ""
    )

    return value


# ================================================================
# DISPLAY SYMBOL
# ================================================================

def display_symbol(symbol):

    symbol = normalize_symbol(
        symbol
    )

    if (
        symbol
        and symbol.endswith("USDT")
    ):

        return (
            symbol[:-4]
            + "-USDT"
        )

    return symbol


# ================================================================
# SAFE FLOAT
# ================================================================

def safe_float(value):

    try:

        if value is None:

            return None

        return float(value)

    except Exception:

        return None


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    print()
    print("=" * 70)
    print(
        "📡 LOADING OK-EX TICKERS"
    )
    print("=" * 70)

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
            "USDT"
        ):

            continue

        price = (
            row.get("lastPrice")
            or row.get("last")
            or row.get("close")
            or row.get("price")
        )

        price = safe_float(
            price
        )

        if (
            price is None
            or price <= 0
        ):

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
            row.get("priceChangePercent")
            or row.get("changeRate")
            or row.get("change")
            or 0
        )

        volume = (
            safe_float(volume)
            or 0.0
        )

        quote_volume = (
            safe_float(
                quote_volume
            )
            or 0.0
        )

        change = (
            safe_float(change)
            or 0.0
        )

        result[symbol] = {
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "quote_volume": quote_volume,
            "change": change,
        }

    stats[
        "ticker_markets"
    ] = len(result)

    print(
        "✅ Valid USDT tickers:",
        len(result)
    )

    return result


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    print()
    print("=" * 70)
    print(
        "📋 LOADING OK-EX PAIRS"
    )
    print("=" * 70)

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
                "USDT"
            )
        ):

            symbols.add(
                symbol
            )

    stats[
        "pair_markets"
    ] = len(symbols)

    print(
        "✅ Valid USDT pairs:",
        len(symbols)
    )

    return symbols


# ================================================================
# CANDLE PARSER
# ================================================================

def parse_candle(row):

    # ------------------------------------------------------------
    # DICT
    # ------------------------------------------------------------

    if isinstance(
        row,
        dict
    ):

        timestamp = (
            row.get("timestamp")
            or row.get("time")
            or row.get("ts")
            or row.get("openTime")
        )

        open_price = (
            row.get("open")
            or row.get("o")
            or row.get("openPrice")
        )

        high = (
            row.get("high")
            or row.get("h")
            or row.get("highPrice")
        )

        low = (
            row.get("low")
            or row.get("l")
            or row.get("lowPrice")
        )

        close = (
            row.get("close")
            or row.get("c")
            or row.get("last")
            or row.get("closePrice")
        )

        volume = (
            row.get("volume")
            or row.get("vol")
            or row.get("v")
            or 0
        )

        open_price = safe_float(
            open_price
        )

        high = safe_float(
            high
        )

        low = safe_float(
            low
        )

        close = safe_float(
            close
        )

        volume = (
            safe_float(
                volume
            )
            or 0.0
        )

        if (
            open_price is not None
            and high is not None
            and low is not None
            and close is not None
        ):

            return {
                "timestamp": timestamp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }

        return None

    # ------------------------------------------------------------
    # ARRAY
    # ------------------------------------------------------------

    if isinstance(
        row,
        list
    ):

        if len(row) < 6:

            return None

        timestamp = row[0]

        open_price = safe_float(
            row[1]
        )

        high = safe_float(
            row[2]
        )

        low = safe_float(
            row[3]
        )

        close = safe_float(
            row[4]
        )

        volume = safe_float(
            row[5]
        )

        if (
            open_price is None
            or high is None
            or low is None
            or close is None
        ):

            return None

        return {
            "timestamp": timestamp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": (
                volume
                or 0.0
            ),
        }

    return None


# ================================================================
# CANDLE API
# ================================================================

def get_candles(
    symbol,
    interval="1h",
    limit=100
):

    api_symbol = normalize_symbol(
        symbol
    )

    end_time = unix_ms()

    start_time = (
        end_time
        - (
            CANDLE_HOURS
            * 60
            * 60
            * 1000
        )
    )

    params = {
        "symbol": api_symbol,
        "interval": interval,
        "startTime": start_time,
        "endTime": end_time,
        "limit": limit,
    }

    print()
    print(
        "🕯 CANDLE REQUEST"
    )

    print(
        "Symbol:",
        api_symbol
    )

    print(
        "Interval:",
        interval
    )

    print(
        "Limit:",
        limit
    )

    data = api_get(
        "/api/v1/spot/public/candles",
        params=params
    )

    if data is None:

        stats[
            "candle_failed"
        ] += 1

        return []

    rows = extract_list(
        data
    )

    print(
        "Extracted candle rows:",
        len(rows)
    )

    candles = []

    for row in rows:

        parsed = parse_candle(
            row
        )

        if parsed:

            candles.append(
                parsed
            )

    print(
        "Parsed candles:",
        len(candles)
    )

    # ------------------------------------------------------------
    # SORT BY TIME
    # ------------------------------------------------------------

    try:

        candles.sort(
            key=lambda x:
            float(
                x.get(
                    "timestamp",
                    0
                )
                or 0
            )
        )

    except Exception:

        pass

    if len(candles) >= 30:

        stats[
            "candle_ok"
        ] += 1

        stats[
            "candle_rows"
        ] += len(candles)

        print(
            "✅ CANDLE OK"
        )

        return candles

    stats[
        "candle_failed"
    ] += 1

    print(
        "❌ CANDLE FAILED"
    )

    return []


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
                * (
                    period - 1
                )
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (
                    period - 1
                )
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

    price = ticker[
        "price"
    ]

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

    if 52 <= rsi <= 70:

        long_score += 15

        long_reasons.append(
            "Bullish RSI"
        )

    elif 30 <= rsi <= 48:

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
    # BREAKOUT / BREAKDOWN
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
    # 10 CANDLE TREND
    # ============================================================

    trend10 = 0.0

    if len(closes) >= 10:

        old = closes[-10]

        if old > 0:

            trend10 = (
                (
                    closes[-1]
                    / old
                )
                - 1.0
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

        return None

    # ============================================================
    # FILTER
    # ============================================================

    difference = abs(
        long_score
        - short_score
    )

    if score < MIN_SCORE:

        return None

    if difference < 10:

        return None

    # ============================================================
    # ENTRY / SL / TP
    # ============================================================

    entry = price

    # 1.5% stop
    stop_percent = 0.015

    if direction == "LONG":

        sl = (
            entry
            * (
                1.0
                - stop_percent
            )
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
            + (
                risk * 2
            )
        )

        tp3 = (
            entry
            + (
                risk * 3
            )
        )

    else:

        sl = (
            entry
            * (
                1.0
                + stop_percent
            )
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
            - (
                risk * 2
            )
        )

        tp3 = (
            entry
            - (
                risk * 3
            )
        )

    stats[
        "analysis_ok"
    ] += 1

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "long_score": long_score,
        "short_score": short_score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "momentum": momentum,
        "trend10": trend10,
        "volume_ratio": volume_ratio,
        "quote_volume": quote_volume,
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

    if signal[
        "direction"
    ] == "LONG":

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
        f"{emoji} {strength} "
        f"{signal['direction']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"

        f"🪙 "
        f"{display_symbol(signal['symbol'])}\n"

        f"📊 Score: "
        f"{signal['score']}/100\n"

        f"🟢 Long Score: "
        f"{signal['long_score']}\n"

        f"🔴 Short Score: "
        f"{signal['short_score']}\n\n"

        f"🎯 Entry: "
        f"{signal['entry']:.8g}\n"

        f"🛑 SL: "
        f"{signal['sl']:.8g}\n"

        f"🥇 TP1: "
        f"{signal['tp1']:.8g}\n"

        f"🥈 TP2: "
        f"{signal['tp2']:.8g}\n"

        f"🥉 TP3: "
        f"{signal['tp3']:.8g}\n\n"

        f"📈 RSI: "
        f"{signal['rsi']:.2f}\n"

        f"EMA20: "
        f"{signal['ema20']:.8g}\n"

        f"EMA50: "
        f"{signal['ema50']:.8g}\n"

        f"Momentum: "
        f"{signal['momentum']:.2f}%\n"

        f"Trend 10H: "
        f"{signal['trend10']:.2f}%\n"

        f"Volume: "
        f"x{signal['volume_ratio']:.2f}\n\n"

        f"🐋 Liquidity Proxy: "
        f"ACTIVE\n\n"

        f"🧠 Reasons:\n"
        f"{reasons}\n\n"

        f"💵 PAPER SIGNAL ONLY\n"
        f"🔴 REAL ORDERS: OFF\n\n"

        f"⏰ {now_text()}"
    )


# ================================================================
# STARTUP
# ================================================================

def send_startup():

    message = (
        "🟢 OK-EX BOT STARTED\n\n"

        "📡 OK-EX API: ONLINE\n"
        "🐋 Scanner: ONLINE\n"
        "🟢 Paper Mode: ON\n"
        "🔴 Real Orders: OFF\n\n"

        "🔎 Market discovery starting...\n\n"

        f"🎯 Minimum Score: "
        f"{MIN_SCORE}/100\n"

        f"🔥 Strong Score: "
        f"{STRONG_SCORE}/100\n"

        f"📨 Max signals/scan: "
        f"{MAX_SIGNALS_PER_SCAN}\n\n"

        "🕯 Real Candle: ON\n"
        "⏱ Official startTime/endTime: ON\n\n"

        f"⏰ {now_text()}"
    )

    send_telegram(
        message
    )


# ================================================================
# CANDLE TEST
# ================================================================

def candle_test():

    print()
    print("=" * 80)

    print(
        "🧪 OFFICIAL OK-EX "
        "SOLUSDT CANDLE TEST"
    )

    print("=" * 80)

    candles = get_candles(
        "SOLUSDT",
        "1h",
        100
    )

    if candles:

        message = (
            "🟢 OK-EX CANDLE TEST PASSED\n\n"

            "🪙 Symbol: SOLUSDT\n"

            f"🕯 Candles: "
            f"{len(candles)}\n"

            "📡 API: ONLINE\n"

            "⏱ startTime/endTime: OK\n\n"

            "Scanner can continue."
        )

        send_telegram(
            message
        )

        print()
        print(
            "✅ CANDLE TEST PASSED"
        )

        return True

    message = (
        "🔴 OK-EX CANDLE TEST FAILED\n\n"

        "🪙 Symbol: SOLUSDT\n"

        "🕯 Candles: 0\n\n"

        "The bot will NOT start "
        "the full scanner.\n\n"

        "Check GitHub Actions log."
    )

    send_telegram(
        message
    )

    print()
    print(
        "❌ CANDLE TEST FAILED"
    )

    return False


# ================================================================
# SUMMARY
# ================================================================

def make_summary():

    avg = 0.0

    if stats[
        "candle_ok"
    ] > 0:

        avg = (
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

        f"📡 Ticker markets: "
        f"{stats['ticker_markets']}\n"

        f"📋 Pair markets: "
        f"{stats['pair_markets']}\n\n"

        f"🕯 Candle OK: "
        f"{stats['candle_ok']}\n"

        f"❌ Candle failed: "
        f"{stats['candle_failed']}\n"

        f"📚 Candle rows: "
        f"{stats['candle_rows']}\n"

        f"📐 Avg candles: "
        f"{avg:.1f}\n\n"

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
# MARKET DISCOVERY
# ================================================================

def discover_markets():

    print()
    print("=" * 80)

    print(
        "🔎 MARKET DISCOVERY"
    )

    print("=" * 80)

    tickers = get_tickers()

    pairs = get_pairs()

    ticker_symbols = set(
        tickers.keys()
    )

    pair_symbols = set(
        pairs
    )

    print()
    print(
        "Ticker USDT:",
        len(ticker_symbols)
    )

    print(
        "Pair USDT:",
        len(pair_symbols)
    )

    # ------------------------------------------------------------
    # PREFERRED:
    # INTERSECTION
    # ------------------------------------------------------------

    symbols = (
        ticker_symbols
        & pair_symbols
    )

    print(
        "Intersection:",
        len(symbols)
    )

    # ------------------------------------------------------------
    # FALLBACK:
    # TICKERS
    # ------------------------------------------------------------

    if not symbols:

        print(
            "⚠️ Pair intersection empty."
        )

        print(
            "Using ticker markets."
        )

        symbols = ticker_symbols

    # ------------------------------------------------------------
    # FALLBACK:
    # PAIRS
    # ------------------------------------------------------------

    if not symbols:

        print(
            "⚠️ Tickers empty."
        )

        print(
            "Using pair markets."
        )

        symbols = pair_symbols

    # ------------------------------------------------------------
    # FINAL
    # ------------------------------------------------------------

    if not symbols:

        print(
            "❌ ZERO USDT MARKETS"
        )

        return [], tickers

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

    print()
    print(
        "✅ FINAL MARKETS:",
        len(symbols)
    )

    return symbols, tickers


# ================================================================
# SCAN
# ================================================================

def scan():

    print()
    print("=" * 80)

    print(
        "🚀 FULL MARKET SCAN"
    )

    print(
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
    # DISCOVERY
    # ------------------------------------------------------------

    symbols, tickers = discover_markets()

    # ------------------------------------------------------------
    # MARKET ERROR
    # ------------------------------------------------------------

    if not symbols:

        send_telegram(
            "⚠️ OK-EX MARKET ERROR\n\n"
            "No USDT markets were returned "
            "by the API.\n\n"
            f"Ticker markets: "
            f"{stats['ticker_markets']}\n"
            f"Pair markets: "
            f"{stats['pair_markets']}\n"
            f"Time: {now_text()}"
        )

        return

    stats[
        "markets"
    ] = len(symbols)

    print()
    print(
        "📊 Markets to scan:",
        len(symbols)
    )

    # ------------------------------------------------------------
    # ANALYSIS
    # ------------------------------------------------------------

    candidates = []

    for index, symbol in enumerate(
        symbols
    ):

        print()
        print(
            f"[{index + 1}/"
            f"{len(symbols)}] "
            f"{display_symbol(symbol)}"
        )

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            print(
                "⚠️ Ticker missing"
            )

            continue

        try:

            signal = analyze_market(
                symbol,
                ticker
            )

            if signal:

                print(
                    "🎯 CANDIDATE:",
                    display_symbol(
                        symbol
                    ),
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

            else:

                print(
                    "WAIT"
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

        # Small delay to reduce API pressure
        time.sleep(
            0.10
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

    print()
    print(
        "🎯 TOTAL CANDIDATES:",
        len(candidates)
    )

    # ------------------------------------------------------------
    # SEND SIGNALS
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
                display_symbol(
                    symbol
                )
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

        if (
            sent
            >= MAX_SIGNALS_PER_SCAN
        ):

            break

    # ------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------

    summary = make_summary()

    print()
    print("=" * 80)

    print(
        summary
    )

    print("=" * 80)

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
        "🐋 OK-EX IRAN "
        "PAPER SIGNAL BOT V4"
    )

    print("=" * 80)

    print()
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

    print(
        "Minimum score:",
        MIN_SCORE
    )

    print(
        "Strong score:",
        STRONG_SCORE
    )

    print(
        "Candle interval:",
        CANDLE_INTERVAL
    )

    print(
        "Candle limit:",
        CANDLE_LIMIT
    )

    # ------------------------------------------------------------
    # SAFETY CHECK
    # ------------------------------------------------------------

    if not PAPER_MODE:

        print(
            "❌ PAPER_MODE must be True"
        )

        return

    if REAL_ORDERS:

        print(
            "❌ REAL_ORDERS must be False"
        )

        return

    # ------------------------------------------------------------
    # TELEGRAM CHECK
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
    # STARTUP
    # ------------------------------------------------------------

    send_startup()

    # ------------------------------------------------------------
    # CANDLE TEST
    # ------------------------------------------------------------

    if not candle_test():

        print()
        print(
            "🛑 BOT STOPPED"
        )

        print(
            "Candle API test failed."
        )

        return

    # ------------------------------------------------------------
    # FULL SCAN
    # ------------------------------------------------------------

    scan()

    # ------------------------------------------------------------
    # LOOP
    # ------------------------------------------------------------

    while True:

        try:

            print()
            print(
                "⏳ Next scan in "
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
