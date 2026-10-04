# ================================================================
# OK-EX IRAN - PAPER SIGNAL BOT
# GitHub Actions / Telegram
# ALL USDT MARKETS
# LONG / SHORT / WAIT
# ENTRY / SL / TP1 / TP2 / TP3
# RSI / EMA / MOMENTUM / VOLUME / WHALE PROXY
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

SCAN_INTERVAL = 300
COOLDOWN = 1800

MIN_SCORE = 60
STRONG_SCORE = 80

MAX_SIGNALS_PER_SCAN = 3
MAX_MARKETS = 9999

PAPER_MODE = True
REAL_ORDERS = False

TIMEOUT = 20

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
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ================================================================
# TELEGRAM
# ================================================================

def send_telegram(text):

    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is empty")
        return False

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID is empty")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": text,
    }

    try:
        r = session.post(
            url,
            json=data,
            timeout=TIMEOUT
        )

        print("TELEGRAM STATUS:", r.status_code)

        if r.ok:
            return True

        print("TELEGRAM ERROR:", r.text[:500])
        return False

    except Exception as e:
        print("TELEGRAM EXCEPTION:", repr(e))
        return False


# ================================================================
# API
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
            timeout=TIMEOUT
        )

        print("HTTP STATUS:", r.status_code)
        print("FINAL URL:", r.url)
        print("CONTENT TYPE:", r.headers.get("content-type"))

        raw = r.text

        print("RAW RESPONSE:")
        print(raw[:1000])

        if not r.ok:
            stats["errors"] += 1
            return None

        try:
            data = r.json()
        except Exception as e:
            print("JSON ERROR:", repr(e))
            stats["errors"] += 1
            return None

        print("JSON TYPE:", type(data).__name__)

        if isinstance(data, dict):
            print("JSON KEYS:", list(data.keys()))

        return data

    except Exception as e:

        print("API ERROR:", repr(e))
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

    possible = [
        "res",
        "data",
        "result",
        "rows",
        "list",
        "items",
        "records",
    ]

    for key in possible:

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            for subkey in possible:

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
# GET TICKERS
# ================================================================

def get_tickers():

    print()
    print("REQUESTING TICKERS...")

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    rows = extract_list(data)

    print("TICKER ROW COUNT:", len(rows))

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

    print("VALID USDT TICKERS:", len(result))

    if result:
        print(
            "TICKER SAMPLE:",
            list(result.keys())[:10]
        )

    return result


# ================================================================
# GET PAIRS
# ================================================================

def get_pairs():

    print()
    print("REQUESTING PAIRS...")

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    rows = extract_list(data)

    print("PAIRS ROW COUNT:", len(rows))

    symbols = set()

    for row in rows:

        if isinstance(row, str):

            symbol = normalize_symbol(row)

            if symbol and symbol.endswith("-USDT"):
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

        if symbol and symbol.endswith("-USDT"):
            symbols.add(symbol)

    print("PAIRS USDT COUNT:", len(symbols))

    if symbols:
        print(
            "PAIR SAMPLE:",
            list(symbols)[:10]
        )

    return symbols


# ================================================================
# GET CANDLES
# ================================================================

def get_candles(symbol, interval="1h", limit=100):

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
            )

            try:
                candles.append({
                    "close": float(close),
                    "high": float(high),
                    "low": float(low),
                    "volume": float(volume or 0),
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

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            (price - result) * multiplier
        ) + result

    return result


# ================================================================
# RSI
# ================================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ================================================================
# MARKET ANALYSIS
# ================================================================

def analyze_market(symbol, ticker):

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

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    r = rsi(closes, 14)

    if e20 is None or e50 is None or r is None:
        return None

    score_long = 0
    score_short = 0

    reasons_long = []
    reasons_short = []

    # ------------------------------------------------------------
    # EMA
    # ------------------------------------------------------------

    if price > e20:
        score_long += 15
        reasons_long.append("Price>EMA20")
    else:
        score_short += 15
        reasons_short.append("Price<EMA20")

    if e20 > e50:
        score_long += 15
        reasons_long.append("EMA20>EMA50")
    else:
        score_short += 15
        reasons_short.append("EMA20<EMA50")

    # ------------------------------------------------------------
    # RSI
    # ------------------------------------------------------------

    if 52 <= r <= 68:
        score_long += 15
        reasons_long.append("RSI bullish")
    elif 32 <= r <= 48:
        score_short += 15
        reasons_short.append("RSI bearish")
    elif r < 30:
        score_long += 10
        reasons_long.append("RSI oversold")
    elif r > 70:
        score_short += 10
        reasons_short.append("RSI overbought")

    # ------------------------------------------------------------
    # MOMENTUM
    # ------------------------------------------------------------

    if len(closes) >= 6:

        momentum = (
            (closes[-1] / closes[-6]) - 1
        ) * 100

        if momentum > 1:
            score_long += 15
            reasons_long.append(
                f"Momentum +{momentum:.2f}%"
            )

        elif momentum < -1:
            score_short += 15
            reasons_short.append(
                f"Momentum {momentum:.2f}%"
            )

    # ------------------------------------------------------------
    # VOLUME
    # ------------------------------------------------------------

    if len(volumes) >= 21:

        avg_volume = (
            sum(volumes[-21:-1]) / 20
        )

        current_volume = volumes[-1]

        if avg_volume > 0:

            volume_ratio = (
                current_volume / avg_volume
            )

            if volume_ratio >= 1.5:

                if price > e20:
                    score_long += 15
                    reasons_long.append(
                        f"Volume x{volume_ratio:.1f}"
                    )
                else:
                    score_short += 15
                    reasons_short.append(
                        f"Volume x{volume_ratio:.1f}"
                    )

    # ------------------------------------------------------------
    # PRICE ACTION
    # ------------------------------------------------------------

    if len(candles) >= 3:

        previous = candles[-2]
        current = candles[-1]

        if (
            current["close"] > previous["high"]
        ):
            score_long += 10
            reasons_long.append("Breakout")

        if (
            current["close"] < previous["low"]
        ):
            score_short += 10
            reasons_short.append("Breakdown")

    # ------------------------------------------------------------
    # WHALE PROXY
    # ------------------------------------------------------------

    quote_volume = ticker.get(
        "quote_volume",
        0
    )

    whale_bonus = 0

    if quote_volume >= 50000:
        whale_bonus = 5

    if score_long >= score_short:

        direction = "LONG"
        score = min(
            100,
            score_long + whale_bonus
        )
        reasons = reasons_long

    else:

        direction = "SHORT"
        score = min(
            100,
            score_short + whale_bonus
        )
        reasons = reasons_short

    if score < MIN_SCORE:
        return None

    # ------------------------------------------------------------
    # ENTRY / SL / TP
    # ------------------------------------------------------------

    entry = price

    if direction == "LONG":

        sl = entry * 0.985

        risk = entry - sl

        tp1 = entry + risk * 1.0
        tp2 = entry + risk * 2.0
        tp3 = entry + risk * 3.0

    else:

        sl = entry * 1.015

        risk = sl - entry

        tp1 = entry - risk * 1.0
        tp2 = entry - risk * 2.0
        tp3 = entry - risk * 3.0

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
        "ema20": e20,
        "ema50": e50,
        "change": ticker.get("change", 0),
        "volume": ticker.get(
            "quote_volume",
            0
        ),
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

    strength = (
        "🔥 STRONG"
        if signal["score"] >= STRONG_SCORE
        else "⚡ SIGNAL"
    )

    reasons = ", ".join(
        signal["reasons"][:5]
    )

    msg = (
        f"{emoji} {strength} — {direction}\n\n"
        f"💰 Symbol: {signal['symbol']}\n"
        f"📊 Score: {signal['score']}/100\n\n"
        f"🎯 Entry: {signal['entry']:.8g}\n"
        f"🛑 SL: {signal['sl']:.8g}\n"
        f"🥇 TP1: {signal['tp1']:.8g}\n"
        f"🥈 TP2: {signal['tp2']:.8g}\n"
        f"🥉 TP3: {signal['tp3']:.8g}\n\n"
        f"📈 RSI: {signal['rsi']:.2f}\n"
        f"EMA20: {signal['ema20']:.8g}\n"
        f"EMA50: {signal['ema50']:.8g}\n"
        f"24h Change: {signal['change']:.2f}%\n\n"
        f"🐋 Whale Proxy: ACTIVE\n"
        f"🧠 Reasons: {reasons}\n\n"
        f"💵 PAPER MODE\n"
        f"🔴 REAL ORDERS: OFF\n\n"
        f"⏰ {now()}"
    )

    return msg


# ================================================================
# MARKET ERROR
# ================================================================

def market_error_message():

    return (
        "⚠️ OK-EX MARKET ERROR\n\n"
        "No usable USDT markets were returned.\n\n"
        "The bot is still running.\n"
        "Check GitHub Actions logs for:\n\n"
        "• HTTP STATUS\n"
        "• RAW RESPONSE\n"
        "• TICKER ROW COUNT\n"
        "• PAIRS ROW COUNT\n\n"
        f"⏰ {now()}"
    )


# ================================================================
# SCAN
# ================================================================

def scan_market():

    stats["scans"] += 1

    print()
    print("#" * 70)
    print("SCAN START:", now())
    print("#" * 70)

    tickers = get_tickers()

    pairs = get_pairs()

    symbols = set()

    # ------------------------------------------------------------
    # Prefer pairs + ticker intersection
    # ------------------------------------------------------------

    if pairs and tickers:

        symbols = pairs.intersection(
            set(tickers.keys())
        )

        print(
            "PAIR/TICKER INTERSECTION:",
            len(symbols)
        )

    # ------------------------------------------------------------
    # Ticker fallback
    # ------------------------------------------------------------

    if not symbols and tickers:

        print(
            "USING TICKER-ONLY FALLBACK"
        )

        symbols = set(tickers.keys())

    # ------------------------------------------------------------
    # Pair fallback
    # ------------------------------------------------------------

    if not symbols and pairs:

        print(
            "USING PAIRS-ONLY FALLBACK"
        )

        symbols = pairs

    if not symbols:

        print(
            "NO USDT MARKETS FOUND"
        )

        send_telegram(
            market_error_message()
        )

        return

    symbols = list(symbols)

    # ------------------------------------------------------------
    # Sort by quote volume
    # ------------------------------------------------------------

    symbols.sort(
        key=lambda s: tickers.get(
            s,
            {}
        ).get(
            "quote_volume",
            0
        ),
        reverse=True
    )

    symbols = symbols[:MAX_MARKETS]

    print(
        "FINAL MARKET COUNT:",
        len(symbols)
    )

    print(
        "TOP MARKETS:",
        symbols[:20]
    )

    candidates = []

    # ------------------------------------------------------------
    # Analyze markets
    # ------------------------------------------------------------

    for index, symbol in enumerate(symbols):

        print(
            f"[{index + 1}/{len(symbols)}] ANALYZING {symbol}"
        )

        ticker = tickers.get(symbol)

        if not ticker:
            continue

        try:

            signal = analyze_market(
                symbol,
                ticker
            )

            if signal:

                print(
                    "SIGNAL:",
                    symbol,
                    signal["direction"],
                    signal["score"]
                )

                candidates.append(signal)

        except Exception as e:

            print(
                "ANALYSIS ERROR",
                symbol,
                repr(e)
            )

        # Small delay to avoid hammering API
        time.sleep(0.15)

    # ------------------------------------------------------------
    # Sort strongest
    # ------------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # ------------------------------------------------------------
    # Send signals
    # ------------------------------------------------------------

    sent = 0

    for signal in candidates:

        symbol = signal["symbol"]

        previous = last_signal_time.get(
            symbol,
            0
        )

        if time.time() - previous < COOLDOWN:

            print(
                "COOLDOWN:",
                symbol
            )

            continue

        msg = signal_message(signal)

        if send_telegram(msg):

            last_signal_time[symbol] = time.time()

            stats["signals"] += 1

            sent += 1

        if sent >= MAX_SIGNALS_PER_SCAN:
            break

    # ------------------------------------------------------------
    # Scan summary
    # ------------------------------------------------------------

    summary = (
        "🔎 SCAN COMPLETE\n\n"
        f"📊 Markets: {len(symbols)}\n"
        f"🎯 Candidates: {len(candidates)}\n"
        f"📨 Signals sent: {sent}\n\n"
        f"🟢 Paper Mode: ON\n"
        f"🔴 Real Orders: OFF\n\n"
        f"⏰ {now()}"
    )

    print(summary)

    if sent == 0:
        send_telegram(summary)


# ================================================================
# COMMAND-LIKE TEST
# ================================================================

def startup_test():

    msg = (
        "🟢 OK-EX BOT STARTED\n\n"
        "📡 OK-EX API: ONLINE\n"
        "🐋 Scanner: ONLINE\n"
        "🟢 Paper Mode: ON\n"
        "🔴 Real Orders: OFF\n\n"
        "🔎 Market discovery starting...\n\n"
        f"⏰ {now()}"
    )

    send_telegram(msg)


# ================================================================
# STATUS
# ================================================================

def status_message():

    return (
        "📊 OK-EX BOT STATUS\n\n"
        "🟢 Bot: RUNNING\n"
        "🟢 Paper Mode: ON\n"
        "🔴 Real Orders: OFF\n"
        f"🔎 Scans: {stats['scans']}\n"
        f"🎯 Signals: {stats['signals']}\n"
        f"⚠️ Errors: {stats['errors']}\n"
        f"⏱ Scan interval: {SCAN_INTERVAL}s\n"
        f"⏰ {now()}"
    )


# ================================================================
# MAIN
# ================================================================

def main():

    print()
    print("=" * 70)
    print("OK-EX IRAN PAPER SIGNAL BOT")
    print("=" * 70)

    print("BOT TOKEN:", "SET" if BOT_TOKEN else "MISSING")
    print("CHAT ID:", "SET" if CHAT_ID else "MISSING")
    print("BASE:", OKEX_BASE)
    print("PAPER MODE:", PAPER_MODE)
    print("REAL ORDERS:", REAL_ORDERS)

    if not BOT_TOKEN or not CHAT_ID:

        print()
        print("ERROR: Telegram secrets are missing.")

        return

    startup_test()

    # First scan immediately
    scan_market()

    last_scan = time.time()

    while True:

        try:

            time.sleep(10)

            if (
                time.time() - last_scan
                >= SCAN_INTERVAL
            ):

                last_scan = time.time()

                scan_market()

        except KeyboardInterrupt:

            print(
                "BOT STOPPED BY USER"
            )

            break

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                repr(e)
            )

            stats["errors"] += 1

            time.sleep(30)


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":
    main()
