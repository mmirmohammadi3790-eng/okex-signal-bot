# ================================================================
# 🐋 OK-EX IRAN — V16
# ALL USDT MARKETS / PAPER SIGNAL ONLY / TELEGRAM
# CAPITAL = 100 USDT / LEVERAGE = 5X
# LONG / SHORT / WAIT
# ENTRY / SL / TP1 / TP2 / TP3
# RSI / EMA / ATR / MOMENTUM / VOLUME / BREAKOUT / WHALE PROXY
# NO REAL ORDERS
# ================================================================

import os
import time
import math
import requests
from datetime import datetime, timezone


# ================================================================
# CONFIG
# ================================================================

BASE_URL = "https://sapi.ok-ex.io"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

PAPER_MODE = True
REAL_ORDERS = False

CAPITAL_USDT = 100.0
LEVERAGE = 5
POSITION_NOTIONAL = CAPITAL_USDT * LEVERAGE

CANDLE_INTERVAL = "1h"
CANDLE_LIMIT = 100

MAX_MARKETS = 227
MAX_SIGNALS = 3

MIN_SCORE = 65
STRONG_SCORE = 80

MIN_VOLUME_RATIO = 1.15
MIN_EDGE = 12

REQUEST_TIMEOUT = 15

# Whale proxy
WHALE_PROXY_ON = True
WHALE_VOLUME_USDT = 50000.0

# Risk
ATR_MULTIPLIER = 1.5
MIN_STOP_PERCENT = 0.008

# Telegram
TELEGRAM_TIMEOUT = 20


# ================================================================
# SESSION
# ================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "OK-EX-Iran-V16/1.0",
    "Accept": "application/json",
})


# ================================================================
# HELPERS
# ================================================================

def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def fmt_price(value):
    value = safe_float(value)

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 100:
        return f"{value:,.3f}"

    if value >= 1:
        return f"{value:,.4f}"

    if value >= 0.01:
        return f"{value:,.5f}"

    return f"{value:.8f}"


def pct(value):
    return f"{value:+.2f}%"


def request_json(url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception:
        return None


# ================================================================
# TELEGRAM
# ================================================================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[TELEGRAM] Missing token or chat id")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            data=payload,
            timeout=TELEGRAM_TIMEOUT
        )

        if response.status_code == 200:
            print("[TELEGRAM] SENT")
            return True

        print(
            "[TELEGRAM] ERROR",
            response.status_code,
            response.text[:300]
        )

        return False

    except Exception as exc:
        print("[TELEGRAM] EXCEPTION", exc)
        return False


# ================================================================
# OK-EX API
# ================================================================

def get_pairs():
    url = BASE_URL + "/api/v1/spot/public/pairs"

    data = request_json(url)

    if not data:
        print("[PAIR ERROR] No response")
        return []

    raw = data.get("res", data)

    if not isinstance(raw, list):
        print("[PAIR ERROR] Unexpected format")
        return []

    symbols = []

    for item in raw:
        if isinstance(item, dict):
            symbol = item.get("symbol", "")
        else:
            symbol = str(item)

        symbol = str(symbol).upper()

        if symbol.endswith("-USDT"):
            symbols.append(symbol)

    # Remove duplicates
    symbols = list(dict.fromkeys(symbols))

    return symbols[:MAX_MARKETS]


def get_tickers():
    url = BASE_URL + "/api/v1/spot/public/tickers"

    data = request_json(url)

    if not data:
        print("[TICKER ERROR] No response")
        return {}

    raw = data.get("tickers", [])

    if not isinstance(raw, list):
        return {}

    result = {}

    for item in raw:

        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).upper()

        if not symbol.endswith("-USDT"):
            continue

        result[symbol] = item

    return result


def get_candles(symbol):
    url = BASE_URL + "/api/v1/spot/public/candles"

    end_time = int(time.time() * 1000)

    # Request slightly more than needed
    start_time = end_time - (
        CANDLE_LIMIT * 60 * 60 * 1000 * 2
    )

    params = {
        "symbol": symbol,
        "interval": CANDLE_INTERVAL,
        "startTime": start_time,
        "endTime": end_time,
    }

    data = request_json(url, params)

    if not data:
        return []

    raw = data.get("res", data)

    if not isinstance(raw, list):
        return []

    candles = []

    for row in raw:

        if not isinstance(row, (list, tuple)):
            continue

        if len(row) < 6:
            continue

        try:
            timestamp = safe_float(row[0])
            open_price = safe_float(row[1])
            high = safe_float(row[2])
            low = safe_float(row[3])
            close = safe_float(row[4])
            volume = safe_float(row[5])

            if close <= 0:
                continue

            candles.append({
                "timestamp": timestamp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            })

        except Exception:
            continue

    if len(candles) < 60:
        return candles

    # OK-EX normally returns newest -> oldest.
    # Indicators require oldest -> newest.
    if candles[0]["timestamp"] > candles[-1]["timestamp"]:
        candles.reverse()

    return candles[-CANDLE_LIMIT:]


# ================================================================
# INDICATORS
# ================================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2.0 / (period + 1.0)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            (price - result) * multiplier
            + result
        )

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):
        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(values)):

        change = values[i] - values[i - 1]

        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        avg_gain = (
            (avg_gain * (period - 1) + gain)
            / period
        )

        avg_loss = (
            (avg_loss * (period - 1) + loss)
            / period
        )

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    if len(candles) <= period:
        return None

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        high = current["high"]
        low = current["low"]
        previous_close = previous["close"]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = (
            (value * (period - 1) + tr)
            / period
        )

    return value


# ================================================================
# WHALE PROXY
# ================================================================

def calculate_whale_proxy(candle, ticker):
    """
    This is a proxy, NOT actual exchange whale-wallet tracking.

    It estimates unusual market participation using:
    - quote volume
    - candle volume
    - volume ratio
    - price movement
    """

    if not WHALE_PROXY_ON:
        return 0.0

    last_price = safe_float(
        ticker.get("lastPrice", candle["close"])
    )

    quote_volume = safe_float(
        ticker.get("quoteVolume", 0)
    )

    if quote_volume <= 0:
        quote_volume = safe_float(
            ticker.get("quoteVol", 0)
        )

    candle_volume = safe_float(candle["volume"])

    # Approximate USDT turnover
    candle_turnover = candle_volume * last_price

    score = 0.0

    if quote_volume >= WHALE_VOLUME_USDT:
        score += 30

    if candle_turnover >= WHALE_VOLUME_USDT:
        score += 25

    change = (
        (last_price - candle["open"])
        / candle["open"] * 100
        if candle["open"] > 0
        else 0
    )

    if abs(change) >= 1:
        score += 15

    if abs(change) >= 2:
        score += 10

    return clamp(score, 0, 100)


# ================================================================
# ANALYSIS
# ================================================================

def analyze(symbol, candles, ticker):

    if len(candles) < 60:
        return None

    closes = [x["close"] for x in candles]
    volumes = [x["volume"] for x in candles]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi14 = rsi(closes, 14)
    atr14 = atr(candles, 14)

    if (
        ema20 is None
        or ema50 is None
        or rsi14 is None
        or atr14 is None
    ):
        return None

    # ------------------------------------------------------------
    # Momentum
    # ------------------------------------------------------------

    lookback = 10

    if len(closes) > lookback:
        old_price = closes[-lookback - 1]

        momentum = (
            (price - old_price)
            / old_price * 100
            if old_price > 0
            else 0
        )
    else:
        momentum = 0.0

    # ------------------------------------------------------------
    # Volume ratio
    # ------------------------------------------------------------

    previous_volumes = volumes[-21:-1]

    avg_volume = (
        sum(previous_volumes)
        / len(previous_volumes)
        if previous_volumes
        else 0
    )

    current_volume = volumes[-1]

    if avg_volume > 0:
        volume_ratio = current_volume / avg_volume
    else:
        volume_ratio = 0.0

    # ------------------------------------------------------------
    # Price action
    # ------------------------------------------------------------

    previous_highs = [
        x["high"]
        for x in candles[-11:-1]
    ]

    previous_lows = [
        x["low"]
        for x in candles[-11:-1]
    ]

    previous_high = max(previous_highs)
    previous_low = min(previous_lows)

    breakout_long = price > previous_high
    breakout_short = price < previous_low

    # ------------------------------------------------------------
    # Whale proxy
    # ------------------------------------------------------------

    whale_score = calculate_whale_proxy(
        candles[-1],
        ticker
    )

    # ------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------

    long_score = 0
    short_score = 0

    # EMA trend
    if price > ema20:
        long_score += 10
    else:
        short_score += 10

    if ema20 > ema50:
        long_score += 10
    else:
        short_score += 10

    # RSI
    if 50 <= rsi14 <= 70:
        long_score += 10

    if 30 <= rsi14 <= 50:
        short_score += 10

    # Avoid extreme RSI
    if rsi14 > 75:
        long_score -= 5

    if rsi14 < 25:
        short_score -= 5

    # Momentum
    if momentum > 0.5:
        long_score += 10

    if momentum > 2:
        long_score += 5

    if momentum < -0.5:
        short_score += 10

    if momentum < -2:
        short_score += 5

    # Volume
    if volume_ratio >= MIN_VOLUME_RATIO:

        if momentum >= 0:
            long_score += 10
        else:
            short_score += 10

    if volume_ratio >= 2:

        if momentum >= 0:
            long_score += 5
        else:
            short_score += 5

    # Breakout
    if breakout_long:
        long_score += 10

    if breakout_short:
        short_score += 10

    # Whale proxy is bonus only
    whale_bonus = int(whale_score * 0.20)

    if momentum >= 0:
        long_score += whale_bonus
    else:
        short_score += whale_bonus

    long_score = int(clamp(long_score, 0, 100))
    short_score = int(clamp(short_score, 0, 100))

    if long_score >= short_score:
        direction = "LONG"
        score = long_score
        opposite_score = short_score
    else:
        direction = "SHORT"
        score = short_score
        opposite_score = long_score

    edge = abs(score - opposite_score)

    # ------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------

    if score < MIN_SCORE:
        return {
            "rejected": "score",
            "score": score,
        }

    if edge < MIN_EDGE:
        return {
            "rejected": "edge",
            "score": score,
        }

    if volume_ratio < MIN_VOLUME_RATIO:
        return {
            "rejected": "volume",
            "score": score,
        }

    # ------------------------------------------------------------
    # Risk calculation
    # ------------------------------------------------------------

    atr_risk = atr14 * ATR_MULTIPLIER

    minimum_risk = price * MIN_STOP_PERCENT

    risk_distance = max(
        atr_risk,
        minimum_risk
    )

    # Prevent nonsensical stops
    risk_distance = min(
        risk_distance,
        price * 0.08
    )

    entry = price

    if direction == "LONG":

        stop_loss = entry - risk_distance

        tp1 = entry + risk_distance
        tp2 = entry + risk_distance * 2
        tp3 = entry + risk_distance * 3

    else:

        stop_loss = entry + risk_distance

        tp1 = entry - risk_distance
        tp2 = entry - risk_distance * 2
        tp3 = entry - risk_distance * 3

    # ------------------------------------------------------------
    # Profit / Loss on 500 USDT notional
    # ------------------------------------------------------------

    def pnl_at(target):

        move_percent = (
            abs(target - entry)
            / entry
        )

        return POSITION_NOTIONAL * move_percent

    max_loss = pnl_at(stop_loss)

    profit_tp1 = pnl_at(tp1)
    profit_tp2 = pnl_at(tp2)
    profit_tp3 = pnl_at(tp3)

    # ------------------------------------------------------------
    # Signal strength
    # ------------------------------------------------------------

    if score >= STRONG_SCORE:
        strength = "🔥 STRONG"
    elif score >= 72:
        strength = "🟢 GOOD"
    else:
        strength = "🟡 WATCH"

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "edge": edge,
        "strength": strength,

        "price": price,
        "entry": entry,
        "sl": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "rsi": rsi14,
        "ema20": ema20,
        "ema50": ema50,
        "atr": atr14,

        "momentum": momentum,
        "volume_ratio": volume_ratio,
        "whale_score": whale_score,

        "max_loss": max_loss,
        "profit_tp1": profit_tp1,
        "profit_tp2": profit_tp2,
        "profit_tp3": profit_tp3,

        "rr1": 1.0,
        "rr2": 2.0,
        "rr3": 3.0,

        "capital": CAPITAL_USDT,
        "leverage": LEVERAGE,
        "notional": POSITION_NOTIONAL,
    }


# ================================================================
# FORMAT SIGNAL
# ================================================================

def format_signal(signal, rank):

    s = signal

    direction_icon = (
        "🟢 LONG"
        if s["direction"] == "LONG"
        else "🔴 SHORT"
    )

    message = f"""
🐋 OK-EX IRAN — PAPER SIGNAL #{rank}

━━━━━━━━━━━━━━━━━━━━
🪙 {s["symbol"]}
📌 {direction_icon}
⭐ {s["strength"]}
🎯 Score: {s["score"]}/100
📊 Edge: {s["edge"]}

━━━━━━━━━━━━━━━━━━━━
💰 CAPITAL
Capital: {s["capital"]:.2f} USDT
Leverage: {s["leverage"]}×
Position Size: {s["notional"]:.2f} USDT

━━━━━━━━━━━━━━━━━━━━
📍 ENTRY
{fmt_price(s["entry"])}

🛑 STOP LOSS
{fmt_price(s["sl"])}
Max Loss: -{s["max_loss"]:.2f} USDT

━━━━━━━━━━━━━━━━━━━━
🎯 TP1
{fmt_price(s["tp1"])}
Profit: +{s["profit_tp1"]:.2f} USDT
R/R: 1:1

🎯 TP2
{fmt_price(s["tp2"])}
Profit: +{s["profit_tp2"]:.2f} USDT
R/R: 1:2

🎯 TP3
{fmt_price(s["tp3"])}
Profit: +{s["profit_tp3"]:.2f} USDT
R/R: 1:3

━━━━━━━━━━━━━━━━━━━━
📈 RSI: {s["rsi"]:.2f}
📊 Volume: {s["volume_ratio"]:.2f}×
🚀 Momentum: {pct(s["momentum"])}
🐋 Whale Proxy: {s["whale_score"]:.0f}/100

━━━━━━━━━━━━━━━━━━━━
⚠️ PAPER MODE: ON
🔴 REAL ORDERS: OFF

⏰ {now_text()}
"""

    return message.strip()


# ================================================================
# SUMMARY
# ================================================================

def format_summary(
    markets_checked,
    tickers_count,
    candle_ok,
    candle_failed,
    analysis_attempted,
    analysis_passed,
    signals_found,
    signals_sent,
    long_count,
    short_count,
    rejected_score,
    rejected_volume,
    rejected_edge,
    rejected_data,
):

    return f"""
🔎 SCAN COMPLETE — V16

🪙 Markets checked: {markets_checked}
📊 Ticker markets: {tickers_count}

🕯 Candle OK: {candle_ok}
❌ Candle failed: {candle_failed}

🧠 Analysis attempted: {analysis_attempted}
✅ Analysis passed: {analysis_passed}

🎯 Signals found: {signals_found}
🟢 LONG: {long_count}
🔴 SHORT: {short_count}
📨 Signals sent: {signals_sent}

━━━━━━━━━━━━━━━━━━━━
⚙️ FILTERS

Minimum score: {MIN_SCORE}/100
Strong score: {STRONG_SCORE}/100
Minimum volume: {MIN_VOLUME_RATIO:.2f}×
Minimum edge: {MIN_EDGE}

━━━━━━━━━━━━━━━━━━━━
🔍 REJECT DIAGNOSTICS

Score: {rejected_score}
Volume: {rejected_volume}
Edge: {rejected_edge}
Data: {rejected_data}

━━━━━━━━━━━━━━━━━━━━
💰 CAPITAL: {CAPITAL_USDT:.2f} USDT
⚡ LEVERAGE: {LEVERAGE}×
📦 POSITION: {POSITION_NOTIONAL:.2f} USDT

🐋 Whale Proxy: ON
🟢 Paper Mode: ON
🔴 Real Orders: OFF

⏰ {now_text()}
""".strip()


# ================================================================
# MAIN SCANNER
# ================================================================

def main():

    print()
    print("===============================================================")
    print("🐋 OK-EX IRAN V16 STARTED")
    print("===============================================================")
    print("PAPER MODE:", PAPER_MODE)
    print("REAL ORDERS:", REAL_ORDERS)
    print("CAPITAL:", CAPITAL_USDT, "USDT")
    print("LEVERAGE:", LEVERAGE, "x")
    print("POSITION:", POSITION_NOTIONAL, "USDT")
    print("BASE:", BASE_URL)
    print()

    if REAL_ORDERS:
        print("🚨 WARNING: REAL ORDERS MUST REMAIN FALSE")
        return

    # ------------------------------------------------------------
    # 1. Pairs
    # ------------------------------------------------------------

    print("[1] Loading pairs...")

    symbols = get_pairs()

    if not symbols:

        print("[PAIR ERROR] No USDT markets found")

        send_telegram(
            "⚠️ OK-EX MARKET ERROR\n\n"
            "Could not load USDT markets."
        )

        return

    print(
        f"[PAIR OK] {len(symbols)} USDT markets"
    )

    # ------------------------------------------------------------
    # 2. Tickers
    # ------------------------------------------------------------

    print()
    print("[2] Loading tickers...")

    tickers = get_tickers()

    print(
        f"[TICKER OK] {len(tickers)} USDT tickers"
    )

    # ------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------

    markets_checked = 0
    candle_ok = 0
    candle_failed = 0

    analysis_attempted = 0
    analysis_passed = 0

    signals = []

    rejected_score = 0
    rejected_volume = 0
    rejected_edge = 0
    rejected_data = 0

    # ------------------------------------------------------------
    # 3. Scan markets
    # ------------------------------------------------------------

    for index, symbol in enumerate(symbols, start=1):

        markets_checked += 1

        print(
            f"[{index}/{len(symbols)}] {symbol}"
        )

        ticker = tickers.get(symbol)

        if not ticker:
            rejected_data += 1
            continue

        print("[CANDLE]", symbol)

        candles = get_candles(symbol)

        if len(candles) < 60:

            candle_failed += 1
            rejected_data += 1

            print(
                "[CANDLE FAIL]",
                symbol,
                len(candles)
            )

            continue

        candle_ok += 1

        print(
            "[CANDLE OK]",
            symbol,
            len(candles)
        )

        analysis_attempted += 1

        result = analyze(
            symbol,
            candles,
            ticker
        )

        if result is None:

            rejected_data += 1
            continue

        if result.get("rejected") == "score":
            rejected_score += 1
            continue

        if result.get("rejected") == "volume":
            rejected_volume += 1
            continue

        if result.get("rejected") == "edge":
            rejected_edge += 1
            continue

        if "direction" not in result:
            rejected_data += 1
            continue

        analysis_passed += 1

        signals.append(result)

    # ------------------------------------------------------------
    # Sort by score then edge
    # ------------------------------------------------------------

    signals.sort(
        key=lambda x: (
            x["score"],
            x["edge"],
            x["volume_ratio"],
            x["whale_score"]
        ),
        reverse=True
    )

    signals_found = len(signals)

    top_signals = signals[:MAX_SIGNALS]

    long_count = sum(
        1
        for x in top_signals
        if x["direction"] == "LONG"
    )

    short_count = sum(
        1
        for x in top_signals
        if x["direction"] == "SHORT"
    )

    # ------------------------------------------------------------
    # Send signals
    # ------------------------------------------------------------

    signals_sent = 0

    for rank, signal in enumerate(
        top_signals,
        start=1
    ):

        print()
        print(
            "SIGNAL",
            rank,
            signal["symbol"],
            signal["direction"],
            signal["score"]
        )

        message = format_signal(
            signal,
            rank
        )

        if send_telegram(message):
            signals_sent += 1

        # Avoid Telegram flood
        time.sleep(1)

    # ------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------

    summary = format_summary(
        markets_checked=markets_checked,
        tickers_count=len(tickers),
        candle_ok=candle_ok,
        candle_failed=candle_failed,
        analysis_attempted=analysis_attempted,
        analysis_passed=analysis_passed,
        signals_found=signals_found,
        signals_sent=signals_sent,
        long_count=long_count,
        short_count=short_count,
        rejected_score=rejected_score,
        rejected_volume=rejected_volume,
        rejected_edge=rejected_edge,
        rejected_data=rejected_data,
    )

    print()
    print(summary)
    print()

    send_telegram(summary)

    print()
    print("🐋 V16 FINISHED")
    print("===============================================================")


# ================================================================
# RUN
# ================================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("Stopped by user.")

    except Exception as exc:

        print()
        print("🚨 FATAL ERROR")
        print(type(exc).__name__, str(exc))

        try:
            send_telegram(
                "🚨 OK-EX V16 ERROR\n\n"
                f"{type(exc).__name__}: {str(exc)[:500]}"
            )
        except Exception:
            pass
