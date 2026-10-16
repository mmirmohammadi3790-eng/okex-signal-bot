
import os
import time
import math
from datetime import datetime, timezone
from collections import Counter

import requests


# ============================================================
# ETH WHALE - BITPIN SMART MARKET WATCH
# PAPER SIGNALS ONLY - NO REAL ORDERS
# ============================================================

BITPIN_BASE = "https://api.bitpin.org/v1"
BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
]

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or ""
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or ""

CAPITAL = 48.0
LEVERAGE = 3
MAX_SIGNALS = 3
MAX_MARKETS = 30

MIN_SCORE = 65
STRONG_SCORE = 80
MIN_VOLUME_RATIO = 1.15

TIMEOUT = 15
CANDLE_LIMIT = 100

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-PaperSignalBot/5.0",
    "Accept": "application/json",
})


# -------------------- HTTP --------------------

def get_json(url, params=None):
    response = session.get(
        url, params=params, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = session.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            print("Telegram API returned ok=false:", result)
            return False

        return True

    except Exception as exc:
        print("Telegram send error:", str(exc))
        return False


# -------------------- BITPIN DATA --------------------

def get_market_list():
    """Fetch USDT markets from Bitpin, including pagination."""
    markets = []
    url = BITPIN_BASE + "/mkt/markets/"
    pages = 0

    while url and pages < 10:
        data = get_json(url)
        pages += 1

        if isinstance(data, list):
            markets.extend(data)
            break

        if not isinstance(data, dict):
            break

        rows = data.get("results", [])
        if not rows and isinstance(data.get("data"), list):
            rows = data["data"]

        markets.extend(rows)
        url = data.get("next")

    unique = {}

    for market in markets:
        if not isinstance(market, dict):
            continue

        symbol = str(market.get("code") or market.get("symbol") or "")
        symbol = symbol.upper().replace("-", "_")

        quote = str(
            (market.get("currency2") or {}).get("code", "")
        ).upper()

        if not quote and "_" in symbol:
            quote = symbol.split("_")[-1]

        if quote != "USDT" or not symbol:
            continue

        if market.get("tradable") is False:
            continue

        unique[symbol] = market

    if not unique:
        raise RuntimeError(
            "No Bitpin USDT markets found. Check the markets API response."
        )

    return list(unique.values())


def get_bitpin_tickers():
    data = get_json(BITPIN_BASE + "/mkt/tickers/")

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("tickers", data.get("results", []))
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not rows and isinstance(data.get("data"), list):
            rows = data["data"]
    else:
        rows = []

    result = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        symbol = str(row.get("symbol") or row.get("code") or "")
        symbol = symbol.upper().replace("-", "_")

        price = (
            row.get("last")
            or row.get("last_price")
            or row.get("price")
            or row.get("close")
        )

        try:
            price = float(price)
            if price > 0 and symbol:
                result[symbol] = {
                    "price": price,
                    "volume": safe_float(
                        row.get("quote_volume")
                        or row.get("volume")
                        or row.get("value")
                    ),
                }
        except (TypeError, ValueError):
            continue

    if not result:
        raise RuntimeError(
            "No usable Bitpin ticker prices found. "
            "Check the tickers API response."
        )

    return result


# -------------------- BINANCE CANDLES --------------------

def binance_symbol(bitpin_symbol):
    return bitpin_symbol.replace("_", "").replace("-", "").upper()


def get_candles(symbol, interval):
    params = {
        "symbol": binance_symbol(symbol),
        "interval": interval,
        "limit": CANDLE_LIMIT,
    }

    errors = []

    for host in BINANCE_HOSTS:
        try:
            data = get_json(host + "/api/v3/klines", params=params)

            if not isinstance(data, list) or len(data) < 60:
                raise ValueError("Not enough candles returned")

            candles = []

            for row in data:
                candles.append({
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": int(row[6]),
                })

            return candles

        except Exception as exc:
            errors.append(str(exc))

    raise RuntimeError(
        "Binance candles unavailable for "
        + symbol + " " + interval
        + ": " + " | ".join(errors[-2:])
    )


# -------------------- INDICATORS --------------------

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough values for EMA")

    multiplier = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = (value - result) * multiplier + result

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        raise ValueError("Not enough values for RSI")

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        raise ValueError("Not enough candles for ATR")

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close),
        )
        true_ranges.append(tr)

    return sum(true_ranges[-period:]) / period


def candle_volume_ratio(candles):
    # Last candle is excluded if it is still forming.
    closed = candles[:-1]

    if len(closed) < 25:
        raise ValueError("Not enough closed candles for volume")

    previous_volumes = [
        c["volume"] for c in closed[-21:-1]
    ]
    average_volume = sum(previous_volumes) / len(previous_volumes)

    if average_volume <= 0:
        return 0.0

    return closed[-1]["volume"] / average_volume


def analyze_timeframe(candles):
    # Exclude the currently forming candle.
    closed = candles[:-1]

    closes = [c["close"] for c in closed]

    if len(closes) < 60:
        raise ValueError("Not enough closed candles")

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    current_close = closes[-1]

    return {
        "close": current_close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi(closes, 14),
        "atr": atr(closed, 14),
        "last_open": closed[-1]["open"],
        "last_close": closed[-1]["close"],
    }


# -------------------- SIGNAL ENGINE --------------------

def build_signal(symbol, bitpin_price):
    candles15 = get_candles(symbol, "15m")
    time.sleep(0.08)
    candles1h = get_candles(symbol, "1h")

    a15 = analyze_timeframe(candles15)
    a1h = analyze_timeframe(candles1h)
    volume_ratio = candle_volume_ratio(candles15)

    long_trend = (
        a15["ema20"] > a15["ema50"]
        and a1h["ema20"] > a1h["ema50"]
    )

    short_trend = (
        a15["ema20"] < a15["ema50"]
        and a1h["ema20"] < a1h["ema50"]
    )

    if long_trend:
        side = "LONG"
    elif short_trend:
        side = "SHORT"
    else:
        return None, "trend_mismatch"

    rsi15 = a15["rsi"]
    rsi1h = a1h["rsi"]

    if side == "LONG":
        if not (42 <= rsi15 <= 69):
            return None, "rsi15_out_of_range"
        if rsi1h < 48:
            return None, "rsi1h_not_confirming"
    else:
        if not (31 <= rsi15 <= 58):
            return None, "rsi15_out_of_range"
        if rsi1h > 52:
            return None, "rsi1h_not_confirming"

    if volume_ratio < MIN_VOLUME_RATIO:
        return None, "low_volume"

    if bitpin_price <= 0 or a15["atr"] <= 0:
        return None, "invalid_price_or_atr"

    # Scoring out of 100.
    score = 30

    ema_gap = abs(a15["ema20"] - a15["ema50"]) / a15["close"]
    score += 15 if ema_gap >= 0.002 else 8

    if side == "LONG":
        score += 15 if 48 <= rsi15 <= 63 else 8
        score += 10 if rsi1h >= 55 else 5
    else:
        score += 15 if 37 <= rsi15 <= 52 else 8
        score += 10 if rsi1h <= 45 else 5

    score += 20 if volume_ratio >= 1.5 else 12
    score += 5 if (
        (side == "LONG" and a15["last_close"] > a15["last_open"])
        or
        (side == "SHORT" and a15["last_close"] < a15["last_open"])
    ) else 0

    if score < MIN_SCORE:
        return None, "score_below_minimum"

    # Risk levels use ATR from Binance candles but Bitpin entry price.
    entry = bitpin_price
    stop_distance = max(a15["atr"] * 1.5, entry * 0.003)

    if side == "LONG":
        stop = entry - stop_distance
        tp1 = entry + stop_distance
        tp2 = entry + stop_distance * 1.7
        tp3 = entry + stop_distance * 2.5
    else:
        stop = entry + stop_distance
        tp1 = entry - stop_distance
        tp2 = entry - stop_distance * 1.7
        tp3 = entry - stop_distance * 2.5

    margin_per_signal = CAPITAL / MAX_SIGNALS
    notional_per_signal = margin_per_signal * LEVERAGE
    quantity = notional_per_signal / entry

    estimated_loss = quantity * abs(entry - stop)
    estimated_tp1 = quantity * abs(tp1 - entry)
    estimated_tp2 = quantity * abs(tp2 - entry)
    estimated_tp3 = quantity * abs(tp3 - entry)

    return {
        "symbol": symbol,
        "side": side,
        "score": min(score, 100),
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "volume_ratio": volume_ratio,
        "margin": margin_per_signal,
        "notional": notional_per_signal,
        "quantity": quantity,
        "estimated_loss": estimated_loss,
        "estimated_tp1": estimated_tp1,
        "estimated_tp2": estimated_tp2,
        "estimated_tp3": estimated_tp3,
    }, "signal"


# -------------------- TELEGRAM FORMATTING --------------------

def fmt_price(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def build_report(signals, stats, errors, market_count, analyzed):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "🐋 ETH WHALE",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 BITPIN SMART MARKET WATCH",
        "🧪 PAPER SIGNALS ONLY",
        "━━━━━━━━━━━━━━━━━━━━",
        "🟢 Bitpin prices | Binance public candles",
        "🔒 Real Orders: OFF",
        "",
        f"💰 Simulated capital: {CAPITAL:.2f} USDT",
        f"⚙️ Simulated leverage: {LEVERAGE}x",
        f"🧩 Margin per position: {CAPITAL / MAX_SIGNALS:.2f} USDT",
        f"📦 Notional per position: {CAPITAL / MAX_SIGNALS * LEVERAGE:.2f} USDT",
        f"📉 Maximum total margin: {CAPITAL:.2f} USDT",
        "⏱ Timeframes: 15m + 1h",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔎 Markets selected: {market_count}",
        f"✅ Analyzed successfully: {analyzed}",
        f"⚠️ Candle/analysis errors: {errors}",
        f"🎯 Valid signals: {len(signals)}",
        "",
    ]

    if signals:
        for index, sig in enumerate(signals, 1):
            icon = "🟢" if sig["side"] == "LONG" else "🔴"
            quality = "🔥 STRONG" if sig["score"] >= STRONG_SCORE else "✅ VALID"

            lines.extend([
                "━━━━━━━━━━━━━━━━━━━━",
                f"{icon} {index}. {sig['symbol']} | {sig['side']}",
                f"{quality} | Score: {sig['score']}/100",
                "",
                f"🎯 Entry: {fmt_price(sig['entry'])}",
                f"🛑 Stop Loss: {fmt_price(sig['stop'])}",
                f"🥇 TP1: {fmt_price(sig['tp1'])}",
                f"🥈 TP2: {fmt_price(sig['tp2'])}",
                f"🥉 TP3: {fmt_price(sig['tp3'])}",
                "",
                f"📊 RSI 15m: {sig['rsi15']:.1f}",
                f"📊 RSI 1h: {sig['rsi1h']:.1f}",
                f"📈 Volume ratio: {sig['volume_ratio']:.2f}x",
                f"💵 Simulated margin: {sig['margin']:.2f} USDT",
                f"📦 Simulated position: {sig['notional']:.2f} USDT",
                f"📏 Estimated quantity: {sig['quantity']:.8f}",
                f"⚠️ Estimated loss at SL: {sig['estimated_loss']:.2f} USDT",
                f"💰 Estimated TP1 P/L: +{sig['estimated_tp1']:.2f} USDT",
                f"💰 Estimated TP2 P/L: +{sig['estimated_tp2']:.2f} USDT",
                f"💰 Estimated TP3 P/L: +{sig['estimated_tp3']:.2f} USDT",
                "",
            ])
    else:
        lines.extend([
            "🔍 No signal matched all filters this run.",
            "",
            "📋 Rejection reasons:",
        ])

        if stats:
            for reason, count in stats.most_common(7):
                lines.append(f"• {reason}: {count}")
        else:
            lines.append("• No diagnostic data available")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🧭 Rejection diagnostics:",
    ])

    if stats:
        for reason, count in stats.most_common(7):
            lines.append(f"• {reason}: {count}")

    lines.extend([
        "",
        f"🕒 Run time: {now}",
        "⚠️ Paper calculations only; not financial advice.",
        "🚫 No real orders were submitted.",
    ])

    return "\n".join(lines)


# -------------------- MAIN --------------------

def main():
    print("=" * 55)
    print("ETH WHALE - BITPIN PAPER SIGNAL BOT")
    print("REAL ORDERS: OFF")
    print("=" * 55)

    stats = Counter()
    errors = 0
    analyzed = 0
    signals = []

    try:
        markets = get_market_list()
        tickers = get_bitpin_tickers()

        # Rank markets by available ticker volume where possible.
        eligible = []

        for market in markets:
            symbol = str(
                market.get("code") or market.get("symbol") or ""
            ).upper().replace("-", "_")

            ticker = tickers.get(symbol)

            if not ticker:
                stats["missing_bitpin_ticker"] += 1
                continue

            eligible.append((
                ticker.get("volume", 0.0),
                symbol,
                ticker["price"],
            ))

        eligible.sort(key=lambda item: item[0], reverse=True)
        selected = eligible[:MAX_MARKETS]

        print("Markets selected:", len(selected))

        for _, symbol, price in selected:
            try:
                signal, reason = build_signal(symbol, price)
                stats[reason] += 1
                analyzed += 1

                if signal:
                    signals.append(signal)
                    print(
                        "SIGNAL:",
                        signal["symbol"],
                        signal["side"],
                        "score=",
                        signal["score"],
                    )

            except Exception as exc:
                errors += 1
                stats["candle_or_analysis_error"] += 1
                print("ERROR", symbol, str(exc)[:250])

            # Avoid sending too many requests too quickly.
            time.sleep(0.15)

        signals.sort(key=lambda item: item["score"], reverse=True)
        signals = signals[:MAX_SIGNALS]

        report = build_report(
            signals=signals,
            stats=stats,
            errors=errors,
            market_count=len(selected),
            analyzed=analyzed,
        )

        print("\n" + report)
        sent = send_telegram(report)
        print("Telegram report sent:", sent)

        print("\nDiagnostics:")
        for reason, count in stats.most_common():
            print(f"{reason}: {count}")

    except Exception as exc:
        error_message = (
            "🐋 ETH WHALE\n"
            "⚠️ BOT RUN FAILED\n\n"
            + str(exc)[:2500]
            + "\n\n🔒 Real orders: OFF"
        )
        print(error_message)
        send_telegram(error_message)
        raise


if __name__ == "__main__":
    main()
