import os
import sys
from datetime import datetime

import requests


# ============================================================
# BITPIN TEST BOT
# PAPER MODE ONLY - NO REAL ORDERS
# ============================================================

BITPIN_BASE = "https://api.bitpin.ir"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEOUT = 20

PAPER_MODE = True
REAL_ORDERS = False


# ============================================================
# LOG
# ============================================================

def log(message):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}",
        flush=True
    )


# ============================================================
# BITPIN REQUEST
# ============================================================

def bitpin_get(endpoint, params=None):

    url = BITPIN_BASE + endpoint

    try:

        response = requests.get(
            url,
            params=params,
            timeout=TIMEOUT,
            headers={
                "User-Agent": "Bitpin-Paper-Test-Bot/1.0",
                "Accept": "application/json"
            }
        )

        log(
            f"BITPIN GET {endpoint} -> "
            f"HTTP {response.status_code}"
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        log(f"BITPIN ERROR: {e}")

        return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TELEGRAM_TOKEN:
        log("Telegram token is missing.")
        return False

    if not TELEGRAM_CHAT_ID:
        log("Telegram chat ID is missing.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=TIMEOUT
        )

        log(
            f"TELEGRAM -> HTTP "
            f"{response.status_code}"
        )

        if response.ok:

            log("Telegram test successful.")
            return True

        log(response.text[:500])

        return False

    except Exception as e:

        log(f"Telegram ERROR: {e}")

        return False


# ============================================================
# GET MARKETS
# ============================================================

def get_markets():

    data = bitpin_get(
        "/api/v1/mkt/markets/"
    )

    if not data:

        return []

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        for key in [
            "results",
            "data",
            "markets"
        ]:

            if isinstance(data.get(key), list):

                return data[key]

    log(
        "Unknown markets response:"
        + str(data)[:1000]
    )

    return []


# ============================================================
# GET TICKERS
# ============================================================

def get_tickers():

    data = bitpin_get(
        "/api/v1/mkt/tickers/"
    )

    if not data:

        return []

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        for key in [
            "results",
            "data",
            "tickers"
        ]:

            if isinstance(data.get(key), list):

                return data[key]

    log(
        "Unknown ticker response:"
        + str(data)[:1000]
    )

    return []


# ============================================================
# FIND SYMBOL
# ============================================================

def get_symbol(item):

    if not isinstance(item, dict):

        return ""

    for key in [
        "symbol",
        "market",
        "pair",
        "code"
    ]:

        value = item.get(key)

        if value:

            return str(value).upper()

    return ""


# ============================================================
# FIND PRICE
# ============================================================

def get_price(item):

    if not isinstance(item, dict):

        return None

    for key in [
        "last",
        "last_price",
        "lastPrice",
        "price",
        "close"
    ]:

        value = item.get(key)

        if value not in [None, ""]:

            try:

                return float(value)

            except Exception:

                pass

    return None


# ============================================================
# MAIN TEST
# ============================================================

def main():

    log("")
    log("======================================")
    log("BITPIN API TEST")
    log("======================================")

    log(
        f"PAPER_MODE = {PAPER_MODE}"
    )

    log(
        f"REAL_ORDERS = {REAL_ORDERS}"
    )

    if REAL_ORDERS:

        log(
            "FATAL: REAL_ORDERS must be False."
        )

        return 1

    # --------------------------------------------------------
    # MARKET TEST
    # --------------------------------------------------------

    log("")
    log("Testing Bitpin markets API...")

    markets = get_markets()

    if not markets:

        log(
            "❌ MARKET API TEST FAILED"
        )

        return 1

    log(
        f"✅ Markets received: {len(markets)}"
    )

    # --------------------------------------------------------
    # PRINT FIRST MARKETS
    # --------------------------------------------------------

    log("")
    log("First markets:")

    for item in markets[:10]:

        symbol = get_symbol(item)

        if symbol:

            log(
                f"  {symbol}"
            )

    # --------------------------------------------------------
    # TICKER TEST
    # --------------------------------------------------------

    log("")
    log("Testing Bitpin ticker API...")

    tickers = get_tickers()

    if not tickers:

        log(
            "❌ TICKER API TEST FAILED"
        )

        return 1

    log(
        f"✅ Tickers received: {len(tickers)}"
    )

    # --------------------------------------------------------
    # PRINT SAMPLE PRICES
    # --------------------------------------------------------

    log("")
    log("Sample ticker prices:")

    count = 0

    for item in tickers:

        symbol = get_symbol(item)

        price = get_price(item)

        if symbol and price is not None:

            log(
                f"  {symbol} = {price}"
            )

            count += 1

        if count >= 10:

            break

    # --------------------------------------------------------
    # TELEGRAM TEST
    # --------------------------------------------------------

    log("")
    log("Testing Telegram...")

    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:

        telegram_send(
            "🟢 BITPIN API TEST\n\n"
            "Bitpin Markets API: ONLINE\n"
            "Bitpin Ticker API: ONLINE\n"
            "Telegram: TESTED\n"
            "Mode: PAPER ONLY\n"
            "Real Orders: OFF"
        )

    else:

        log(
            "Telegram secrets are not configured."
        )

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    log("")
    log("======================================")
    log("✅ BITPIN TEST COMPLETED")
    log("======================================")

    return 0


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        sys.exit(
            main()
        )

    except Exception as e:

        log("")
        log("❌ UNEXPECTED ERROR")
        log(
            f"{type(e).__name__}: {e}"
        )

        sys.exit(1)
