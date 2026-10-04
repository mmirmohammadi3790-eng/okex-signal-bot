# ================================================================
# 🐋 ETH WHALE — OK-EX IRAN
# V12 — API DEBUG + PAPER SIGNAL
# ================================================================

import os
import time
import requests
from datetime import datetime

# ================================================================
# CONFIG
# ================================================================

BASE_URL = "https://sapi.ok-ex.io"

PAPER_MODE = True
REAL_ORDERS = False

CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100

MAX_MARKETS = 227
MAX_SIGNALS = 3

MIN_SCORE = 70
STRONG_SCORE = 80

MIN_VOLUME_RATIO = 1.20
STRONG_VOLUME_RATIO = 2.00
MIN_EDGE = 15

REQUEST_TIMEOUT = 20

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

SESSION = requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


# ================================================================
# GLOBAL DEBUG
# ================================================================

STATS = {
    "ticker_ok": 0,
    "ticker_failed": 0,
    "pairs_ok": 0,
    "pairs_failed": 0,
    "candle_ok": 0,
    "candle_failed": 0,
    "candle_rows": 0,
    "analysis_passed": 0,
    "signals_found": 0,
    "signals_sent": 0,
}


# ================================================================
# HELPERS
# ================================================================

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def get_json(path, params=None):
    url = BASE_URL + path

    try:
        r = SESSION.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code != 200:
            print(f"[HTTP ERROR] {path} -> {r.status_code}")
            print(r.text[:500])
            return None

        try:
            return r.json()

        except Exception:
            print(f"[JSON ERROR] {path}")
            print(r.text[:500])
            return None

    except Exception as e:
        print(f"[REQUEST ERROR] {path}: {e}")
        return None


# ================================================================
# TELEGRAM
# ================================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[TELEGRAM] Missing token or chat ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:

        r = SESSION.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code == 200:
            STATS["signals_sent"] += 1
            return True

        print("[TELEGRAM ERROR]", r.status_code)
        print(r.text[:500])
        return False

    except Exception as e:
        print("[TELEGRAM REQUEST ERROR]", e)
        return False


# ================================================================
# PAIRS
# ================================================================

def get_pairs():

    print("\n[1] Loading OK-EX pairs...")

    data = get_json(
        "/api/v1/spot/public/pairs"
    )

    if not data:
        STATS["pairs_failed"] += 1
        return []

    print("[PAIR RAW]", str(data)[:1000])

    result = None

    if isinstance(data, dict):
        result = data.get("res")

        if result is None:
            result = data.get("data")

        if result is None:
            result = data.get("result")

    elif isinstance(data, list):
        result = data

    if not isinstance(result, list):
        print("[PAIR ERROR] Unknown response format")
        STATS["pairs_failed"] += 1
        return []

    symbols = []

    for item in result:

        symbol = None

        if isinstance(item, str):
            symbol = item

        elif isinstance(item, dict):

            symbol = (
                item.get("symbol")
                or item.get("pair")
                or item.get("market")
                or item.get("instId")
            )

        if not symbol:
            continue

        symbol = str(symbol).upper()

        if "USDT" not in symbol:
            continue

        symbol = symbol.replace("_", "-").replace("/", "-")

        if symbol.endswith("USDT") and "-" not in symbol:
            symbol = symbol[:-4] + "-USDT"

        if symbol not in symbols:
            symbols.append(symbol)

    symbols = symbols[:MAX_MARKETS]

    STATS["pairs_ok"] = len(symbols)

    print(f"[PAIR OK] {len(symbols)} USDT markets")

    return symbols


# ================================================================
# TICKERS
# ================================================================

def get_tickers():

    print("\n[2] Loading tickers...")

    data = get_json(
        "/api/v1/spot/public/tickers"
    )

    if not data:
        STATS["ticker_failed"] += 1
        return {}

    print("[TICKER RAW]", str(data)[:1200])

    result = None

    if isinstance(data, dict):

        result = data.get("res")

        if result is None:
            result = data.get("data")

        if result is None:
            result = data.get("result")

    elif isinstance(data, list):
        result = data

    if not isinstance(result, list):
        print("[TICKER ERROR] Unknown response format")
        STATS["ticker_failed"] += 1
        return {}

    tickers = {}

    for item in result:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("pair")
            or item.get("market")
            or item.get("instId")
        )

        if not symbol:
            continue

        symbol = str(symbol).upper()
        symbol = symbol.replace("_", "-").replace("/", "-")

        if symbol.endswith("USDT") and "-" not in symbol:
            symbol = symbol[:-4] + "-USDT"

        if "-USDT" not in symbol:
            continue

        tickers[symbol] = item

    STATS["ticker_ok"] = len(tickers)

    print(f"[TICKER OK] {len(tickers)} USDT tickers")

    return tickers


# ================================================================
# PRICE FROM TICKER
# ================================================================

def ticker_price(item):

    if not isinstance(item, dict):
        return None

    fields = [
        "last",
        "lastPrice",
        "price",
        "close",
        "c",
        "last_price"
    ]

    for field in fields:

        value = item.get(field)

        if value is None:
            continue

        try:
            price = float(value)

            if price > 0:
                return price

        except Exception:
            pass

    return None


# ================================================================
# CANDLES
# ================================================================

def get_candles(symbol):

    params = {
        "symbol": symbol,
        "interval": CANDLE_INTERVAL,
        "limit": CANDLE_LIMIT
    }

    data = get_json(
        "/api/v1/spot/public/candles",
        params=params
    )

    if not data:
        return []

    result = None

    if isinstance(data, dict):

        result = data.get("res")

        if result is None:
            result = data.get("data")

        if result is None:
            result = data.get("result")

    elif isinstance(data, list):
        result = data

    if not isinstance(result, list):
        print(f"[CANDLE FORMAT ERROR] {symbol}")
        return []

    candles = []

    for row in result:

        try:

            if isinstance(row, list):

                if len(row) >= 5:

                    timestamp = float(row[0])
                    open_price = float(row[1])
                    high = float(row[2])
                    low = float(row[3])
                    close = float(row[4])

                    volume = 0.0

                    if len(row) >= 6:
                        try:
                            volume = float(row[5])
                        except Exception:
                            volume = 0.0

                    candles.append({
                        "time": timestamp,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume
                    })

            elif isinstance(row, dict):

                o = row.get("open") or row.get("o")
                h = row.get("high") or row.get("h")
                l = row.get("low") or row.get("l")
                c = row.get("close") or row.get("c")
                v = row.get("volume") or row.get("v") or 0

                if o is not None and h is not None and l is not None and c is not None:

                    candles.append({
                        "time": row.get("time") or row.get("timestamp") or 0,
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(c),
                        "volume": float(v)
                    })

        except Exception:
            continue

    return candles


# ================================================================
# INDICATORS
# ================================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (price - result) * multiplier + result

    return result


def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

        trs.append(tr)

    return sum(trs[-period:]) / period


# ================================================================
# ANALYSIS
# ================================================================

def analyze(symbol, candles):

    if len(candles) < 50:
        return None

    closes = [x["close"] for x in candles]
    volumes = [x["volume"] for x in candles]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi14 = rsi(closes, 14)
    atr14 = atr(candles, 14)

    if not ema20 or not ema50 or not rsi14 or not atr14:
        return None

    recent_volume = volumes[-1]

    previous_volumes = volumes[-21:-1]

    avg_volume = (
        sum(previous_volumes) / len(previous_volumes)
        if previous_volumes else 0
    )

    volume_ratio = (
        recent_volume / avg_volume
        if avg_volume > 0 else 0
    )

    momentum = 0

    if len(closes) >= 11:

        old_price = closes[-11]

        if old_price > 0:
            momentum = ((price - old_price) / old_price) * 100

    trend = 0

    if len(closes) >= 11:

        trend_old = closes[-11]

        if price > trend_old:
            trend = 1

        elif price < trend_old:
            trend = -1

    score_long = 0
    score_short = 0

    # EMA
    if price > ema20:
        score_long += 15

    if ema20 > ema50:
        score_long += 15

    if price < ema20:
        score_short += 15

    if ema20 < ema50:
        score_short += 15

    # RSI
    if 50 <= rsi14 <= 70:
        score_long += 15

    if 30 <= rsi14 <= 50:
        score_short += 15

    # Momentum
    if momentum > 1:
        score_long += 15

    if momentum < -1:
        score_short += 15

    # Trend
    if trend > 0:
        score_long += 10

    if trend < 0:
        score_short += 10

    # Volume
    if volume_ratio >= MIN_VOLUME_RATIO:

        if score_long > score_short:
            score_long += 15

        elif score_short > score_long:
            score_short += 15

    # Price action
    recent_high = max(closes[-10:-1])
    recent_low = min(closes[-10:-1])

    if price > recent_high:
        score_long += 15

    if price < recent_low:
        score_short += 15

    direction = None
    score = 0

    if score_long >= score_short:
        direction = "LONG"
        score = score_long
    else:
        direction = "SHORT"
        score = score_short

    edge = abs(score_long - score_short)

    if score < MIN_SCORE:
        return None

    if edge < MIN_EDGE:
        return None

    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    STATS["analysis_passed"] += 1

    risk = max(atr14 * 1.5, price * 0.008)

    if direction == "LONG":

        entry = price

        sl = entry - risk

        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3

    else:

        entry = price

        sl = entry + risk

        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "edge": edge,
        "price": price,
        "rsi": rsi14,
        "volume_ratio": volume_ratio,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3
    }


# ================================================================
# SIGNAL MESSAGE
# ================================================================

def signal_message(signal):

    emoji = "🟢" if signal["direction"] == "LONG" else "🔴"

    strength = (
        "🔥 STRONG"
        if signal["score"] >= STRONG_SCORE
        else "⚡ SIGNAL"
    )

    return f"""
🐋 <b>ETH WHALE — OK-EX IRAN</b>

{emoji} <b>{signal["direction"]}</b>
{strength}

🪙 <b>{signal["symbol"]}</b>

🎯 Score: <b>{signal["score"]}/100</b>
📐 Edge: <b>{signal["edge"]}</b>

💰 Entry:
<b>{signal["entry"]:.8g}</b>

🛑 SL:
<b>{signal["sl"]:.8g}</b>

🎯 TP1:
<b>{signal["tp1"]:.8g}</b>

🎯 TP2:
<b>{signal["tp2"]:.8g}</b>

🎯 TP3:
<b>{signal["tp3"]:.8g}</b>

📊 RSI:
<b>{signal["rsi"]:.2f}</b>

📈 Volume:
<b>x{signal["volume_ratio"]:.2f}</b>

🟢 Paper Mode: ON
🔴 Real Orders: OFF

⏰ {now()}
"""


# ================================================================
# SCAN
# ================================================================

def scan():

    print("\n========================================")
    print("🐋 OK-EX IRAN V12")
    print("========================================")

    symbols = get_pairs()

    if not symbols:

        send_telegram(
            "⚠️ <b>OK-EX ERROR</b>\n\n"
            "Unable to load USDT markets."
        )

        return

    tickers = get_tickers()

    signals = []

    candle_test_done = 0

    for index, symbol in enumerate(symbols, start=1):

        print(f"[{index}/{len(symbols)}] {symbol}")

        candles = get_candles(symbol)

        if candles:

            STATS["candle_ok"] += 1
            STATS["candle_rows"] += len(candles)

            candle_test_done += 1

            signal = analyze(symbol, candles)

            if signal:

                signals.append(signal)

                STATS["signals_found"] += 1

        else:

            STATS["candle_failed"] += 1

        if len(signals) >= MAX_SIGNALS:
            break

    signals.sort(
        key=lambda x: (x["score"], x["edge"]),
        reverse=True
    )

    sent = 0

    for signal in signals[:MAX_SIGNALS]:

        if send_telegram(signal_message(signal)):
            sent += 1

    avg_candles = (
        STATS["candle_rows"] / STATS["candle_ok"]
        if STATS["candle_ok"] > 0 else 0
    )

    summary = f"""
🔎 <b>SCAN COMPLETE — V12</b>
━━━━━━━━━━━━━━━━━━

🪙 Markets checked:
<b>{len(symbols)}</b>

📡 Ticker markets:
<b>{len(tickers)}</b>

📋 Pair markets:
<b>{len(symbols)}</b>

🕯 Candle OK:
<b>{STATS["candle_ok"]}</b>

❌ Candle failed:
<b>{STATS["candle_failed"]}</b>

📚 Candle rows:
<b>{STATS["candle_rows"]}</b>

📐 Avg candles:
<b>{avg_candles:.1f}</b>

🧠 Analysis passed:
<b>{STATS["analysis_passed"]}</b>

🎯 Signals found:
<b>{STATS["signals_found"]}</b>

📨 Signals sent:
<b>{sent}</b>

━━━━━━━━━━━━━━━━━━

🎯 Minimum Score:
<b>{MIN_SCORE}/100</b>

🔥 Strong Score:
<b>{STRONG_SCORE}/100</b>

📊 Minimum Volume:
<b>x{MIN_VOLUME_RATIO:.2f}</b>

📐 Minimum Edge:
<b>{MIN_EDGE}</b>

🟢 Paper Mode:
<b>ON</b>

🔴 Real Orders:
<b>OFF</b>

⏰ {now()}
"""

    send_telegram(summary)

    print("\n" + summary)


# ================================================================
# MAIN
# ================================================================

if __name__ == "__main__":

    print("🐋 OK-EX IRAN V12 STARTED")
    print("PAPER MODE:", PAPER_MODE)
    print("REAL ORDERS:", REAL_ORDERS)
    print("BASE:", BASE_URL)

    try:
        scan()

    except Exception as e:

        print("[FATAL ERROR]", repr(e))

        send_telegram(
            "🚨 <b>OK-EX BOT FATAL ERROR</b>\n\n"
            f"<code>{str(e)[:1000]}</code>"
        )

    print("\n🐋 BOT FINISHED")
