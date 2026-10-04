# ================================================================
# OK-EX IRAN FUTURES SIGNAL BOT
# GITHUB ACTIONS - PAPER SIGNAL ONLY
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

# ================================================================
# TELEGRAM SECRETS
# ================================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not CHAT_ID:
    CHAT_ID = os.getenv("CHAT_ID", "")

# ================================================================
# HTTP SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "OK-EX-IRAN-Paper-Bot/1.0",
    "Accept": "application/json"
})

# ================================================================
# TELEGRAM SEND
# ================================================================

def telegram_send(message):

    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN: MISSING")
        return False

    if not CHAT_ID:
        print("TELEGRAM_CHAT_ID: MISSING")
        return False

    url = f"{TELEGRAM_API}/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        response = requests.post(
            url,
            data=payload,
            timeout=20
        )

        print("TELEGRAM STATUS:", response.status_code)

        if response.status_code == 200:

            print("TELEGRAM MESSAGE SENT")

            return True

        print("TELEGRAM ERROR:", response.text)

        return False

    except Exception as e:

        print("TELEGRAM EXCEPTION:", e)

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
            timeout=20
        )

        print(
            "API:",
            response.status_code,
            response.url
        )

        if response.status_code != 200:

            print(
                "API ERROR:",
                response.text[:500]
            )

            return None

        try:

            return response.json()

        except Exception:

            print("JSON ERROR")

            return None

    except Exception as e:

        print("REQUEST ERROR:", e)

        return None


# ================================================================
# NUMBER
# ================================================================

def num(value, default=0.0):

    try:

        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(
            str(value).replace(",", "")
        )

    except Exception:

        return default


# ================================================================
# GET USDT MARKETS
# ================================================================

def get_symbols():

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    if not data:
        return []

    rows = []

    if isinstance(data, dict):

        for key in [
            "res",
            "data",
            "result"
        ]:

            value = data.get(key)

            if isinstance(value, list):

                rows = value

                break

    elif isinstance(data, list):

        rows = data

    symbols = []

    for item in rows:

        try:

            if isinstance(item, str):

                symbol = item

            elif isinstance(item, dict):

                symbol = (
                    item.get("symbol")
                    or item.get("instId")
                    or item.get("pair")
                    or ""
                )

            else:

                continue

            symbol = str(
                symbol
            ).upper().strip()

            if symbol.endswith("-USDT"):

                symbols.append(symbol)

            elif (
                symbol.endswith("USDT")
                and "-" not in symbol
            ):

                base = symbol[:-4]

                if base:

                    symbols.append(
                        base + "-USDT"
                    )

        except Exception:

            continue

    symbols = sorted(
        set(symbols)
    )

    print(
        "USDT MARKETS:",
        len(symbols)
    )

    return symbols


# ================================================================
# GET TICKERS
# ================================================================

def get_tickers():

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    if not data:

        return []

    if isinstance(data, dict):

        for key in [
            "res",
            "data",
            "result"
        ]:

            value = data.get(key)

            if isinstance(value, list):

                return value

    if isinstance(data, list):

        return data

    return []


# ================================================================
# PARSE TICKER
# ================================================================

def parse_ticker(row):

    if not isinstance(row, dict):

        return None

    symbol = (
        row.get("symbol")
        or row.get("instId")
        or row.get("pair")
        or ""
    )

    symbol = str(
        symbol
    ).upper().strip()

    if not symbol.endswith("USDT"):

        return None

    if "-" not in symbol:

        symbol = (
            symbol[:-4]
            + "-USDT"
        )

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
            (last - open_price)
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
# CANDLES
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

    rows = []

    if isinstance(data, dict):

        for key in [
            "res",
            "data",
            "result"
        ]:

            value = data.get(key)

            if isinstance(value, list):

                rows = value

                break

    elif isinstance(data, list):

        rows = data

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

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            (price - result)
            * multiplier
            + result
        )

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
# PRICE FORMAT
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
# ANALYZE MARKET
# ================================================================

def analyze(symbol, ticker):

    candles = get_candles(
        symbol,
        "1h",
        60
    )

    if len(candles) < 30:

        print(
            symbol,
            "NOT ENOUGH CANDLES"
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

        old_price = closes[-6]

        if old_price > 0:

            momentum = (
                (
                    price
                    - old_price
                )
                / old_price
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

    candle_open = candle["open"]
    candle_close = candle["close"]

    bullish = (
        candle_close > candle_open
    )

    bearish = (
        candle_close < candle_open
    )

    # ------------------------------------------------------------
    # SCORE
    # ------------------------------------------------------------

    long_score = 0
    short_score = 0

    # EMA20
    if price > ema20:

        long_score += 15

    elif price < ema20:

        short_score += 15

    # EMA20 / EMA50
    if ema20 > ema50:

        long_score += 15

    elif ema20 < ema50:

        short_score += 15

    # RSI
    if 50 <= rsi14 <= 68:

        long_score += 15

    elif 32 <= rsi14 <= 50:

        short_score += 15

    # Momentum
    if momentum > 0.5:

        long_score += 15

    elif momentum < -0.5:

        short_score += 15

    # Volume
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

    # 24H CHANGE
    daily_change = ticker["change"]

    if daily_change > 2:

        long_score += 10

    elif daily_change < -2:

        short_score += 10

    # ------------------------------------------------------------
    # WHALE PROXY
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
        score = long_score + whale_score

    elif short_score > long_score:

        direction = "SHORT"
        score = short_score + whale_score

    else:

        return None

    if score > 100:

        score = 100

    if score < MIN_SCORE:

        return None

    # ------------------------------------------------------------
    # ATR-LIKE RANGE
    # ------------------------------------------------------------

    ranges = []

    for x in candles[-20:]:

        high = x["high"]
        low = x["low"]

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
            + risk * 2.0
        )

        tp3 = (
            entry
            + risk * 3.0
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
        "rsi": rsi14,
        "ema20": ema20,
        "ema50": ema50,
        "momentum": momentum,
        "volume_ratio": volume_ratio,
        "change24": daily_change,
        "liquidity": liquidity,
        "whale_score": whale_score
    }


# ================================================================
# FORMAT SIGNAL
# ================================================================

def format_signal(signal):

    direction = signal["direction"]

    if direction == "LONG":

        emoji = "🟢"

    else:

        emoji = "🔴"

    if signal["score"] >= STRONG_SCORE:

        strength = "🔥 STRONG SIGNAL"

    else:

        strength = "⚡ SIGNAL"

    return f"""
{emoji} <b>OK-EX IRAN FUTURES</b>

<b>{strength}</b>

<b>{direction}</b>

🪙 Symbol:
<b>{signal["symbol"]}</b>

📊 Score:
<b>{signal["score"]}/100</b>

💰 Entry:
<b>{fmt_price(signal["entry"])}</b>

🛑 Stop Loss:
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
# TELEGRAM COMMANDS
# ================================================================

last_update_id = 0


def check_commands():

    global last_update_id

    if not BOT_TOKEN:

        return

    url = (
        f"{TELEGRAM_API}"
        f"/bot{BOT_TOKEN}"
        f"/getUpdates"
    )

    try:

        response = requests.get(
            url,
            params={
                "timeout": 1,
                "offset": (
                    last_update_id + 1
                )
            },
            timeout=5
        )

        if not response.ok:

            return

        data = response.json()

        for update in data.get(
            "result",
            []
        ):

            last_update_id = (
                update.get(
                    "update_id",
                    last_update_id
                )
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

            if text == "/start":

                telegram_send(
                    "🤖 <b>OK-EX IRAN BOT</b>\n\n"
                    "🟢 Online\n"
                    "📡 OK-EX Connected\n"
                    "🐋 Scanner Active\n"
                    "🟢 Paper Mode ON\n"
                    "🔴 Real Orders OFF\n\n"
                    "/test\n"
                    "/status\n"
                    "/scan\n"
                    "/help"
                )

            elif text == "/test":

                telegram_send(
                    "✅ <b>TELEGRAM TEST OK</b>\n\n"
                    "🟢 Bot is working\n"
                    "🟢 Paper Mode ON\n"
                    "🔴 Real Orders OFF"
                )

            elif text == "/status":

                symbols = get_symbols()

                telegram_send(
                    "🟢 <b>BOT STATUS</b>\n\n"
                    f"📡 OK-EX: CONNECTED\n"
                    f"🪙 USDT Markets: {len(symbols)}\n"
                    "🟢 Paper Mode: ON\n"
                    "🔴 Real Orders: OFF\n"
                    f"⏱ Scan: {SCAN_INTERVAL}s"
                )

            elif text == "/scan":

                telegram_send(
                    "🔎 <b>MANUAL SCAN STARTED</b>"
                )

                scan_market()

            elif text == "/help":

                telegram_send(
                    "🐋 <b>OK-EX SIGNAL BOT</b>\n\n"
                    "/start - Start\n"
                    "/test - Telegram test\n"
                    "/status - Bot status\n"
                    "/scan - Manual scan\n"
                    "/help - Commands"
                )

    except Exception as e:

        print(
            "COMMAND ERROR:",
            e
        )


# ================================================================
# MARKET SCANNER
# ================================================================

last_signals = {}


def scan_market():

    print("")
    print("=" * 70)
    print(
        "SCAN START:",
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )
    print("=" * 70)

    try:

        symbols = get_symbols()

        if not symbols:

            print(
                "NO SYMBOLS FOUND"
            )

            telegram_send(
                "⚠️ OK-EX market list unavailable."
            )

            return

        tickers_raw = get_tickers()

        print(
            "RAW TICKERS:",
            len(tickers_raw)
        )

        ticker_map = {}

        for row in tickers_raw:

            ticker = parse_ticker(row)

            if ticker:

                ticker_map[
                    ticker["symbol"]
                ] = ticker

        print(
            "VALID TICKERS:",
            len(ticker_map)
        )

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

        # بالاترین نقدشوندگی اول
        candidates.sort(
            key=lambda x: x[2],
            reverse=True
        )

        print(
            "MARKETS TO ANALYZE:",
            len(candidates)
        )

        signals = []

        for index, item in enumerate(
            candidates,
            start=1
        ):

            symbol = item[0]
            ticker = item[1]

            print(
                f"[{index}/{len(candidates)}]",
                symbol
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
                        "SIGNAL:",
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

            # جلوگیری از فشار زیاد به API
            time.sleep(0.10)

        signals.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        print(
            "TOTAL SIGNALS:",
            len(signals)
        )

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

        if sent == 0:

            print(
                "NO NEW SIGNAL SENT"
            )

            telegram_send(
                "🔎 <b>SCAN COMPLETE</b>\n\n"
                f"🪙 Markets checked: {len(candidates)}\n"
                f"📊 Signals found: {len(signals)}\n"
                "ℹ️ No new signal above threshold."
            )

        print(
            "SIGNALS SENT:",
            sent
        )

    except Exception as e:

        print(
            "SCAN ERROR:",
            e
        )

        telegram_send(
            "⚠️ <b>SCAN ERROR</b>\n\n"
            f"{str(e)[:500]}"
        )

    print("=" * 70)
    print("SCAN END")
    print("=" * 70)


# ================================================================
# MAIN
# ================================================================

def main():

    print("")
    print("=" * 70)
    print("OK-EX IRAN SIGNAL BOT STARTED")
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

    # ------------------------------------------------------------
    # SECRET CHECK
    # ------------------------------------------------------------

    if not BOT_TOKEN or not CHAT_ID:

        print(
            "ERROR: TELEGRAM SECRETS MISSING"
        )

        return

    # ------------------------------------------------------------
    # START MESSAGE
    # ------------------------------------------------------------

    telegram_send(
        "🟢 <b>OK-EX BOT STARTED</b>\n\n"
        "📡 OK-EX API: ONLINE\n"
        "🐋 Market Scanner: ONLINE\n"
        "🟢 Paper Mode: ON\n"
        "🔴 Real Orders: OFF\n\n"
        "⏱ Scan interval: 5 minutes\n"
        "🪙 USDT markets: ALL\n\n"
        "🤖 Bot is running..."
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

            # Telegram commands
            check_commands()

            now = time.time()

            # Scan every 5 minutes
            if (
                now - last_scan
                >= SCAN_INTERVAL
            ):

                scan_market()

                last_scan = time.time()

            # heartbeat
            print(
                "BOT ALIVE:",
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
# START
# ================================================================

if __name__ == "__main__":

    main()
