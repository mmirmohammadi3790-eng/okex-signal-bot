# ================================================================
# 🐋 OK-EX IRAN — V5.1 CANDLE DIAGNOSTIC
# ================================================================
# PAPER SIGNAL ONLY
# NO REAL ORDERS
#
# هدف این نسخه:
# پیدا کردن علت:
# Candle OK: 0
# Total candle rows: 0
#
# فقط 5 بازار تست می‌شوند.
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

REQUEST_TIMEOUT = 20

CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100
CANDLE_HOURS = 120

TEST_MARKETS = 5

# ================================================================
# TELEGRAM
# ================================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

# ================================================================
# SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "OKEX-Iran-PaperBot/5.1",
    "Accept": "application/json",
})


# ================================================================
# TELEGRAM SEND
# ================================================================

def telegram_send(text):

    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN is missing")
        return False

    if not CHAT_ID:
        print("❌ CHAT_ID is missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:

        response = session.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        print(
            "Telegram:",
            response.status_code
        )

        if response.status_code == 200:
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
        .strip()
    )


# ================================================================
# RAW GET
# ================================================================

def raw_get(path, params=None):

    url = OKEX_BASE + path

    print("\n--------------------------------")
    print("GET:", url)
    print("PARAMS:", params)

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            "HTTP:",
            response.status_code
        )

        print(
            "URL:",
            response.url
        )

        print(
            "RAW:",
            response.text[:3000]
        )

        return response

    except Exception as e:

        print(
            "REQUEST EXCEPTION:",
            repr(e)
        )

        return None


# ================================================================
# JSON GET
# ================================================================

def get_json(path, params=None):

    response = raw_get(
        path,
        params,
    )

    if response is None:
        return None

    if response.status_code != 200:
        return None

    try:

        return response.json()

    except Exception as e:

        print(
            "JSON ERROR:",
            repr(e)
        )

        return None


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    data = get_json(
        "/api/v1/spot/public/tickers"
    )

    if not data:
        print("❌ No ticker JSON")
        return {}

    print(
        "\nTICKER JSON KEYS:",
        list(data.keys())
        if isinstance(data, dict)
        else type(data)
    )

    rows = None

    if isinstance(data, dict):

        rows = data.get("res")

        if rows is None:
            rows = data.get("data")

        if rows is None:
            rows = data.get("result")

    if not isinstance(rows, list):

        print(
            "❌ Ticker rows is not list:",
            type(rows)
        )

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

        except Exception:

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

        except Exception:

            quote_volume = 0

        try:

            change = float(
                item.get("priceChangePercent")
                or item.get("changePercent")
                or item.get("change")
                or 0
            )

        except Exception:

            change = 0

        result[symbol] = {
            "price": price,
            "quote_volume": quote_volume,
            "change": change,
        }

    print(
        "\n🟢 Parsed USDT tickers:",
        len(result)
    )

    return result


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    data = get_json(
        "/api/v1/spot/public/pairs"
    )

    if not data:

        print(
            "❌ No pair JSON"
        )

        return []

    print(
        "\nPAIR JSON KEYS:",
        list(data.keys())
        if isinstance(data, dict)
        else type(data)
    )

    rows = None

    if isinstance(data, dict):

        rows = data.get("res")

        if rows is None:
            rows = data.get("data")

        if rows is None:
            rows = data.get("result")

    if not isinstance(rows, list):

        print(
            "❌ Pair rows is not list:",
            type(rows)
        )

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

        if not symbol:
            continue

        symbol = normalize_symbol(symbol)

        if symbol.endswith("USDT"):
            symbols.append(symbol)

    symbols = list(
        dict.fromkeys(symbols)
    )

    print(
        "🟢 Parsed USDT pairs:",
        len(symbols)
    )

    return symbols


# ================================================================
# MARKET DISCOVERY
# ================================================================

def discover_markets(tickers, pairs):

    ticker_symbols = set(
        tickers.keys()
    )

    pair_symbols = set(
        pairs
    )

    print(
        "\nTicker symbols:",
        len(ticker_symbols)
    )

    print(
        "Pair symbols:",
        len(pair_symbols)
    )

    if ticker_symbols and pair_symbols:

        intersection = (
            ticker_symbols &
            pair_symbols
        )

        print(
            "Intersection:",
            len(intersection)
        )

        if intersection:

            markets = sorted(
                intersection
            )

        else:

            markets = sorted(
                ticker_symbols
            )

    elif ticker_symbols:

        markets = sorted(
            ticker_symbols
        )

    else:

        markets = sorted(
            pair_symbols
        )

    markets = [
        x for x in markets
        if x.endswith("USDT")
    ]

    print(
        "Final USDT markets:",
        len(markets)
    )

    return markets


# ================================================================
# CANDLE EXTRACTION
# ================================================================

def extract_candle_rows(data):

    if not data:

        print(
            "❌ Empty candle response"
        )

        return []

    print(
        "\nCANDLE JSON TYPE:",
        type(data)
    )

    if isinstance(data, dict):

        print(
            "CANDLE JSON KEYS:",
            list(data.keys())
        )

        rows = data.get("res")

        if rows is None:
            rows = data.get("data")

        if rows is None:
            rows = data.get("result")

    elif isinstance(data, list):

        rows = data

    else:

        rows = None

    if not isinstance(rows, list):

        print(
            "❌ Candle rows is not list:"
        )

        print(
            type(rows)
        )

        return []

    print(
        "Raw candle rows:",
        len(rows)
    )

    return rows


# ================================================================
# PARSE CANDLES
# ================================================================

def parse_candles(rows):

    candles = []

    for index, row in enumerate(rows):

        try:

            # ----------------------------------------------------
            # DICT FORMAT
            # ----------------------------------------------------

            if isinstance(row, dict):

                timestamp = (
                    row.get("timestamp")
                    or row.get("time")
                    or row.get("ts")
                )

                open_price = row.get("open")
                high = row.get("high")
                low = row.get("low")
                close = row.get("close")

                volume = (
                    row.get("volume")
                    or row.get("vol")
                    or 0
                )

            # ----------------------------------------------------
            # LIST FORMAT
            # ----------------------------------------------------

            elif isinstance(row, list):

                if len(row) < 5:

                    print(
                        "⚠️ Short candle row:",
                        index,
                        row
                    )

                    continue

                timestamp = row[0]
                open_price = row[1]
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

            if (
                timestamp is None
                or open_price is None
                or high is None
                or low is None
                or close is None
            ):

                print(
                    "⚠️ Missing candle field:",
                    index,
                    row
                )

                continue

            candle = {

                "time": float(timestamp),

                "open": float(open_price),

                "high": float(high),

                "low": float(low),

                "close": float(close),

                "volume": float(volume),

            }

            candles.append(candle)

        except Exception as e:

            print(
                "⚠️ Candle parse error:",
                index,
                repr(e)
            )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ================================================================
# GET CANDLES
# ================================================================

def get_candles(symbol):

    api_symbol = normalize_symbol(
        symbol
    )

    end_time = int(
        time.time() * 1000
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

        "symbol": api_symbol,

        "interval": CANDLE_INTERVAL,

        "startTime": start_time,

        "endTime": end_time,

        "limit": CANDLE_LIMIT,

    }

    print(
        "\n================================"
    )

    print(
        "CANDLE TEST:",
        symbol
    )

    print(
        "API SYMBOL:",
        api_symbol
    )

    print(
        "START:",
        start_time
    )

    print(
        "END:",
        end_time
    )

    print(
        "INTERVAL:",
        CANDLE_INTERVAL
    )

    print(
        "LIMIT:",
        CANDLE_LIMIT
    )

    response = raw_get(
        "/api/v1/spot/public/candles",
        params,
    )

    if response is None:

        return []

    if response.status_code != 200:

        print(
            "❌ Candle HTTP error:",
            response.status_code
        )

        return []

    try:

        data = response.json()

    except Exception as e:

        print(
            "❌ Candle JSON error:",
            repr(e)
        )

        return []

    rows = extract_candle_rows(
        data
    )

    candles = parse_candles(
        rows
    )

    print(
        "🕯 Parsed candles:",
        len(candles)
    )

    if candles:

        print(
            "FIRST:",
            candles[0]
        )

        print(
            "LAST:",
            candles[-1]
        )

    return candles


# ================================================================
# SEND CANDLE RESULT
# ================================================================

def send_candle_result(
    symbol,
    ticker,
    candles
):

    if candles:

        last = candles[-1]

        message = f"""
🟢 <b>CANDLE TEST PASSED</b>

🪙 Symbol:
<b>{symbol}</b>

💰 Ticker:
<b>{ticker["price"]}</b>

🕯 Candle rows:
<b>{len(candles)}</b>

📌 Last candle close:
<b>{last["close"]}</b>

📊 Last candle volume:
<b>{last["volume"]}</b>

⏱ Candle:
<b>{CANDLE_INTERVAL}</b>

📡 API:
<b>ONLINE</b>
"""

    else:

        message = f"""
🔴 <b>CANDLE TEST FAILED</b>

🪙 Symbol:
<b>{symbol}</b>

💰 Ticker:
<b>{ticker["price"]}</b>

🕯 Candle rows:
<b>0</b>

❌ No valid candle rows parsed.

⚠️ Raw API response was printed
in GitHub Actions log.
"""

    telegram_send(
        message
    )


# ================================================================
# DIAGNOSTIC SCAN
# ================================================================

def scan():

    print(
        "\n\n"
        "################################################"
    )

    print(
        "🔎 STARTING CANDLE DIAGNOSTIC"
    )

    print(
        datetime.now()
    )

    print(
        "################################################"
    )

    # ------------------------------------------------------------
    # TICKERS
    # ------------------------------------------------------------

    tickers = get_tickers()

    # ------------------------------------------------------------
    # PAIRS
    # ------------------------------------------------------------

    pairs = get_pairs()

    # ------------------------------------------------------------
    # DISCOVER
    # ------------------------------------------------------------

    markets = discover_markets(
        tickers,
        pairs
    )

    print(
        "\n📊 TOTAL MARKETS:",
        len(markets)
    )

    if not markets:

        telegram_send(
            """
🔴 <b>MARKET DISCOVERY FAILED</b>

No USDT markets found.
"""
        )

        return

    # ------------------------------------------------------------
    # ONLY FIRST 5
    # ------------------------------------------------------------

    test_markets = markets[
        :TEST_MARKETS
    ]

    print(
        "\n🧪 TEST MARKETS:"
    )

    for x in test_markets:

        print(
            "•",
            x
        )

    telegram_send(
        "🧪 <b>OK-EX CANDLE DIAGNOSTIC</b>\n\n"
        f"📊 Markets found: <b>{len(markets)}</b>\n"
        f"🧪 Markets being tested: <b>{len(test_markets)}</b>\n\n"
        + "\n".join(
            f"• {x}"
            for x in test_markets
        )
        +
        "\n\n⏳ Testing real candles..."
    )

    # ------------------------------------------------------------
    # COUNTERS
    # ------------------------------------------------------------

    candle_ok = 0
    candle_failed = 0
    total_rows = 0

    # ------------------------------------------------------------
    # TEST MARKETS
    # ------------------------------------------------------------

    for symbol in test_markets:

        print(
            "\n\n"
            "================================================"
        )

        print(
            "🧪 TESTING:",
            symbol
        )

        print(
            "================================================"
        )

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            print(
                "❌ TICKER NOT FOUND"
            )

            candle_failed += 1

            continue

        print(
            "Ticker:",
            ticker
        )

        try:

            candles = get_candles(
                symbol
            )

        except Exception as e:

            print(
                "❌ EXCEPTION:",
                repr(e)
            )

            candles = []

        if candles:

            candle_ok += 1

            total_rows += len(
                candles
            )

        else:

            candle_failed += 1

        send_candle_result(
            symbol,
            ticker,
            candles
        )

        # --------------------------------------------------------
        # RATE LIMIT PROTECTION
        # --------------------------------------------------------

        print(
            "\n⏳ Waiting 2 seconds..."
        )

        time.sleep(2)

    # ============================================================
    # FINAL RESULT
    # ============================================================

    if candle_ok > 0:

        average = (
            total_rows /
            candle_ok
        )

    else:

        average = 0

    print(
        "\n\n"
        "################################################"
    )

    print(
        "🔎 DIAGNOSTIC COMPLETE"
    )

    print(
        "################################################"
    )

    print(
        "📊 Markets:",
        len(markets)
    )

    print(
        "🧪 Tested:",
        len(test_markets)
    )

    print(
        "🕯 Candle OK:",
        candle_ok
    )

    print(
        "❌ Candle Failed:",
        candle_failed
    )

    print(
        "📚 Total candle rows:",
        total_rows
    )

    print(
        "📐 Average:",
        round(average, 2)
    )

    print(
        "################################################"
    )

    result_message = f"""
🔎 <b>SCAN COMPLETE — DIAGNOSTIC</b>

📊 Markets: <b>{len(markets)}</b>

🧪 Tested: <b>{len(test_markets)}</b>

🕯 Candle OK: <b>{candle_ok}</b>
❌ Candle Failed: <b>{candle_failed}</b>

📚 Total candle rows:
<b>{total_rows}</b>

📐 Avg candles/OK market:
<b>{average:.1f}</b>

🧠 Analysis:
<b>NOT RUN</b>

🎯 Candidates:
<b>NOT RUN</b>

📨 Signals sent:
<b>NOT RUN</b>

🟢 Paper Mode: ON
🔴 Real Orders: OFF

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    telegram_send(
        result_message
    )

    # ============================================================
    # NEXT STEP MESSAGE
    # ============================================================

    if candle_ok == 0:

        telegram_send(
            """
🔴 <b>CANDLE PROBLEM CONFIRMED</b>

هیچ کندلی از ۵ بازار تست‌شده
دریافت/Parse نشد.

⚠️ فعلاً اسکن ۲۲۷ بازار اجرا نمی‌شود.

لگ GitHub Actions شامل
HTTP Status + URL + Parameters
+ Raw API Response است.
"""
        )

    else:

        telegram_send(
            """
🟢 <b>CANDLE API WORKS</b>

حداقل یک بازار کندل واقعی داد.

مرحله بعد:
فعال‌کردن اسکن کامل بازارها
و RSI / EMA / Momentum / Volume.
"""
        )


# ================================================================
# STARTUP
# ================================================================

def startup():

    message = """
🟢 <b>OK-EX IRAN BOT — DIAGNOSTIC MODE</b>

📡 OK-EX API:
<b>ONLINE</b>

🕯 Real Candle:
<b>TEST MODE</b>

🧪 Markets per test:
<b>5</b>

🟢 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

⚠️ فعلاً فقط مشکل Candle بررسی می‌شود.
"""

    print(message)

    telegram_send(
        message
    )


# ================================================================
# MAIN
# ================================================================

def main():

    startup()

    try:

        scan()

    except Exception as e:

        print(
            "\n\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        print(
            "MAIN ERROR:"
        )

        print(
            repr(e)
        )

        print(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        telegram_send(
            f"""
🔴 <b>BOT ERROR</b>

<code>{str(e)[:1500]}</code>
"""
        )

    print(
        "\n🛑 Diagnostic finished."
    )


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":

    main()
