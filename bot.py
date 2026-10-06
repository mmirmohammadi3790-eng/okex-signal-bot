import os
import sys
import traceback
from datetime import datetime

import requests


# ============================================================
# OK-EX PAPER SIGNAL BOT
# NO REAL ORDERS
# ============================================================

OKEX_BASE = "https://sapi.ok-ex.io"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEOUT = 20

PAPER_MODE = True
REAL_ORDERS = False

MAX_SYMBOLS = 30


# ============================================================
# LOG
# ============================================================

def log(message):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}",
        flush=True
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if not TELEGRAM_TOKEN:
        log("WARNING: TELEGRAM_BOT_TOKEN is missing.")
        return False

    if not TELEGRAM_CHAT_ID:
        log("WARNING: TELEGRAM_CHAT_ID is missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=TIMEOUT
        )

        log(f"Telegram HTTP: {response.status_code}")

        if response.ok:
            log("Telegram message sent successfully.")
            return True

        log(response.text[:500])
        return False

    except Exception as e:

        log(f"Telegram error: {e}")
        return False


# ============================================================
# OK-EX API
# ============================================================

def okex_get(endpoint, params=None):

    url = OKEX_BASE + endpoint

    try:

        response = requests.get(
            url,
            params=params,
            timeout=TIMEOUT,
            headers={
                "User-Agent": "OKEX-Paper-Signal-Bot/1.0"
            }
        )

        log(
            f"OK-EX GET {endpoint} -> "
            f"HTTP {response.status_code}"
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        log(f"OK-EX API ERROR: {e}")

        return None


# ============================================================
# GET MARKETS
# ============================================================

def get_usdt_markets():

    data = okex_get(
        "/api/v1/spot/public/pairs"
    )

    if not data:
        return []

    result = data.get("res", data)

    if isinstance(result, dict):

        for key in [
            "data",
            "list",
            "pairs",
            "result"
        ]:

            if isinstance(result.get(key), list):
                result = result[key]
                break

    if not isinstance(result, list):

        log(
            "Unexpected pairs response: "
            + str(data)[:500]
        )

        return []

    markets = []

    for item in result:

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

        symbol = str(symbol).upper().strip()

        if symbol.endswith("-USDT"):

            markets.append(symbol)

    markets = sorted(set(markets))

    log(
        f"USDT markets found: {len(markets)}"
    )

    return markets


# ============================================================
# GET TICKERS
# ============================================================

def get_tickers():

    data = okex_get(
        "/api/v1/spot/public/tickers"
    )

    if not data:
        return []

    result = data.get("res", data)

    if isinstance(result, dict):

        for key in [
            "data",
            "list",
            "tickers",
            "result"
        ]:

            if isinstance(result.get(key), list):

                result = result[key]
                break

    if not isinstance(result, list):

        log(
            "Unexpected ticker response: "
            + str(data)[:500]
        )

        return []

    log(
        f"Tickers received: {len(result)}"
    )

    return result


# ============================================================
# TICKER HELPERS
# ============================================================

def ticker_symbol(item):

    if not isinstance(item, dict):
        return ""

    return str(
        item.get("symbol")
        or item.get("instId")
        or item.get("pair")
        or ""
    ).upper().strip()


def ticker_price(item):

    if not isinstance(item, dict):
        return None

    for key in [
        "last",
        "lastPrice",
        "close",
        "price",
        "lastPr"
    ]:

        value = item.get(key)

        if value not in [None, ""]:

            try:
                return float(value)

            except Exception:
                pass

    return None


def ticker_volume(item):

    if not isinstance(item, dict):
        return 0

    for key in [
        "volume",
        "vol",
        "baseVolume",
        "quoteVolume",
        "turnover"
    ]:

        value = item.get(key)

        if value not in [None, ""]:

            try:
                return float(value)

            except Exception:
                pass

    return 0


# ============================================================
# PAPER SIGNAL
# ============================================================

def create_paper_signal(
    symbol,
    price,
    volume
):

    if price is None:
        return None

    if price <= 0:
        return None

    # --------------------------------------------------------
    # IMPORTANT
    # This first version does NOT fabricate RSI/EMA/4H data.
    # Therefore default direction is WAIT.
    # --------------------------------------------------------

    score = 0

    direction = "WAIT"

    if volume > 0:
        score += 10

    return {
        "symbol": symbol,
        "price": price,
        "volume": volume,
        "score": score,
        "direction": direction
    }


# ============================================================
# MARKET SCAN
# ============================================================

def scan():

    log("")
    log("========== MARKET SCAN ==========")

    markets = get_usdt_markets()

    if not markets:

        log("ERROR: No USDT markets found.")

        return []

    tickers = get_tickers()

    if not tickers:

        log("ERROR: No tickers received.")

        return []

    ticker_map = {}

    for item in tickers:

        symbol = ticker_symbol(item)

        if symbol:

            ticker_map[symbol] = item

    results = []

    for symbol in markets[:MAX_SYMBOLS]:

        item = ticker_map.get(symbol)

        if not item:
            continue

        price = ticker_price(item)

        volume = ticker_volume(item)

        signal = create_paper_signal(
            symbol,
            price,
            volume
        )

        if signal:

            results.append(signal)

    log(
        f"Markets successfully scanned: "
        f"{len(results)}"
    )

    return results


# ============================================================
# TELEGRAM REPORT
# ============================================================

def send_report(results):

    if not results:

        telegram_send(
            "⚠️ OK-EX PAPER SCAN\n\n"
            "No valid market data received."
        )

        return

    results = sorted(
        results,
        key=lambda x: x["score"],
        reverse=True
    )

    top = results[:10]

    lines = []

    lines.append("📊 OK-EX PAPER SCAN")
    lines.append("")
    lines.append("🟢 API: ONLINE")
    lines.append("🟢 MODE: PAPER ONLY")
    lines.append("🔴 REAL ORDERS: OFF")
    lines.append("")

    for item in top:

        lines.append(
            f"⏸ {item['symbol']} | "
            f"{item['direction']} | "
            f"Price: {item['price']} | "
            f"Score: {item['score']}"
        )

    lines.append("")
    lines.append(
        f"Markets scanned: {len(results)}"
    )

    telegram_send(
        "\n".join(lines)
    )


# ============================================================
# MAIN
# ============================================================

def main():

    log("")
    log("==========================================")
    log("OK-EX FUTURES SIGNAL BOT")
    log("==========================================")

    log(
        f"PAPER_MODE = {PAPER_MODE}"
    )

    log(
        f"REAL_ORDERS = {REAL_ORDERS}"
    )

    # Safety lock

    if REAL_ORDERS:

        log(
            "FATAL ERROR: "
            "REAL_ORDERS must be False."
        )

        return 1

    # --------------------------------------------------------
    # Telegram configuration
    # --------------------------------------------------------

    if TELEGRAM_TOKEN:

        log(
            "TELEGRAM_BOT_TOKEN: configured"
        )

    else:

        log(
            "TELEGRAM_BOT_TOKEN: MISSING"
        )

    if TELEGRAM_CHAT_ID:

        log(
            "TELEGRAM_CHAT_ID: configured"
        )

    else:

        log(
            "TELEGRAM_CHAT_ID: MISSING"
        )

    # --------------------------------------------------------
    # Test OK-EX
    # --------------------------------------------------------

    markets = get_usdt_markets()

    if not markets:

        log("")
        log(
            "❌ OK-EX CONNECTION TEST FAILED"
        )

        return 1

    log("")
    log(
        "✅ OK-EX CONNECTION TEST PASSED"
    )

    log(
        f"✅ USDT markets: {len(markets)}"
    )

    # --------------------------------------------------------
    # Telegram test
    # --------------------------------------------------------

    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:

        telegram_send(
            "🟢 OK-EX BOT TEST\n\n"
            "OK-EX API: ONLINE\n"
            "Telegram: ONLINE\n"
            "Mode: PAPER ONLY\n"
            "Real orders: OFF"
        )

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    results = scan()

    # --------------------------------------------------------
    # Telegram report
    # --------------------------------------------------------

    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:

        send_report(results)

    log("")
    log(
        "=========================================="
    )

    log(
        "✅ BOT FINISHED SUCCESSFULLY"
    )

    log(
        "=========================================="
    )

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
        log(
            "❌ UNEXPECTED ERROR"
        )

        log(
            f"{type(e).__name__}: {e}"
        )

        traceback.print_exc()

        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:

            telegram_send(
                "🔴 OK-EX BOT ERROR\n\n"
                f"{type(e).__name__}: {e}"
            )

        sys.exit(1)
