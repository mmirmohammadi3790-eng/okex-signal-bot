# ================================================================
# OK-EX IRAN - SMART PAPER SIGNAL BOT
# GITHUB ACTIONS
# ALL USDT MARKETS
# LONG / SHORT / WAIT
# ENTRY / SL / TP1 / TP2 / TP3
# RSI / EMA / MOMENTUM / VOLUME / PRICE ACTION
# WHALE PROXY
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

# ------------------------------------------------
# SCAN
# ------------------------------------------------

SCAN_INTERVAL = 300
COOLDOWN = 1800

MAX_MARKETS = 9999
MAX_SIGNALS_PER_SCAN = 5

# ------------------------------------------------
# SIGNAL FILTER
# ------------------------------------------------

MIN_SCORE = 50
STRONG_SCORE = 70

# ------------------------------------------------
# PAPER MODE
# ------------------------------------------------

PAPER_MODE = True
REAL_ORDERS = False

REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

session = requests.Session()
session.headers.update(HEADERS)

last_signal_time = {}

stats = {
    "scans": 0,
    "signals": 0,
    "errors": 0,
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
        print("ERROR: BOT TOKEN MISSING")
        return False

    if not CHAT_ID:
        print("ERROR: CHAT ID MISSING")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
    }

    try:

        r = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        print(
            "TELEGRAM STATUS:",
            r.status_code
        )

        if r.ok:
            return True

        print(
            "TELEGRAM ERROR:",
            r.text[:500]
        )

        return False

    except Exception as e:

        print(
            "TELEGRAM ERROR:",
            repr(e)
        )

        return False


# ================================================================
# API
# ================================================================

def api_get(
    path,
    params=None,
    quiet=False
):

    url = OKEX_BASE + path

    if not quiet:

        print()
        print("=" * 70)
        print("GET:", url)
        print("PARAMS:", params)

    try:

        r = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if not quiet:

            print(
                "HTTP STATUS:",
                r.status_code
            )

            print(
                "FINAL URL:",
                r.url
            )

            print(
                "CONTENT TYPE:",
                r.headers.get(
                    "content-type"
                )
            )

            print(
                "RAW RESPONSE:"
            )

            print(
                r.text[:1000]
            )

        if not r.ok:

            stats["errors"] += 1

            return None

        try:

            return r.json()

        except Exception as e:

            print(
                "JSON ERROR:",
                repr(e)
            )

            stats["errors"] += 1

            return None

    except Exception as e:

        print(
            "API ERROR:",
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

            for subkey in keys:

                sub = value.get(
                    subkey
                )

                if isinstance(
                    sub,
                    list
                ):
                    return sub

    return []


# ================================================================
# SYMBOL
# ================================================================

def normalize_symbol(symbol):

    if symbol is None:
        return None

    s = str(
        symbol
    ).upper().strip()

    s = s.replace(
        "_",
        "-"
    )

    s = s.replace(
        "/",
        "-"
    )

    if s.endswith(
        "-USDT"
    ):
        return s

    if s.endswith(
        "USDT"
    ):

        base = s[:-4]

        if base:
            return (
                base
                + "-USDT"
            )

    return s


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    print()
    print(
        "REQUESTING TICKERS..."
    )

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_list(
        data
    )

    print(
        "TICKER ROW COUNT:",
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
        except:
            volume = 0.0

        try:
            quote_volume = float(
                quote_volume
            )
        except:
            quote_volume = 0.0

        try:
            change = float(
                change
            )
        except:
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
        "REQUESTING PAIRS..."
    )

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    rows = extract_list(
        data
    )

    print(
        "PAIRS ROW COUNT:",
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
        "PAIRS USDT COUNT:",
        len(symbols)
    )

    return symbols


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
        params,
        quiet=True
    )

    rows = extract_list(
        data
    )

    candles = []

    for row in rows:

        # --------------------------------------------------------
        # DICT FORMAT
        # --------------------------------------------------------

        if isinstance(
            row,
            dict
        ):

            close = (
                row.get("close")
                or row.get("c")
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

            try:

                candles.append({
                    "close": float(
                        close
                    ),
                    "high": float(
                        high
                    ),
                    "low": float(
                        low
                    ),
                    "volume": float(
                        volume
                    ),
                })

            except:
                pass

        # --------------------------------------------------------
        # LIST FORMAT
        # --------------------------------------------------------

        elif isinstance(
            row,
            list
        ):

            try:

                if len(row) >= 6:

                    candles.append({
                        "close": float(
                            row[4]
                        ),
                        "high": float(
                            row[2]
                        ),
                        "low": float(
                            row[3]
                        ),
                        "volume": float(
                            row[5]
                        ),
                    })

            except:
                pass

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
        / (
            period
            + 1
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
        return 100

    rs = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (
            100
            / (
                1 + rs
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
        "1h",
        100
    )

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

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    r = rsi(
        closes,
        14
    )

    if (
        ema20 is None
        or ema50 is None
        or r is None
    ):
        return None

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # ============================================================
    # EMA TREND
    # ============================================================

    if price > ema20:

        long_score += 15

        long_reasons.append(
            "Price above EMA20"
        )

    else:

        short_score += 15

        short_reasons.append(
            "Price below EMA20"
        )

    if ema20 > ema50:

        long_score += 15

        long_reasons.append(
            "EMA20 above EMA50"
        )

    else:

        short_score += 15

        short_reasons.append(
            "EMA20 below EMA50"
        )

    # ============================================================
    # RSI
    # ============================================================

    if 50 <= r <= 70:

        long_score += 15

        long_reasons.append(
            "RSI bullish"
        )

    elif 30 <= r <= 50:

        short_score += 15

        short_reasons.append(
            "RSI bearish"
        )

    elif r < 30:

        long_score += 10

        long_reasons.append(
            "RSI oversold"
        )

    elif r > 70:

        short_score += 10

        short_reasons.append(
            "RSI overbought"
        )

    # ============================================================
    # MOMENTUM
    # ============================================================

    momentum = 0

    if len(closes) >= 6:

        momentum = (
            (
                closes[-1]
                / closes[-6]
            )
            - 1
        ) * 100

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

        avg_volume = (
            sum(
                volumes[-21:-1]
            )
            / 20
        )

        current_volume = volumes[-1]

        if avg_volume > 0:

            volume_ratio = (
                current_volume
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
    # PRICE ACTION
    # ============================================================

    if len(candles) >= 3:

        previous_high = highs[-2]
        previous_low = lows[-2]

        current_close = closes[-1]

        if current_close > previous_high:

            long_score += 10

            long_reasons.append(
                "Bullish breakout"
            )

        elif current_close < previous_low:

            short_score += 10

            short_reasons.append(
                "Bearish breakdown"
            )

    # ============================================================
    # SHORT-TERM PRICE DIRECTION
    # ============================================================

    if len(closes) >= 10:

        recent_change = (
            (
                closes[-1]
                / closes[-10]
            )
            - 1
        ) * 100

        if recent_change > 0.8:

            long_score += 5

            long_reasons.append(
                "Short-term strength"
            )

        elif recent_change < -0.8:

            short_score += 5

            short_reasons.append(
                "Short-term weakness"
            )

    # ============================================================
    # WHALE PROXY
    # ============================================================

    quote_volume = ticker.get(
        "quote_volume",
        0
    )

    if quote_volume >= 50000:

        if long_score >= short_score:

            long_score += 5

            long_reasons.append(
                "Liquidity/whale proxy"
            )

        else:

            short_score += 5

            short_reasons.append(
                "Liquidity/whale proxy"
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
    # AVOID WEAK CONFLICTS
    # ============================================================

    score_difference = abs(
        long_score
        - short_score
    )

    if score_difference < 10:

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
            + risk * 1.0
        )

        tp2 = (
            entry
            + risk * 2.0
        )

        tp3 = (
            entry
            + risk * 3.0
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
            - risk * 1.0
        )

        tp2 = (
            entry
            - risk * 2.0
        )

        tp3 = (
            entry
            - risk * 3.0
        )

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": r,
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

    message = (
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

        f"Volume Ratio: "
        f"x{signal['volume_ratio']:.2f}\n"

        f"24h Change: "
        f"{signal['change']:.2f}%\n\n"

        f"🐋 Whale Proxy: ACTIVE\n"

        f"🧠 Reasons:\n"
        f"{reasons}\n\n"

        f"💵 PAPER SIGNAL ONLY\n"
        f"🔴 REAL ORDERS: OFF\n\n"

        f"⏰ {now()}"
    )

    return message


# ================================================================
# START MESSAGE
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

        f"⏰ {now()}"
    )

    send_telegram(
        message
    )


# ================================================================
# SCAN
# ================================================================

def scan_market():

    stats["scans"] += 1

    print()
    print("#" * 70)
    print(
        "SCAN START:",
        now()
    )
    print("#" * 70)

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

    if pairs and tickers:

        symbols = pairs.intersection(
            set(
                tickers.keys()
            )
        )

        print(
            "PAIR/TICKER INTERSECTION:",
            len(symbols)
        )

    # ------------------------------------------------------------
    # FALLBACK
    # ------------------------------------------------------------

    if not symbols and tickers:

        print(
            "USING TICKER FALLBACK"
        )

        symbols = set(
            tickers.keys()
        )

    if not symbols and pairs:

        print(
            "USING PAIRS FALLBACK"
        )

        symbols = set(
            pairs
        )

    # ------------------------------------------------------------
    # ERROR
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
    # SORT BY LIQUIDITY
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

    symbols = symbols[
        :MAX_MARKETS
    ]

    print(
        "MARKETS:",
        len(symbols)
    )

    candidates = []

    # ============================================================
    # ANALYSIS
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
                    ">>> CANDIDATE:",
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

            stats["errors"] += 1

        time.sleep(
            0.10
        )

    # ============================================================
    # SORT
    # ============================================================

    candidates.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    print()
    print(
        "CANDIDATES:",
        len(candidates)
    )

    # ============================================================
    # SEND
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

        if (
            sent
            >= MAX_SIGNALS_PER_SCAN
        ):

            break

    # ============================================================
    # SUMMARY
    # ============================================================

    summary = (
        "🔎 SCAN COMPLETE\n\n"

        f"🪙 Markets checked: "
        f"{len(symbols)}\n"

        f"📊 Signals found: "
        f"{len(candidates)}\n"

        f"📨 Signals sent: "
        f"{sent}\n\n"

        f"🎯 Minimum score: "
        f"{MIN_SCORE}/100\n"

        f"🔥 Strong score: "
        f"{STRONG_SCORE}/100\n\n"

        f"🟢 Paper Mode: ON\n"
        f"🔴 Real Orders: OFF\n\n"

        f"⏰ {now()}"
    )

    print(
        summary
    )

    # ------------------------------------------------------------
    # WAIT
    # ------------------------------------------------------------

    if sent == 0:

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
        "OK-EX IRAN SMART PAPER BOT"
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
            "BOT TOKEN MISSING"
        )
        return

    if not CHAT_ID:
        print(
            "CHAT ID MISSING"
        )
        return

    # ------------------------------------------------------------
    # START
    # ------------------------------------------------------------

    startup_message()

    # ------------------------------------------------------------
    # FIRST SCAN
    # ------------------------------------------------------------

    scan_market()

    last_scan = time.time()

    # ============================================================
    # LOOP
    # ============================================================

    while True:

        try:

            time.sleep(
                10
            )

            if (
                time.time()
                - last_scan
                >= SCAN_INTERVAL
            ):

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
# RUN
# ================================================================

if __name__ == "__main__":

    main()
