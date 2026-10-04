# ================================================================
# 🐋 OK-EX IRAN — V5 WATCHLIST
# PAPER SIGNAL ONLY
# ALL USDT MARKETS
# LONG / SHORT / WATCH
# ENTRY / SL / TP1 / TP2 / TP3
# REAL CANDLES + EMA + RSI + MOMENTUM + VOLUME
# TELEGRAM
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

PAPER_MODE = True
REAL_ORDERS = False

SCAN_INTERVAL = 300
COOLDOWN = 1800

MAX_MARKETS = 9999
MAX_SIGNALS_PER_SCAN = 5
WATCHLIST_SIZE = 5

MIN_SCORE = 50
STRONG_SCORE = 70

REQUEST_TIMEOUT = 20

CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100
CANDLE_HOURS = 120

# ================================================================
# TELEGRAM SECRETS
# ================================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

# ================================================================
# SESSION
# ================================================================

session = requests.Session()

last_sent = {}

# ================================================================
# TELEGRAM
# ================================================================

def telegram_send(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram secrets are missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

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

        print("Telegram error:", r.status_code, r.text[:500])
        return False

    except Exception as e:
        print("Telegram exception:", e)
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
            print("HTTP ERROR:", r.status_code, url)
            return None

        return r.json()

    except Exception as e:
        print("REQUEST ERROR:", e)
        return None


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    data = get_json("/api/v1/spot/public/tickers")

    if not data:
        return {}

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
        except:
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
        except:
            quote_volume = 0

        try:
            change = float(
                item.get("priceChangePercent")
                or item.get("changePercent")
                or item.get("change")
                or 0
            )
        except:
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

    data = get_json("/api/v1/spot/public/pairs")

    if not data:
        return []

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

        if symbol:

            symbol = normalize_symbol(symbol)

            if symbol.endswith("USDT"):
                symbols.append(symbol)

    return list(dict.fromkeys(symbols))


# ================================================================
# SYMBOL NORMALIZER
# ================================================================

def normalize_symbol(symbol):

    return (
        str(symbol)
        .upper()
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
        .strip()
    )


# ================================================================
# MARKET DISCOVERY
# ================================================================

def discover_markets(tickers, pairs):

    ticker_symbols = set(tickers.keys())
    pair_symbols = set(pairs)

    if ticker_symbols and pair_symbols:

        symbols = ticker_symbols.intersection(pair_symbols)

        if not symbols:
            symbols = ticker_symbols

    elif ticker_symbols:

        symbols = ticker_symbols

    else:

        symbols = pair_symbols

    symbols = [
        s for s in symbols
        if s.endswith("USDT")
    ]

    return sorted(symbols)[:MAX_MARKETS]


# ================================================================
# CANDLES
# ================================================================

def get_candles(symbol):

    end_time = int(time.time() * 1000)

    start_time = end_time - (
        CANDLE_HOURS * 60 * 60 * 1000
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

    rows = data.get("res")

    if rows is None:
        rows = data.get("data")

    if rows is None:
        rows = data.get("result")

    if not isinstance(rows, list):
        return []

    candles = []

    for row in rows:

        try:

            if isinstance(row, dict):

                timestamp = float(
                    row.get("timestamp")
                    or row.get("time")
                    or row.get("ts")
                )

                open_price = float(
                    row.get("open")
                )

                high = float(
                    row.get("high")
                )

                low = float(
                    row.get("low")
                )

                close = float(
                    row.get("close")
                )

                volume = float(
                    row.get("volume")
                    or row.get("vol")
                    or 0
                )

            elif isinstance(row, list):

                # Common exchange candle format:
                # [timestamp, open, high, low, close, volume...]

                timestamp = float(row[0])
                open_price = float(row[1])
                high = float(row[2])
                low = float(row[3])
                close = float(row[4])
                volume = float(row[5]) if len(row) > 5 else 0

            else:
                continue

            candles.append({
                "time": timestamp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            })

        except Exception:
            continue

    candles.sort(key=lambda x: x["time"])

    return candles


# ================================================================
# EMA
# ================================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    value = sum(values[:period]) / period

    for price in values[period:]:

        value = (
            (price - value) * multiplier
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
# ANALYSIS
# ================================================================

def analyze(symbol, candles, ticker):

    if len(candles) < 60:
        return None

    closes = [x["close"] for x in candles]
    highs = [x["high"] for x in candles]
    lows = [x["low"] for x in candles]
    volumes = [x["volume"] for x in candles]

    price = ticker["price"]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    current_rsi = rsi(closes, 14)

    if ema20 is None or ema50 is None or current_rsi is None:
        return None

    # ------------------------------------------------------------
    # MOMENTUM
    # ------------------------------------------------------------

    lookback = 6

    if len(closes) > lookback:

        momentum = (
            (closes[-1] - closes[-1-lookback])
            / closes[-1-lookback]
        ) * 100

    else:
        momentum = 0

    # ------------------------------------------------------------
    # TREND
    # ------------------------------------------------------------

    trend10 = 0

    if closes[-1] > closes[-11]:
        trend10 = 1
    elif closes[-1] < closes[-11]:
        trend10 = -1

    # ------------------------------------------------------------
    # VOLUME
    # ------------------------------------------------------------

    recent_volumes = volumes[-21:-1]

    avg_volume = (
        sum(recent_volumes) /
        len(recent_volumes)
        if recent_volumes else 0
    )

    if avg_volume > 0:
        volume_ratio = volumes[-1] / avg_volume
    else:
        volume_ratio = 1

    # ------------------------------------------------------------
    # BREAKOUT / BREAKDOWN
    # ------------------------------------------------------------

    previous_high = max(highs[-6:-1])
    previous_low = min(lows[-6:-1])

    breakout = closes[-1] > previous_high
    breakdown = closes[-1] < previous_low

    # ------------------------------------------------------------
    # SCORE
    # ------------------------------------------------------------

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # EMA20 / EMA50
    if price > ema20:
        long_score += 10
        long_reasons.append("Price > EMA20")
    else:
        short_score += 10
        short_reasons.append("Price < EMA20")

    if ema20 > ema50:
        long_score += 15
        long_reasons.append("EMA20 > EMA50")
    else:
        short_score += 15
        short_reasons.append("EMA20 < EMA50")

    # EMA200 if available
    if ema200 is not None:

        if price > ema200:
            long_score += 5
            long_reasons.append("Above EMA200")
        else:
            short_score += 5
            short_reasons.append("Below EMA200")

    # RSI
    if 50 <= current_rsi <= 68:
        long_score += 10
        long_reasons.append(
            f"RSI bullish {current_rsi:.1f}"
        )

    if 32 <= current_rsi < 50:
        short_score += 10
        short_reasons.append(
            f"RSI bearish {current_rsi:.1f}"
        )

    if current_rsi > 72:
        short_score += 5
        short_reasons.append(
            f"RSI high {current_rsi:.1f}"
        )

    if current_rsi < 28:
        long_score += 5
        long_reasons.append(
            f"RSI low {current_rsi:.1f}"
        )

    # Momentum
    if momentum > 1:
        long_score += 10
        long_reasons.append(
            f"Momentum +{momentum:.2f}%"
        )

    elif momentum < -1:
        short_score += 10
        short_reasons.append(
            f"Momentum {momentum:.2f}%"
        )

    # Trend
    if trend10 > 0:
        long_score += 5
        long_reasons.append("10-candle uptrend")

    elif trend10 < 0:
        short_score += 5
        short_reasons.append("10-candle downtrend")

    # Volume
    if volume_ratio >= 1.5:

        if momentum >= 0:
            long_score += 10
            long_reasons.append(
                f"Volume spike {volume_ratio:.2f}x"
            )

        else:
            short_score += 10
            short_reasons.append(
                f"Volume spike {volume_ratio:.2f}x"
            )

    elif volume_ratio >= 1.2:

        if momentum >= 0:
            long_score += 5
            long_reasons.append(
                f"Volume {volume_ratio:.2f}x"
            )

        else:
            short_score += 5
            short_reasons.append(
                f"Volume {volume_ratio:.2f}x"
            )

    # Breakout
    if breakout:
        long_score += 10
        long_reasons.append("Breakout")

    if breakdown:
        short_score += 10
        short_reasons.append("Breakdown")

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
        score = max(long_score, short_score)
        reasons = []

    # ------------------------------------------------------------
    # PAPER TRADE LEVELS
    # ------------------------------------------------------------

    if direction == "LONG":

        entry = price
        sl = entry * 0.985

        risk = entry - sl

        tp1 = entry + risk
        tp2 = entry + (risk * 2)
        tp3 = entry + (risk * 3)

    elif direction == "SHORT":

        entry = price
        sl = entry * 1.015

        risk = sl - entry

        tp1 = entry - risk
        tp2 = entry - (risk * 2)
        tp3 = entry - (risk * 3)

    else:

        entry = price
        sl = price
        tp1 = price
        tp2 = price
        tp3 = price

    # Liquidity proxy
    quote_volume = ticker.get("quote_volume", 0)

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "long_score": long_score,
        "short_score": short_score,
        "price": price,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
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
        "reasons": reasons,
    }


# ================================================================
# COOLDOWN
# ================================================================

def can_send(symbol):

    now = time.time()

    last = last_sent.get(symbol, 0)

    if now - last < COOLDOWN:
        return False

    return True


# ================================================================
# SIGNAL MESSAGE
# ================================================================

def signal_message(a):

    emoji = "🟢" if a["direction"] == "LONG" else "🔴"

    strength = (
        "🔥 STRONG"
        if a["score"] >= STRONG_SCORE
        else "⚡ SIGNAL"
    )

    reasons = "\n".join(
        f"• {x}" for x in a["reasons"][:6]
    )

    return f"""
{emoji} <b>OK-EX IRAN PAPER SIGNAL</b>

{strength}

🪙 <b>{a["symbol"]}</b>
📈 <b>{a["direction"]}</b>
🎯 Score: <b>{a["score"]}/100</b>

💰 Entry: <b>{a["entry"]:.8g}</b>
🛑 SL: <b>{a["sl"]:.8g}</b>

🎯 TP1: <b>{a["tp1"]:.8g}</b>
🎯 TP2: <b>{a["tp2"]:.8g}</b>
🎯 TP3: <b>{a["tp3"]:.8g}</b>

📊 RSI14: {a["rsi"]:.1f}
📐 EMA20: {a["ema20"]:.8g}
📐 EMA50: {a["ema50"]:.8g}

🚀 Momentum: {a["momentum"]:+.2f}%
📊 Volume: {a["volume_ratio"]:.2f}x

💧 Liquidity Proxy:
{a["quote_volume"]:.0f} USDT

<b>Reasons:</b>
{reasons}

🐋 Whale detection:
<b>Liquidity proxy only</b>

🟢 PAPER MODE: ON
🔴 REAL ORDERS: OFF

⏱ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


# ================================================================
# WATCHLIST MESSAGE
# ================================================================

def watchlist_message(items):

    lines = [
        "👀 <b>OK-EX WATCHLIST</b>",
        "",
        "سیگنال کامل هنوز تأیید نشده؛",
        "این‌ها نزدیک‌ترین کاندیداها هستند:",
        "",
    ]

    for i, a in enumerate(items, 1):

        if a["direction"] == "LONG":
            icon = "🟢"
        elif a["direction"] == "SHORT":
            icon = "🔴"
        else:
            icon = "⚪"

        lines.append(
            f"{i}. {icon} <b>{a['symbol']}</b> "
            f"{a['direction']} "
            f"Score {a['score']}/100"
        )

        lines.append(
            f"   💰 {a['price']:.8g} | "
            f"RSI {a['rsi']:.1f} | "
            f"Mom {a['momentum']:+.2f}% | "
            f"Vol {a['volume_ratio']:.2f}x"
        )

    lines.extend([
        "",
        f"🎯 Signal threshold: {MIN_SCORE}",
        f"🔥 Strong threshold: {STRONG_SCORE}",
        "",
        "🐋 Whale = liquidity proxy",
        "🟢 Paper Mode ON",
        "🔴 Real Orders OFF",
    ])

    return "\n".join(lines)


# ================================================================
# STATUS MESSAGE
# ================================================================

def status_message(markets, candidates, sent):

    return f"""
📊 <b>OK-EX BOT STATUS</b>

🟢 API: ONLINE
🟢 Candles: ONLINE
🟢 Telegram: ONLINE

📈 Markets: {markets}
🎯 Candidates: {candidates}
📨 Signals sent: {sent}

🎯 Minimum Score: {MIN_SCORE}
🔥 Strong Score: {STRONG_SCORE}

🕯 Candle: {CANDLE_INTERVAL}
⏱ Scan: {SCAN_INTERVAL}s

🟢 Paper Mode: ON
🔴 Real Orders: OFF

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


# ================================================================
# CANDLE TEST
# ================================================================

def candle_test():

    symbol = "SOLUSDT"

    candles = get_candles(symbol)

    if len(candles) >= 10:

        msg = f"""
🟢 <b>OK-EX CANDLE TEST PASSED</b>

🪙 Symbol: {symbol}
🕯 Candles: {len(candles)}

📡 API: ONLINE
⏱ startTime/endTime: OK

Scanner can continue.
"""

        telegram_send(msg)

        print(msg)

        return True

    msg = """
🔴 <b>OK-EX CANDLE TEST FAILED</b>

No valid candles returned.
"""

    telegram_send(msg)

    print(msg)

    return False


# ================================================================
# SCAN
# ================================================================

def scan():

    print("\n========================================")
    print("START SCAN")
    print(datetime.now())
    print("========================================")

    tickers = get_tickers()

    pairs = get_pairs()

    markets = discover_markets(
        tickers,
        pairs,
    )

    print("Markets:", len(markets))

    if not markets:

        telegram_send(
            "🔴 <b>SCAN ERROR</b>\n\n"
            "No USDT markets were returned."
        )

        return

    analyses = []

    checked = 0

    for symbol in markets:

        ticker = tickers.get(symbol)

        if not ticker:
            continue

        try:

            candles = get_candles(symbol)

            checked += 1

            if len(candles) < 60:
                continue

            result = analyze(
                symbol,
                candles,
                ticker,
            )

            if result:
                analyses.append(result)

        except Exception as e:

            print(
                "Analysis error",
                symbol,
                e,
            )

        time.sleep(0.05)

    # ------------------------------------------------------------
    # SORT
    # ------------------------------------------------------------

    analyses.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    # ------------------------------------------------------------
    # TRUE SIGNALS
    # ------------------------------------------------------------

    strong_signals = []

    for a in analyses:

        if a["score"] < MIN_SCORE:
            continue

        if a["direction"] not in ("LONG", "SHORT"):
            continue

        difference = abs(
            a["long_score"] -
            a["short_score"]
        )

        if difference < 10:
            continue

        strong_signals.append(a)

    strong_signals.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    strong_signals = strong_signals[
        :MAX_SIGNALS_PER_SCAN
    ]

    sent = 0

    for a in strong_signals:

        if not can_send(a["symbol"]):
            continue

        if telegram_send(
            signal_message(a)
        ):

            last_sent[a["symbol"]] = time.time()

            sent += 1

    # ------------------------------------------------------------
    # WATCHLIST
    # ------------------------------------------------------------

    watchlist = [
        x for x in analyses
        if x["direction"] in ("LONG", "SHORT")
    ]

    watchlist.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    watchlist = watchlist[
        :WATCHLIST_SIZE
    ]

    if watchlist:

        telegram_send(
            watchlist_message(watchlist)
        )

    # ------------------------------------------------------------
    # CONSOLE
    # ------------------------------------------------------------

    print("\nSCAN COMPLETE")
    print("Markets:", len(markets))
    print("Checked:", checked)
    print("Analyses:", len(analyses))
    print("Signals:", len(strong_signals))
    print("Sent:", sent)

    if watchlist:

        print("\nWATCHLIST:")

        for a in watchlist:

            print(
                a["symbol"],
                a["direction"],
                a["score"]
            )

    # ------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------

    telegram_send(
        status_message(
            len(markets),
            len(strong_signals),
            sent,
        )
    )


# ================================================================
# STARTUP
# ================================================================

def startup():

    msg = """
🟢 <b>OK-EX IRAN BOT STARTED</b>

📡 OK-EX API: ONLINE
🐋 Scanner: ONLINE

🟢 Paper Mode: ON
🔴 Real Orders: OFF

🔎 Market discovery starting...

🎯 Minimum Score: 50/100
🔥 Strong Score: 70/100

📨 Max signals/scan: 5
👀 Watchlist: TOP 5

🕯 Real Candle: ON
⏱ Official startTime/endTime: ON

⚠️ No real trades will be executed.
"""

    telegram_send(msg)

    print(msg)


# ================================================================
# MAIN
# ================================================================

def main():

    startup()

    candle_test()

    while True:

        try:

            scan()

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                repr(e)
            )

            telegram_send(
                "⚠️ <b>BOT ERROR</b>\n\n"
                f"<code>{str(e)[:800]}</code>"
            )

        print(
            f"\nNext scan in {SCAN_INTERVAL} seconds..."
        )

        time.sleep(SCAN_INTERVAL)


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":
    main()
