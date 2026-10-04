# ================================================================
# OK-EX IRAN - PAPER FUTURES SIGNAL BOT
# GITHUB ACTIONS
# ALL USDT MARKETS
# MORE SIGNALS / STILL FILTERED
# LONG / SHORT / WAIT
# ENTRY / SL / TP1 / TP2 / TP3
# RSI / EMA / MOMENTUM / VOLUME / PRICE ACTION / WHALE PROXY
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
# SIGNAL SETTINGS
# ------------------------------------------------

SCAN_INTERVAL = 300

# سیگنال‌ها کمی بیشتر، ولی همچنان فیلترشده
MIN_SCORE = 55
STRONG_SCORE = 75

# حداکثر سیگنال در هر اسکن
MAX_SIGNALS_PER_SCAN = 5

# جلوگیری از تکرار یک ارز
COOLDOWN = 1800

# تمام بازارهای USDT
MAX_MARKETS = 9999

# ------------------------------------------------
# SAFETY
# ------------------------------------------------

PAPER_MODE = True
REAL_ORDERS = False

REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 OK-EX-Iran-Paper-Bot",
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
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ================================================================
# TELEGRAM
# ================================================================

def send_telegram(text):

    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN IS EMPTY")
        return False

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID IS EMPTY")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

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

        print("TELEGRAM STATUS:", r.status_code)

        if r.ok:
            return True

        print("TELEGRAM ERROR:", r.text[:500])
        return False

    except Exception as e:

        print(
            "TELEGRAM EXCEPTION:",
            repr(e)
        )

        return False


# ================================================================
# OK-EX API
# ================================================================

def api_get(path, params=None):

    url = OKEX_BASE + path

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
            r.headers.get("content-type")
        )

        raw = r.text

        print("RAW RESPONSE:")
        print(raw[:1000])

        if not r.ok:

            stats["errors"] += 1

            return None

        try:

            data = r.json()

        except Exception as e:

            print(
                "JSON ERROR:",
                repr(e)
            )

            stats["errors"] += 1

            return None

        print(
            "JSON TYPE:",
            type(data).__name__
        )

        if isinstance(data, dict):

            print(
                "JSON KEYS:",
                list(data.keys())
            )

        return data

    except Exception as e:

        print(
            "API ERROR:",
            repr(e)
        )

        stats["errors"] += 1

        return None


# ================================================================
# EXTRACT API LIST
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

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            for subkey in possible_keys:

                sub = value.get(subkey)

                if isinstance(sub, list):
                    return sub

    return []


# ================================================================
# SYMBOL NORMALIZER
# ================================================================

def normalize_symbol(symbol):

    if symbol is None:
        return None

    s = str(symbol).upper().strip()

    s = s.replace("_", "-")
    s = s.replace("/", "-")

    if s.endswith("-USDT"):
        return s

    if s.endswith("USDT"):

        base = s[:-4]

        if base:
            return base + "-USDT"

    return s


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    print()
    print("REQUESTING TICKERS...")

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_list(data)

    print(
        "TICKER ROW COUNT:",
        len(rows)
    )

    result = {}

    for row in rows:

        if not isinstance(row, dict):
            continue

        symbol = (
            row.get("symbol")
            or row.get("instId")
            or row.get("market")
            or row.get("pair")
            or row.get("code")
        )

        symbol = normalize_symbol(symbol)

        if not symbol:
            continue

        if not symbol.endswith("-USDT"):
            continue

        price = (
            row.get("last")
            or row.get("lastPrice")
            or row.get("close")
            or row.get("price")
        )

        try:

            price = float(price)

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
            quote_volume = float(quote_volume)
        except Exception:
            quote_volume = 0.0

        try:
            change = float(change)
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
            list(result.keys())[:10]
        )

    return result


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    print()
    print("REQUESTING PAIRS...")

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    rows = extract_list(data)

    print(
        "PAIRS ROW COUNT:",
        len(rows)
    )

    symbols = set()

    for row in rows:

        if isinstance(row, str):

            symbol = normalize_symbol(row)

            if (
                symbol
                and symbol.endswith("-USDT")
            ):
                symbols.add(symbol)

            continue

        if not isinstance(row, dict):
            continue

        symbol = (
            row.get("symbol")
            or row.get("instId")
            or row.get("market")
            or row.get("pair")
            or row.get("code")
        )

        symbol = normalize_symbol(symbol)

        if (
            symbol
            and symbol.endswith("-USDT")
        ):
            symbols.add(symbol)

    print(
        "PAIRS USDT COUNT:",
        len(symbols)
    )

    if symbols:

        print(
            "PAIR SAMPLE:",
            list(symbols)[:10]
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
        params
    )

    rows = extract_list(data)

    candles = []

    for row in rows:

        if isinstance(row, dict):

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
                    "close": float(close),
                    "high": float(high),
                    "low": float(low),
                    "volume": float(volume),
                })

            except Exception:

                pass

        elif isinstance(row, list):

            try:

                if len(row) >= 6:

                    candles.append({
                        "close": float(row[4]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "volume": float(row[5]),
                    })

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

    result = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        result = (
            (price - result)
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

    if len(values) < period + 1:
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

    rs = avg_gain / avg_loss

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# ================================================================
# MARKET ANALYSIS
# ================================================================

def analyze_market(
    symbol,
    ticker
):

    price = ticker["price"]

    candles = get_candles(
        symbol,
        "1h",
        100
    )

    if len(candles) < 30:

        print(
            symbol,
            "INSUFFICIENT CANDLES:",
            len(candles)
        )

        return None

    closes = [
        x["close"]
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
    # EMA20
    # ============================================================

    if price > ema20:

        long_score += 15

        long_reasons.append(
            "Price>EMA20"
        )

    else:

        short_score += 15

        short_reasons.append(
            "Price<EMA20"
        )

    # ============================================================
    # EMA50
    # ============================================================

    if ema20 > ema50:

        long_score += 15

        long_reasons.append(
            "EMA20>EMA50"
        )

    else:

        short_score += 15

        short_reasons.append(
            "EMA20<EMA50"
        )

    # ============================================================
    # RSI
    # ============================================================

    if 52 <= r <= 68:

        long_score += 15

        long_reasons.append(
            "RSI bullish"
        )

    elif 32 <= r <= 48:

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

        if momentum > 0.7:

            long_score += 15

            long_reasons.append(
                f"Momentum +{momentum:.2f}%"
            )

        elif momentum < -0.7:

            short_score += 15

            short_reasons.append(
                f"Momentum {momentum:.2f}%"
            )

    # ============================================================
    # VOLUME
    # ============================================================

    if len(volumes) >= 21:

        avg_volume = (
            sum(volumes[-21:-1])
            / 20
        )

        current_volume = volumes[-1]

        if avg_volume > 0:

            volume_ratio = (
                current_volume
                / avg_volume
            )

            if volume_ratio >= 1.3:

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

        previous = candles[-2]
        current = candles[-1]

        if (
            current["close"]
            > previous["high"]
        ):

            long_score += 10

            long_reasons.append(
                "Breakout"
            )

        elif (
            current["close"]
            < previous["low"]
        ):

            short_score += 10

            short_reasons.append(
                "Breakdown"
            )

    # ============================================================
    # WHALE PROXY
    # ============================================================

    quote_volume = ticker.get(
        "quote_volume",
        0
    )

    whale_bonus = 0

    if quote_volume >= 50000:

        whale_bonus = 5

    long_score = min(
        100,
        long_score + whale_bonus
    )

    short_score = min(
        100,
        short_score + whale_bonus
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
    # FINAL FILTER
    # ============================================================

    if score < MIN_SCORE:

        return None

    # ============================================================
    # ENTRY / SL / TP
    # ============================================================

    entry = price

    # ------------------------------------------------------------
    # LONG
    # ------------------------------------------------------------

    if direction == "LONG":

        sl = entry * 0.985

        risk = (
            entry - sl
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

    # ------------------------------------------------------------
    # SHORT
    # ------------------------------------------------------------

    else:

        sl = entry * 1.015

        risk = (
            sl - entry
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
        "change": ticker.get(
            "change",
            0
        ),
        "volume": quote_volume,
        "reasons": reasons,
    }


# ================================================================
# SIGNAL MESSAGE
# ================================================================

def signal_message(signal):

    direction = signal["direction"]

    if direction == "LONG":

        emoji = "🟢"

    else:

        emoji = "🔴"

    if signal["score"] >= STRONG_SCORE:

        strength = "🔥 STRONG"

    else:

        strength = "⚡ FILTERED"

    reasons = ", ".join(
        signal["reasons"][:6]
    )

    message = (
        f"{emoji} {strength} {direction}\n"
        f"━━━━━━━━━━━━━━━━\n"
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
        f"24h Change: {signal['change']:.2f}%\n\n"

        f"🐋 Whale Proxy: ACTIVE\n"
        f"🧠 Reasons: {reasons}\n\n"

        f"💵 PAPER SIGNAL\n"
        f"🔴 REAL ORDERS: OFF\n"
        f"⏰ {now()}"
    )

    return message


# ================================================================
# MARKET ERROR
# ================================================================

def market_error_message():

    return (
        "⚠️ OK-EX MARKET ERROR\n\n"
        "No usable USDT markets were returned.\n\n"
        "The bot is still running.\n"
        "Check GitHub Actions logs.\n\n"
        f"⏰ {now()}"
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
    # GET TICKERS
    # ------------------------------------------------------------

    tickers = get_tickers()

    # ------------------------------------------------------------
    # GET PAIRS
    # ------------------------------------------------------------

    pairs = get_pairs()

    symbols = set()

    # ------------------------------------------------------------
    # INTERSECTION
    # ------------------------------------------------------------

    if pairs and tickers:

        symbols = (
            pairs.intersection(
                set(tickers.keys())
            )
        )

        print(
            "PAIR/TICKER INTERSECTION:",
            len(symbols)
        )

    # ------------------------------------------------------------
    # TICKER FALLBACK
    # ------------------------------------------------------------

    if not symbols and tickers:

        print(
            "USING TICKER-ONLY FALLBACK"
        )

        symbols = set(
            tickers.keys()
        )

    # ------------------------------------------------------------
    # PAIR FALLBACK
    # ------------------------------------------------------------

    if not symbols and pairs:

        print(
            "USING PAIRS-ONLY FALLBACK"
        )

        symbols = set(pairs)

    # ------------------------------------------------------------
    # NO MARKETS
    # ------------------------------------------------------------

    if not symbols:

        print(
            "NO USDT MARKETS FOUND"
        )

        send_telegram(
            market_error_message()
        )

        return

    # ------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------

    symbols = list(symbols)

    # ------------------------------------------------------------
    # SORT BY LIQUIDITY
    # ------------------------------------------------------------

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
        "FINAL MARKET COUNT:",
        len(symbols)
    )

    print(
        "TOP MARKETS:",
        symbols[:20]
    )

    candidates = []

    # ============================================================
    # ANALYZE ALL MARKETS
    # ============================================================

    for index, symbol in enumerate(
        symbols
    ):

        print(
            f"[{index + 1}/{len(symbols)}]"
            f" ANALYZING {symbol}"
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
                    ">>> SIGNAL:",
                    symbol,
                    signal["direction"],
                    signal["score"]
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

        # API protection
        time.sleep(0.12)

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
        "TOTAL CANDIDATES:",
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

    print()
    print(summary)

    # اگر سیگنال نداشتیم، وضعیت را اعلام کن
    if sent == 0:

        send_telegram(
            summary
        )


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
# MAIN
# ================================================================

def main():

    print()
    print("=" * 70)
    print(
        "OK-EX IRAN PAPER FUTURES SIGNAL BOT"
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
        "OK-EX BASE:",
        OKEX_BASE
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
    # CHECK TELEGRAM
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

            time.sleep(10)

            elapsed = (
                time.time()
                - last_scan
            )

            if (
                elapsed
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

            time.sleep(30)


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":

    main()
