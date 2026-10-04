# ================================================================
# OK-EX IRAN - SMART PAPER SIGNAL BOT V2
# GITHUB ACTIONS
# ALL USDT MARKETS
# LONG / SHORT / WAIT
# ENTRY / SL / TP1 / TP2 / TP3
# RSI / EMA / MOMENTUM / VOLUME / PRICE ACTION
# WHALE PROXY
# CANDLE DIAGNOSTICS
# PAPER ONLY - NO REAL ORDERS
# ================================================================

import os
import time
import requests
from datetime import datetime


# ================================================================
# CONFIG
# ================================================================

OKEX_BASE = "https://sapi.ok-ex.io"

BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")
    or ""
).strip()

CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
    or ""
).strip()


# ================================================================
# SCAN SETTINGS
# ================================================================

SCAN_INTERVAL = 300
COOLDOWN = 1800

MAX_MARKETS = 9999
MAX_SIGNALS_PER_SCAN = 5

MIN_SCORE = 50
STRONG_SCORE = 70

REQUEST_TIMEOUT = 20

PAPER_MODE = True
REAL_ORDERS = False


# ================================================================
# HTTP
# ================================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

session = requests.Session()
session.headers.update(HEADERS)


# ================================================================
# GLOBALS
# ================================================================

last_signal_time = {}

stats = {
    "scans": 0,
    "signals": 0,
    "errors": 0,
    "candle_ok": 0,
    "candle_failed": 0,
    "candle_rows": 0,
    "analysis_ok": 0,
    "candidates": 0,
}


# ================================================================
# TIME
# ================================================================

def now():
    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ================================================================
# TELEGRAM
# ================================================================

def send_telegram(text):

    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN MISSING")
        return False

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID MISSING")
        return False

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
    }

    try:

        response = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        print(
            "TELEGRAM:",
            response.status_code
        )

        if response.ok:
            return True

        print(
            "TELEGRAM ERROR:",
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "TELEGRAM EXCEPTION:",
            repr(e)
        )

        return False


# ================================================================
# API GET
# ================================================================

def api_get(
    path,
    params=None,
    quiet=False
):

    url = OKEX_BASE + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if not quiet:

            print()
            print("=" * 70)
            print("GET:", url)
            print("PARAMS:", params)
            print(
                "STATUS:",
                response.status_code
            )

            print(
                "URL:",
                response.url
            )

            print(
                "CONTENT TYPE:",
                response.headers.get(
                    "content-type"
                )
            )

            print(
                "RESPONSE:",
                response.text[:1000]
            )

        if not response.ok:

            stats["errors"] += 1

            return None

        try:

            return response.json()

        except Exception as e:

            print(
                "JSON ERROR:",
                repr(e)
            )

            stats["errors"] += 1

            return None

    except Exception as e:

        print(
            "REQUEST ERROR:",
            path,
            repr(e)
        )

        stats["errors"] += 1

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

    possible_keys = [
        "res",
        "data",
        "result",
        "rows",
        "list",
        "items",
        "records",
    ]

    for key in possible_keys:

        value = data.get(key)

        if isinstance(
            value,
            list
        ):
            return value

        if isinstance(
            value,
            dict
        ):

            for subkey in possible_keys:

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

def normalize_symbol(symbol):

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
        "REQUESTING OK-EX TICKERS..."
    )

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_list(
        data
    )

    print(
        "RAW TICKER ROWS:",
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
            volume = float(volume)
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

        result[symbol] = {
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "quote_volume": quote_volume,
            "change": change,
        }

    print(
        "VALID USDT TICKERS:",
        len(result)
    )

    if result:

        print(
            "TICKER SAMPLE:",
            list(
                result.keys()
            )[:10]
        )

    return result


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    print()
    print(
        "REQUESTING OK-EX PAIRS..."
    )

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    rows = extract_list(
        data
    )

    print(
        "RAW PAIR ROWS:",
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

            if (
                symbol
                and symbol.endswith(
                    "-USDT"
                )
            ):
                symbols.add(
                    symbol
                )

            continue

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
        "VALID USDT PAIRS:",
        len(symbols)
    )

    return symbols


# ================================================================
# CANDLE VALUE HELPERS
# ================================================================

def safe_float(value):

    try:

        if value is None:
            return None

        return float(value)

    except Exception:

        return None


# ================================================================
# PARSE ONE CANDLE
# ================================================================

def parse_candle(row):

    # ------------------------------------------------------------
    # DICT
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
    # LIST
    # ------------------------------------------------------------

    if isinstance(
        row,
        list
    ):

        if len(row) < 6:
            return None

        # Standard OK-EX style assumption:
        # [time, open, high, low, close, volume, ...]

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
# CANDLES
# ================================================================

def get_candles(
    symbol,
    interval="1h",
    limit=100
):

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    data = api_get(
        "/api/v1/spot/public/candles",
        params=params,
        quiet=True
    )

    rows = extract_list(
        data
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

    # ------------------------------------------------------------
    # DIAGNOSTIC
    # ------------------------------------------------------------

    if candles:

        stats[
            "candle_ok"
        ] += 1

        stats[
            "candle_rows"
        ] += len(candles)

    else:

        stats[
            "candle_failed"
        ] += 1

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
        2.0
        / (
            period
            + 1.0
        )
    )

    result = (
        sum(
            values[:period]
        )
        / period
    )

    for price in values[period:]:

        result = (
            (
                price
                - result
            )
            * multiplier
        ) + result

    return result


# ================================================================
# RSI
# ================================================================

def rsi(
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

        if change >= 0:

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
# ANALYZE MARKET
# ================================================================

def analyze_market(
    symbol,
    ticker
):

    price = ticker[
        "price"
    ]

    candles = get_candles(
        symbol,
        interval="1h",
        limit=100
    )

    # ------------------------------------------------------------
    # NOT ENOUGH CANDLES
    # ------------------------------------------------------------

    if len(candles) < 30:

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

    # ------------------------------------------------------------
    # INDICATORS
    # ------------------------------------------------------------

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

    if (
        ema20 is None
        or ema50 is None
        or current_rsi is None
    ):

        return None

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # ============================================================
    # TREND - PRICE / EMA20
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
    # TREND - EMA20 / EMA50
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
        current_rsi >= 50
        and current_rsi <= 70
    ):

        long_score += 15

        long_reasons.append(
            "Bullish RSI"
        )

    elif (
        current_rsi >= 30
        and current_rsi < 50
    ):

        short_score += 15

        short_reasons.append(
            "Bearish RSI"
        )

    elif current_rsi < 30:

        long_score += 10

        long_reasons.append(
            "RSI Oversold"
        )

    elif current_rsi > 70:

        short_score += 10

        short_reasons.append(
            "RSI Overbought"
        )

    # ============================================================
    # MOMENTUM
    # ============================================================

    momentum = 0.0

    if len(closes) >= 6:

        previous_price = closes[-6]

        if previous_price > 0:

            momentum = (
                (
                    closes[-1]
                    / previous_price
                )
                - 1.0
            ) * 100.0

            if momentum > 0.4:

                long_score += 15

                long_reasons.append(
                    f"Momentum +{momentum:.2f}%"
                )

            elif momentum < -0.4:

                short_score += 15

                short_reasons.append(
                    f"Momentum {momentum:.2f}%"
                )

    # ============================================================
    # VOLUME
    # ============================================================

    volume_ratio = 1.0

    if len(volumes) >= 21:

        previous_volumes = (
            volumes[-21:-1]
        )

        avg_volume = (
            sum(
                previous_volumes
            )
            / len(
                previous_volumes
            )
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
    # SHORT TERM TREND
    # ============================================================

    if len(closes) >= 10:

        old_price = closes[-10]

        if old_price > 0:

            short_term_change = (
                (
                    closes[-1]
                    / old_price
                )
                - 1.0
            ) * 100.0

            if short_term_change > 0.8:

                long_score += 5

                long_reasons.append(
                    "Short-term strength"
                )

            elif short_term_change < -0.8:

                short_score += 5

                short_reasons.append(
                    "Short-term weakness"
                )

    # ============================================================
    # WHALE / LIQUIDITY PROXY
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
    # SCORE FILTER
    # ============================================================

    if score < MIN_SCORE:

        return None

    # ============================================================
    # DIRECTION CONFIRMATION
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

        sl = entry * 0.985

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

        sl = entry * 1.015

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
        "rsi": current_rsi,
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

def signal_message(
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

        strength = "⚡ FILTERED"

    reasons = ", ".join(
        signal[
            "reasons"
        ][:6]
    )

    return (
        f"{emoji} {strength} "
        f"{signal['direction']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🪙 {signal['symbol']}\n"
        f"📊 Score: "
        f"{signal['score']}/100\n\n"

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

        f"Volume: "
        f"x{signal['volume_ratio']:.2f}\n"

        f"24h Change: "
        f"{signal['change']:.2f}%\n\n"

        f"🐋 Whale Proxy: ACTIVE\n\n"

        f"🧠 Reasons:\n"
        f"{reasons}\n\n"

        f"💵 PAPER SIGNAL ONLY\n"
        f"🔴 REAL ORDERS: OFF\n\n"

        f"⏰ {now()}"
    )


# ================================================================
# STARTUP
# ================================================================

def startup_message():

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

        "🧪 Candle diagnostics: ON\n\n"

        f"⏰ {now()}"
    )

    send_telegram(
        message
    )


# ================================================================
# DIAGNOSTIC MESSAGE
# ================================================================

def diagnostic_message(
    market_count,
    candidates_count,
    sent_count
):

    avg_rows = 0

    if stats["candle_ok"] > 0:

        avg_rows = (
            stats["candle_rows"]
            / stats["candle_ok"]
        )

    return (
        "🔎 SCAN COMPLETE\n\n"

        f"📊 Markets: "
        f"{market_count}\n"

        f"🕯 Candle OK: "
        f"{stats['candle_ok']}\n"

        f"❌ Candle Failed: "
        f"{stats['candle_failed']}\n"

        f"📚 Total candle rows: "
        f"{stats['candle_rows']}\n"

        f"📐 Avg candles/OK market: "
        f"{avg_rows:.1f}\n\n"

        f"🧠 Analysis Passed: "
        f"{stats['analysis_ok']}\n"

        f"🎯 Candidates: "
        f"{candidates_count}\n"

        f"📨 Signals sent: "
        f"{sent_count}\n\n"

        f"🎯 Minimum Score: "
        f"{MIN_SCORE}/100\n"

        f"🔥 Strong Score: "
        f"{STRONG_SCORE}/100\n\n"

        "🟢 Paper Mode: ON\n"
        "🔴 Real Orders: OFF\n\n"

        f"⏰ {now()}"
    )


# ================================================================
# SCAN MARKET
# ================================================================

def scan_market():

    stats["scans"] += 1

    # ------------------------------------------------------------
    # RESET CANDLE STATS
    # ------------------------------------------------------------

    stats["candle_ok"] = 0
    stats["candle_failed"] = 0
    stats["candle_rows"] = 0
    stats["analysis_ok"] = 0

    print()
    print("=" * 70)
    print(
        "SCAN START:",
        now()
    )
    print("=" * 70)

    # ------------------------------------------------------------
    # TICKERS
    # ------------------------------------------------------------

    tickers = get_tickers()

    # ------------------------------------------------------------
    # PAIRS
    # ------------------------------------------------------------

    pairs = get_pairs()

    symbols = set()

    # ------------------------------------------------------------
    # INTERSECTION
    # ------------------------------------------------------------

    if (
        tickers
        and pairs
    ):

        symbols = (
            set(
                tickers.keys()
            )
            .intersection(
                pairs
            )
        )

        print(
            "PAIR/TICKER INTERSECTION:",
            len(symbols)
        )

    # ------------------------------------------------------------
    # FALLBACK
    # ------------------------------------------------------------

    if not symbols:

        if tickers:

            print(
                "USING TICKER FALLBACK"
            )

            symbols = set(
                tickers.keys()
            )

        elif pairs:

            print(
                "USING PAIRS FALLBACK"
            )

            symbols = set(
                pairs
            )

    # ------------------------------------------------------------
    # NO MARKETS
    # ------------------------------------------------------------

    if not symbols:

        print(
            "NO USDT MARKETS"
        )

        send_telegram(
            "⚠️ OK-EX MARKET ERROR\n\n"
            "No USDT markets returned."
        )

        return

    # ------------------------------------------------------------
    # LIQUIDITY SORT
    # ------------------------------------------------------------

    symbols = list(
        symbols
    )

    symbols.sort(
        key=lambda s:
        tickers.get(
            s,
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

    print(
        "MARKETS TO CHECK:",
        len(symbols)
    )

    candidates = []

    # ============================================================
    # ANALYZE ALL MARKETS
    # ============================================================

    for index, symbol in enumerate(
        symbols
    ):

        print(
            f"[{index + 1}/"
            f"{len(symbols)}] "
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
                    ">>> SIGNAL CANDIDATE:",
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

            print(
                "ANALYSIS ERROR:",
                symbol,
                repr(e)
            )

            stats[
                "errors"
            ] += 1

        time.sleep(
            0.10
        )

    # ============================================================
    # SORT CANDIDATES
    # ============================================================

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
        "CANDIDATES:",
        len(candidates)
    )

    # ============================================================
    # SEND SIGNALS
    # ============================================================

    sent = 0

    for signal in candidates:

        symbol = signal[
            "symbol"
        ]

        previous = (
            last_signal_time.get(
                symbol,
                0
            )
        )

        # --------------------------------------------------------
        # COOLDOWN
        # --------------------------------------------------------

        if (
            time.time()
            - previous
            < COOLDOWN
        ):

            print(
                "COOLDOWN:",
                symbol
            )

            continue

        # --------------------------------------------------------
        # SEND
        # --------------------------------------------------------

        message = signal_message(
            signal
        )

        if send_telegram(
            message
        ):

            last_signal_time[
                symbol
            ] = time.time()

            stats[
                "signals"
            ] += 1

            sent += 1

        # --------------------------------------------------------
        # MAX SIGNALS
        # --------------------------------------------------------

        if (
            sent
            >= MAX_SIGNALS_PER_SCAN
        ):

            break

    # ============================================================
    # SUMMARY
    # ============================================================

    summary = diagnostic_message(
        len(symbols),
        len(candidates),
        sent
    )

    print()
    print(summary)

    # ------------------------------------------------------------
    # ALWAYS SEND DIAGNOSTIC
    # ------------------------------------------------------------

    send_telegram(
        summary
    )


# ================================================================
# MAIN
# ================================================================

def main():

    print()
    print("=" * 70)
    print(
        "OK-EX IRAN SMART PAPER BOT V2"
    )
    print("=" * 70)

    print(
        "BOT TOKEN:",
        "SET"
        if BOT_TOKEN
        else "MISSING"
    )

    print(
        "CHAT ID:",
        "SET"
        if CHAT_ID
        else "MISSING"
    )

    print(
        "MIN SCORE:",
        MIN_SCORE
    )

    print(
        "STRONG SCORE:",
        STRONG_SCORE
    )

    print(
        "MAX SIGNALS:",
        MAX_SIGNALS_PER_SCAN
    )

    print(
        "SCAN INTERVAL:",
        SCAN_INTERVAL
    )

    print(
        "PAPER MODE:",
        PAPER_MODE
    )

    print(
        "REAL ORDERS:",
        REAL_ORDERS
    )

    # ------------------------------------------------------------
    # CONFIG CHECK
    # ------------------------------------------------------------

    if not BOT_TOKEN:

        print(
            "ERROR: BOT TOKEN MISSING"
        )

        return

    if not CHAT_ID:

        print(
            "ERROR: CHAT ID MISSING"
        )

        return

    # ------------------------------------------------------------
    # TELEGRAM START
    # ------------------------------------------------------------

    startup_message()

    # ------------------------------------------------------------
    # FIRST SCAN
    # ------------------------------------------------------------

    scan_market()

    last_scan = time.time()

    # ============================================================
    # CONTINUOUS LOOP
    # ============================================================

    while True:

        try:

            time.sleep(
                10
            )

            elapsed = (
                time.time()
                - last_scan
            )

            if elapsed >= SCAN_INTERVAL:

                last_scan = time.time()

                scan_market()

        except KeyboardInterrupt:

            print(
                "BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                repr(e)
            )

            stats[
                "errors"
            ] += 1

            time.sleep(
                30
            )


# ================================================================
# START
# ================================================================

if __name__ == "__main__":

    main()
