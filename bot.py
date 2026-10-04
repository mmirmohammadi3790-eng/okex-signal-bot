# ================================================================
# OK-EX IRAN PAPER FUTURES SIGNAL BOT
# GITHUB ACTIONS
# ALL USDT MARKETS
# LONG / SHORT
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
TELEGRAM_API = "https://api.telegram.org"

SCAN_INTERVAL = 300
COOLDOWN = 1800

MIN_SCORE = 60
STRONG_SCORE = 80

MAX_SIGNALS_PER_SCAN = 3

PAPER_MODE = True
REAL_ORDERS = False

# برای تست اولیه تعداد بازارها را محدود نمی‌کنیم
MAX_MARKETS = 9999

# ================================================================
# TELEGRAM
# ================================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not CHAT_ID:
    CHAT_ID = os.getenv("CHAT_ID", "")

# ================================================================
# SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "OK-EX-IRAN-PAPER-BOT/2.0",
    "Accept": "application/json"
})

# ================================================================
# NUMBER
# ================================================================

def num(value, default=0.0):

    try:

        if value is None:
            return default

        return float(
            str(value).replace(",", "")
        )

    except Exception:

        return default


# ================================================================
# TELEGRAM SEND
# ================================================================

def telegram_send(message):

    if not BOT_TOKEN:

        print("TELEGRAM TOKEN MISSING")

        return False

    if not CHAT_ID:

        print("TELEGRAM CHAT ID MISSING")

        return False

    url = (
        TELEGRAM_API
        + "/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        r = requests.post(
            url,
            data=data,
            timeout=20
        )

        print(
            "TELEGRAM:",
            r.status_code
        )

        if r.ok:

            return True

        print(
            "TELEGRAM ERROR:",
            r.text[:500]
        )

    except Exception as e:

        print(
            "TELEGRAM EXCEPTION:",
            e
        )

    return False


# ================================================================
# API GET
# ================================================================

def api_get(path, params=None):

    url = OKEX_BASE + path

    try:

        r = session.get(
            url,
            params=params,
            timeout=20
        )

        print(
            "GET:",
            r.status_code,
            r.url
        )

        if r.status_code != 200:

            print(
                "HTTP ERROR:",
                r.text[:500]
            )

            return None

        try:

            data = r.json()

        except Exception as e:

            print(
                "JSON PARSE ERROR:",
                e
            )

            print(
                "BODY:",
                r.text[:1000]
            )

            return None

        return data

    except Exception as e:

        print(
            "API REQUEST ERROR:",
            e
        )

        return None


# ================================================================
# EXTRACT LIST
# ================================================================

def extract_list(data):

    if isinstance(data, list):

        return data

    if not isinstance(data, dict):

        return []

    # رایج‌ترین ساختارها
    for key in [
        "res",
        "data",
        "result",
        "rows",
        "list",
        "items"
    ]:

        value = data.get(key)

        if isinstance(value, list):

            return value

        # بعضی APIها ممکن است data را داخل dict بدهند
        if isinstance(value, dict):

            for subkey in [
                "res",
                "data",
                "result",
                "rows",
                "list",
                "items"
            ]:

                subvalue = value.get(subkey)

                if isinstance(subvalue, list):

                    return subvalue

    return []


# ================================================================
# NORMALIZE SYMBOL
# ================================================================

def normalize_symbol(value):

    if value is None:

        return ""

    symbol = str(
        value
    ).upper().strip()

    symbol = symbol.replace(
        "_",
        "-"
    )

    symbol = symbol.replace(
        "/",
        "-"
    )

    # BTCUSDT -> BTC-USDT
    if (
        symbol.endswith("USDT")
        and "-"
        not in symbol
    ):

        symbol = (
            symbol[:-4]
            + "-USDT"
        )

    return symbol


# ================================================================
# GET SYMBOL FROM ROW
# ================================================================

def symbol_from_row(row):

    if isinstance(row, str):

        return normalize_symbol(
            row
        )

    if not isinstance(row, dict):

        return ""

    possible = [
        "symbol",
        "instId",
        "instrument",
        "pair",
        "market",
        "name",
        "code"
    ]

    for key in possible:

        value = row.get(key)

        if value:

            symbol = normalize_symbol(
                value
            )

            if symbol.endswith(
                "-USDT"
            ):

                return symbol

    return ""


# ================================================================
# GET SYMBOLS FROM PAIRS
# ================================================================

def get_symbols_from_pairs():

    print("")
    print(
        "REQUESTING PAIRS..."
    )

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    if data is None:

        print(
            "PAIRS RESPONSE: NONE"
        )

        return []

    print(
        "PAIRS RESPONSE TYPE:",
        type(data).__name__
    )

    if isinstance(data, dict):

        print(
            "PAIRS KEYS:",
            list(data.keys())[:20]
        )

    rows = extract_list(
        data
    )

    print(
        "PAIRS ROW COUNT:",
        len(rows)
    )

    symbols = []

    for row in rows:

        symbol = symbol_from_row(
            row
        )

        if symbol.endswith(
            "-USDT"
        ):

            symbols.append(
                symbol
            )

    symbols = sorted(
        set(symbols)
    )

    print(
        "PAIRS USDT COUNT:",
        len(symbols)
    )

    if symbols:

        print(
            "PAIRS SAMPLE:",
            symbols[:10]
        )

    return symbols


# ================================================================
# GET TICKERS
# ================================================================

def get_tickers():

    print("")
    print(
        "REQUESTING TICKERS..."
    )

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    if data is None:

        print(
            "TICKERS RESPONSE: NONE"
        )

        return []

    print(
        "TICKERS RESPONSE TYPE:",
        type(data).__name__
    )

    if isinstance(data, dict):

        print(
            "TICKERS KEYS:",
            list(data.keys())[:20]
        )

    rows = extract_list(
        data
    )

    print(
        "TICKER ROW COUNT:",
        len(rows)
    )

    return rows


# ================================================================
# PARSE TICKER
# ================================================================

def parse_ticker(row):

    if not isinstance(row, dict):

        return None

    symbol = symbol_from_row(
        row
    )

    if not symbol.endswith(
        "-USDT"
    ):

        return None

    last = num(
        row.get("last")
        or row.get("lastPrice")
        or row.get("close")
        or row.get("price")
    )

    open_price = num(
        row.get("open")
        or row.get("open24h")
        or row.get("openPrice")
    )

    high = num(
        row.get("high")
        or row.get("high24h")
    )

    low = num(
        row.get("low")
        or row.get("low24h")
    )

    volume = num(
        row.get("volume")
        or row.get("vol")
        or row.get("vol24h")
        or row.get("baseVolume")
    )

    quote_volume = num(
        row.get("quoteVolume")
        or row.get("quoteVol")
        or row.get("turnover")
        or row.get("amount")
        or row.get("quoteVol24h")
    )

    change = num(
        row.get("change")
        or row.get("change24h")
        or row.get("priceChangePercent")
        or row.get("changePercent")
    )

    if (
        change == 0
        and open_price > 0
        and last > 0
    ):

        change = (
            (
                last
                - open_price
            )
            / open_price
        ) * 100

    if last <= 0:

        return None

    return {
        "symbol": symbol,
        "last": last,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": volume,
        "quote_volume": quote_volume,
        "change": change
    }


# ================================================================
# GET CANDLES
# ================================================================

def get_candles(
    symbol,
    interval="1h",
    limit=60
):

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    data = api_get(
        "/api/v1/spot/public/candles",
        params
    )

    if not data:

        return []

    rows = extract_list(
        data
    )

    candles = []

    for row in rows:

        try:

            if isinstance(row, dict):

                o = num(
                    row.get("open")
                    or row.get("o")
                )

                h = num(
                    row.get("high")
                    or row.get("h")
                )

                l = num(
                    row.get("low")
                    or row.get("l")
                )

                c = num(
                    row.get("close")
                    or row.get("c")
                )

                v = num(
                    row.get("volume")
                    or row.get("vol")
                    or row.get("v")
                )

            else:

                if len(row) < 6:

                    continue

                o = num(row[1])
                h = num(row[2])
                l = num(row[3])
                c = num(row[4])
                v = num(row[5])

            if c > 0:

                candles.append({
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v
                })

        except Exception:

            continue

    return candles[-limit:]


# ================================================================
# EMA
# ================================================================

def ema(values, period):

    if len(values) < period:

        return None

    multiplier = (
        2 / (period + 1)
    )

    result = (
        sum(values[:period])
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

def rsi(values, period=14):

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

        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


# ================================================================
# ANALYZE
# ================================================================

def analyze(
    symbol,
    ticker
):

    candles = get_candles(
        symbol,
        "1h",
        60
    )

    if len(candles) < 30:

        return None

    closes = [
        x["close"]
        for x in candles
    ]

    volumes = [
        x["volume"]
        for x in candles
    ]

    price = closes[-1]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    rsi14 = rsi(
        closes,
        14
    )

    if (
        ema20 is None
        or ema50 is None
        or rsi14 is None
    ):

        return None

    # ------------------------------------------------------------
    # MOMENTUM
    # ------------------------------------------------------------

    momentum = 0.0

    if len(closes) >= 6:

        old = closes[-6]

        if old > 0:

            momentum = (
                (
                    price - old
                )
                / old
            ) * 100

    # ------------------------------------------------------------
    # VOLUME
    # ------------------------------------------------------------

    recent_volume = volumes[-1]

    previous = volumes[-21:-1]

    if previous:

        avg_volume = (
            sum(previous)
            / len(previous)
        )

    else:

        avg_volume = 0

    if avg_volume > 0:

        volume_ratio = (
            recent_volume
            / avg_volume
        )

    else:

        volume_ratio = 0

    # ------------------------------------------------------------
    # CANDLE
    # ------------------------------------------------------------

    candle = candles[-1]

    bullish = (
        candle["close"]
        > candle["open"]
    )

    bearish = (
        candle["close"]
        < candle["open"]
    )

    # ------------------------------------------------------------
    # SCORE
    # ------------------------------------------------------------

    long_score = 0
    short_score = 0

    if price > ema20:

        long_score += 15

    elif price < ema20:

        short_score += 15

    if ema20 > ema50:

        long_score += 15

    elif ema20 < ema50:

        short_score += 15

    if 50 <= rsi14 <= 68:

        long_score += 15

    elif 32 <= rsi14 <= 50:

        short_score += 15

    if momentum > 0.5:

        long_score += 15

    elif momentum < -0.5:

        short_score += 15

    if volume_ratio >= 1.5:

        if bullish:

            long_score += 15

        elif bearish:

            short_score += 15

    elif volume_ratio >= 1.15:

        if bullish:

            long_score += 8

        elif bearish:

            short_score += 8

    daily_change = ticker["change"]

    if daily_change > 2:

        long_score += 10

    elif daily_change < -2:

        short_score += 10

    # ------------------------------------------------------------
    # LIQUIDITY / WHALE PROXY
    # ------------------------------------------------------------

    liquidity = ticker["quote_volume"]

    if liquidity <= 0:

        liquidity = (
            ticker["volume"]
            * ticker["last"]
        )

    whale_score = 0

    if liquidity >= 500000:

        whale_score = 5

    if liquidity >= 1000000:

        whale_score = 10

    if liquidity >= 5000000:

        whale_score = 15

    if long_score > short_score:

        direction = "LONG"

        score = (
            long_score
            + whale_score
        )

    elif short_score > long_score:

        direction = "SHORT"

        score = (
            short_score
            + whale_score
        )

    else:

        return None

    score = min(
        score,
        100
    )

    if score < MIN_SCORE:

        return None

    # ------------------------------------------------------------
    # RANGE
    # ------------------------------------------------------------

    ranges = []

    for candle in candles[-20:]:

        high = candle["high"]
        low = candle["low"]

        if high >= low:

            ranges.append(
                high - low
            )

    if ranges:

        avg_range = (
            sum(ranges)
            / len(ranges)
        )

    else:

        avg_range = (
            price * 0.01
        )

    if avg_range <= 0:

        avg_range = (
            price * 0.01
        )

    # ------------------------------------------------------------
    # ENTRY / SL / TP
    # ------------------------------------------------------------

    entry = price

    if direction == "LONG":

        sl = (
            entry
            - avg_range * 1.5
        )

        risk = (
            entry - sl
        )

        tp1 = (
            entry
            + risk * 1.2
        )

        tp2 = (
            entry
            + risk * 2
        )

        tp3 = (
            entry
            + risk * 3
        )

    else:

        sl = (
            entry
            + avg_range * 1.5
        )

        risk = (
            sl - entry
        )

        tp1 = (
            entry
            - risk * 1.2
        )

        tp2 = (
            entry
            - risk * 2
        )

        tp3 = (
            entry
            - risk * 3
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
        "rsi": rsi14,
        "momentum": momentum,
        "volume_ratio": volume_ratio,
        "change24": daily_change,
        "liquidity": liquidity,
        "whale_score": whale_score
    }


# ================================================================
# FORMAT PRICE
# ================================================================

def fmt_price(value):

    if value >= 1000:

        return f"{value:,.2f}"

    if value >= 1:

        return f"{value:,.4f}"

    if value >= 0.01:

        return f"{value:,.6f}"

    return f"{value:.8f}"


# ================================================================
# FORMAT SIGNAL
# ================================================================

def format_signal(signal):

    if signal["direction"] == "LONG":

        emoji = "🟢"

    else:

        emoji = "🔴"

    if signal["score"] >= STRONG_SCORE:

        strength = "🔥 STRONG"

    else:

        strength = "⚡ SIGNAL"

    return f"""
{emoji} <b>OK-EX IRAN FUTURES</b>

<b>{strength} — {signal["direction"]}</b>

🪙 <b>{signal["symbol"]}</b>

📊 Score:
<b>{signal["score"]}/100</b>

💰 Entry:
<b>{fmt_price(signal["entry"])}</b>

🛑 SL:
<b>{fmt_price(signal["sl"])}</b>

🎯 TP1:
<b>{fmt_price(signal["tp1"])}</b>

🎯 TP2:
<b>{fmt_price(signal["tp2"])}</b>

🎯 TP3:
<b>{fmt_price(signal["tp3"])}</b>

📈 RSI:
{signal["rsi"]:.1f}

📉 Momentum:
{signal["momentum"]:.2f}%

📊 Volume:
{signal["volume_ratio"]:.2f}x

🐋 Whale Proxy:
{signal["whale_score"]}/15

📊 24H:
{signal["change24"]:.2f}%

💧 Liquidity:
{signal["liquidity"]:,.0f} USDT

⚠️ <b>PAPER SIGNAL ONLY</b>

❌ REAL ORDER: OFF

🕐 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""


# ================================================================
# MARKET SCAN
# ================================================================

last_signals = {}


def scan_market():

    print("")
    print("=" * 70)
    print(
        "MARKET SCAN:",
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )
    print("=" * 70)

    # ------------------------------------------------------------
    # TICKERS FIRST
    # ------------------------------------------------------------

    ticker_rows = get_tickers()

    print(
        "RAW TICKERS:",
        len(ticker_rows)
    )

    ticker_map = {}

    for row in ticker_rows:

        ticker = parse_ticker(
            row
        )

        if ticker:

            ticker_map[
                ticker["symbol"]
            ] = ticker

    print(
        "USDT TICKERS:",
        len(ticker_map)
    )

    # ------------------------------------------------------------
    # PAIRS
    # ------------------------------------------------------------

    pair_symbols = (
        get_symbols_from_pairs()
    )

    # ------------------------------------------------------------
    # FALLBACK
    # ------------------------------------------------------------

    if pair_symbols:

        symbols = sorted(
            set(pair_symbols)
            & set(ticker_map.keys())
        )

        print(
            "USDT MARKETS FROM PAIRS:",
            len(pair_symbols)
        )

    else:

        print(
            "PAIRS EMPTY - USING TICKERS FALLBACK"
        )

        symbols = sorted(
            ticker_map.keys()
        )

    # ------------------------------------------------------------
    # FINAL MARKET LIST
    # ------------------------------------------------------------

    if not symbols:

        print(
            "NO USDT MARKETS AVAILABLE"
        )

        telegram_send(
            "⚠️ <b>OK-EX MARKET ERROR</b>\n\n"
            "No USDT markets were returned "
            "by the API."
        )

        return

    print(
        "FINAL USDT MARKETS:",
        len(symbols)
    )

    # ------------------------------------------------------------
    # SORT BY LIQUIDITY
    # ------------------------------------------------------------

    candidates = []

    for symbol in symbols:

        ticker = ticker_map.get(
            symbol
        )

        if not ticker:

            continue

        liquidity = (
            ticker["quote_volume"]
        )

        if liquidity <= 0:

            liquidity = (
                ticker["volume"]
                * ticker["last"]
            )

        if liquidity <= 0:

            continue

        candidates.append(
            (
                symbol,
                ticker,
                liquidity
            )
        )

    candidates.sort(
        key=lambda x: x[2],
        reverse=True
    )

    candidates = candidates[
        :MAX_MARKETS
    ]

    print(
        "MARKETS TO ANALYZE:",
        len(candidates)
    )

    # ------------------------------------------------------------
    # ANALYSIS
    # ------------------------------------------------------------

    signals = []

    for index, item in enumerate(
        candidates,
        start=1
    ):

        symbol = item[0]
        ticker = item[1]

        print(
            f"[{index}/{len(candidates)}] "
            f"{symbol}"
        )

        try:

            signal = analyze(
                symbol,
                ticker
            )

            if signal:

                signals.append(
                    signal
                )

                print(
                    ">>> SIGNAL",
                    symbol,
                    signal["direction"],
                    signal["score"]
                )

        except Exception as e:

            print(
                "ANALYZE ERROR:",
                symbol,
                e
            )

        time.sleep(0.10)

    # ------------------------------------------------------------
    # SORT SIGNALS
    # ------------------------------------------------------------

    signals.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print(
        "SIGNALS FOUND:",
        len(signals)
    )

    # ------------------------------------------------------------
    # SEND SIGNALS
    # ------------------------------------------------------------

    now = time.time()

    sent = 0

    for signal in signals:

        if sent >= MAX_SIGNALS_PER_SCAN:

            break

        key = (
            signal["symbol"]
            + "_"
            + signal["direction"]
        )

        previous = (
            last_signals.get(
                key,
                0
            )
        )

        if (
            now - previous
            < COOLDOWN
        ):

            print(
                "COOLDOWN:",
                key
            )

            continue

        message = format_signal(
            signal
        )

        if telegram_send(message):

            last_signals[key] = now

            sent += 1

            print(
                "SIGNAL SENT:",
                key
            )

    # ------------------------------------------------------------
    # NO SIGNAL
    # ------------------------------------------------------------

    if sent == 0:

        telegram_send(
            "🔎 <b>SCAN COMPLETE</b>\n\n"
            f"🪙 Markets checked: "
            f"{len(candidates)}\n"
            f"📊 Signals found: "
            f"{len(signals)}\n\n"
            "ℹ️ No new signal above threshold."
        )

    print(
        "SIGNALS SENT:",
        sent
    )

    print("=" * 70)


# ================================================================
# TELEGRAM COMMANDS
# ================================================================

last_update_id = 0


def check_commands():

    global last_update_id

    if not BOT_TOKEN:

        return

    try:

        url = (
            TELEGRAM_API
            + "/bot"
            + BOT_TOKEN
            + "/getUpdates"
        )

        r = requests.get(
            url,
            params={
                "timeout": 1,
                "offset": (
                    last_update_id + 1
                )
            },
            timeout=5
        )

        if not r.ok:

            return

        data = r.json()

        for update in data.get(
            "result",
            []
        ):

            last_update_id = update.get(
                "update_id",
                last_update_id
            )

            message = update.get(
                "message",
                {}
            )

            text = str(
                message.get(
                    "text",
                    ""
                )
            ).strip()

            if not text:

                continue

            print(
                "COMMAND:",
                text
            )

            if text == "/test":

                telegram_send(
                    "✅ <b>TELEGRAM TEST OK</b>\n\n"
                    "🟢 Bot is online\n"
                    "🟢 Paper Mode ON\n"
                    "🔴 Real Orders OFF"
                )

            elif text == "/status":

                symbols = get_symbols_from_pairs()

                telegram_send(
                    "🟢 <b>BOT STATUS</b>\n\n"
                    "📡 OK-EX API: ONLINE\n"
                    f"🪙 Markets: {len(symbols)}\n"
                    "🟢 Paper Mode: ON\n"
                    "🔴 Real Orders: OFF"
                )

            elif text == "/scan":

                telegram_send(
                    "🔎 <b>MANUAL SCAN STARTED</b>"
                )

                scan_market()

            elif text == "/start":

                telegram_send(
                    "🤖 <b>OK-EX IRAN BOT</b>\n\n"
                    "🟢 Online\n"
                    "📡 API Connected\n"
                    "🐋 Scanner Active\n"
                    "🟢 Paper Mode ON\n"
                    "🔴 Real Orders OFF\n\n"
                    "/test\n"
                    "/status\n"
                    "/scan\n"
                    "/help"
                )

            elif text == "/help":

                telegram_send(
                    "🐋 <b>OK-EX SIGNAL BOT</b>\n\n"
                    "/start\n"
                    "/test\n"
                    "/status\n"
                    "/scan\n"
                    "/help"
                )

    except Exception as e:

        print(
            "COMMAND ERROR:",
            e
        )


# ================================================================
# MAIN
# ================================================================

def main():

    print("")
    print("=" * 70)
    print(
        "OK-EX IRAN SIGNAL BOT STARTED"
    )
    print("=" * 70)

    print(
        "PAPER_MODE:",
        PAPER_MODE
    )

    print(
        "REAL_ORDERS:",
        REAL_ORDERS
    )

    print(
        "BOT TOKEN:",
        "OK" if BOT_TOKEN else "MISSING"
    )

    print(
        "CHAT ID:",
        "OK" if CHAT_ID else "MISSING"
    )

    print("=" * 70)

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
    # TELEGRAM START MESSAGE
    # ------------------------------------------------------------

    telegram_send(
        "🟢 <b>OK-EX BOT STARTED</b>\n\n"
        "📡 OK-EX API: ONLINE\n"
        "🐋 Scanner: ONLINE\n"
        "🟢 Paper Mode: ON\n"
        "🔴 Real Orders: OFF\n\n"
        "🔎 Market discovery starting..."
    )

    # ------------------------------------------------------------
    # INITIAL SCAN
    # ------------------------------------------------------------

    try:

        scan_market()

    except Exception as e:

        print(
            "INITIAL SCAN ERROR:",
            e
        )

    last_scan = time.time()

    # ------------------------------------------------------------
    # INFINITE LOOP
    # ------------------------------------------------------------

    while True:

        try:

            check_commands()

            now = time.time()

            if (
                now - last_scan
                >= SCAN_INTERVAL
            ):

                scan_market()

                last_scan = time.time()

            print(
                "HEARTBEAT:",
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            time.sleep(10)

        except KeyboardInterrupt:

            print(
                "BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                e
            )

            time.sleep(15)


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":

    main()
