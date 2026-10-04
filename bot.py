# ================================================================
# OK-EX IRAN FUTURES SIGNAL BOT
# GITHUB ACTIONS / PAPER SIGNAL ONLY
# LONG / SHORT / WAIT
# ENTRY / SL / TP1 / TP2 / TP3
# ALL USDT MARKETS
# ================================================================

import os
import time
import requests
from datetime import datetime, timezone

# ================================================================
# CONFIG
# ================================================================

OKEX_BASE = "https://sapi.ok-ex.io"
TELEGRAM_API = "https://api.telegram.org"

SCAN_INTERVAL = 300          # 5 minutes
COOLDOWN = 1800              # 30 minutes

MIN_SCORE = 65
STRONG_SCORE = 80

MAX_SIGNALS_PER_SCAN = 3

# فقط سیگنال کاغذی
PAPER_MODE = True
REAL_ORDERS = False

# ================================================================
# TELEGRAM
# ================================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# پشتیبانی از نام‌های جایگزین در صورت وجود Secret قدیمی
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not CHAT_ID:
    CHAT_ID = os.getenv("CHAT_ID", "")


def telegram_send(message):

    if not BOT_TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET NOT FOUND")
        return False

    url = f"{TELEGRAM_API}/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, data=data, timeout=20)

        print("Telegram:", r.status_code)

        if r.ok:
            return True

        print(r.text)

    except Exception as e:
        print("Telegram error:", e)

    return False


# ================================================================
# HTTP
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "OK-EX-Paper-Signal-Bot/1.0",
    "Accept": "application/json"
})


def api_get(path, params=None):

    url = OKEX_BASE + path

    try:

        r = session.get(
            url,
            params=params,
            timeout=20
        )

        print("GET", r.url, r.status_code)

        if r.status_code != 200:
            return None

        return r.json()

    except Exception as e:

        print("API ERROR:", e)

        return None


# ================================================================
# NUMBER
# ================================================================

def num(value, default=0.0):

    try:
        if value is None:
            return default

        if isinstance(value, (int, float)):
            return float(value)

        return float(str(value).replace(",", ""))

    except:
        return default


# ================================================================
# SYMBOL DISCOVERY
# ================================================================

def get_symbols():

    data = api_get(
        "/api/v1/spot/public/pairs"
    )

    if not data:
        return []

    rows = []

    if isinstance(data, dict):

        for key in ["res", "data", "result"]:

            if isinstance(data.get(key), list):
                rows = data[key]
                break

    elif isinstance(data, list):

        rows = data

    symbols = []

    for item in rows:

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

        symbol = str(symbol).upper()

        if symbol.endswith("-USDT"):

            symbols.append(symbol)

        elif symbol.endswith("USDT") and "-" not in symbol:

            base = symbol[:-4]

            if base:
                symbols.append(base + "-USDT")

    return sorted(set(symbols))


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    data = api_get(
        "/api/v1/spot/public/tickers"
    )

    if not data:
        return []

    if isinstance(data, dict):

        for key in ["res", "data", "result"]:

            if isinstance(data.get(key), list):
                return data[key]

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

    symbol = str(symbol).upper()

    if not symbol.endswith("USDT"):
        return None

    if "-" not in symbol and symbol.endswith("USDT"):

        symbol = symbol[:-4] + "-USDT"

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

    if change == 0 and open_price > 0 and last > 0:

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
# CANDLE DATA
# ================================================================

def get_candles(symbol, interval="1h", limit=60):

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

        for key in ["res", "data", "result"]:

            if isinstance(data.get(key), list):
                rows = data[key]
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

                # معمولاً:
                # timestamp, open, high, low, close, volume ...

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

        except:
            continue

    return candles[-limit:]


# ================================================================
# EMA
