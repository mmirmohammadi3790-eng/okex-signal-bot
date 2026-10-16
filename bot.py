
import os
import time
from datetime import datetime, timezone
from collections import Counter

import requests

# ============================================================
# ETH WHALE - BITPIN PAPER SIGNAL BOT
# PAPER ONLY - NO REAL ORDERS
# ============================================================

BITPIN_BASES = [
    "https://api.bitpin.ir",
    "https://api.bitpin.org",
]

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

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/5.1",
    "Accept": "application/json",
})


# ---------------- HTTP ----------------

def get_json(url, params=None):
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram credentials missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

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
        data = response.json()
        print("Telegram send:", data.get("ok", False))
        return bool(data.get("ok"))
    except Exception as exc:
        print("Telegram error:", str(exc))
        return False


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------- BITPIN API ----------------

def fetch_bitpin_endpoint(paths):
    errors = []

    for base in BITPIN_BASES:
        for path in paths:
            url = base + path
            try:
                data = get_json(url)
                print("API endpoint responded:", url)
                return data, url
            except Exception as exc:
                errors.append(f"{url}: {str(exc)[:140]}")

    raise RuntimeError(
        "All Bitpin endpoints failed:\n" + "\n".join(errors)
    )


def get_market_list():
    data, used_url = fetch_bitpin_endpoint([
        "/v1/mkt/markets/",
        "/api/v1/mkt/markets/",
        "/v1/mkt/markets",
        "/api/v1/mkt/markets",
    ])

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("results", data.get("data", []))
    else:
        rows = []

    if not isinstance(rows, list) or not rows:
        raise RuntimeError(
            f"Market endpoint returned an unexpected response: {used_url}"
        )

    markets = []
    seen = set()

    for item in rows:
        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("code") or item.get("symbol") or ""
        ).upper().replace("-", "_")

        quote = str(
            (item.get("currency2") or {}).get("code", "")
        ).upper()

        if not quote and "_" in symbol:
            quote = symbol.split("_")[-1]

        if quote == "USDT" and symbol and symbol not in seen:
            if item.get("tradable") is False:
                continue
            seen.add(symbol)
            markets.append(item)

    if not markets:
        raise RuntimeError(
            "No USDT markets parsed. Inspect the markets API response."
        )

    return markets


def parse_tickers(data):
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get(
            "tickers",
            data.get("results", data.get("data", [])),
        )
        if isinstance(rows, dict):
            rows = list(rows.values())
    else:
        rows = []

    result = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        symbol = str(
            row.get("symbol") or row.get("code") or ""
        ).upper().replace("-", "_")

        price = (
            row.get("last")
            or row.get("last_price")
            or row.get("price")
            or row.get("close")
        )

        try:
            price = float(price)
        except (TypeError, ValueError):
            continue

        if symbol and price > 0:
            result[symbol] = {
                "price": price,
                "volume": safe_float(
                    row.get("quote_volume")
                    or row.get("volume")
                    or row.get("value")
                ),
            }

    return result


def get_bitpin_tickers():
    data, used_url = fetch_bitpin_endpoint([
        "/v1/mkt/tickers/",
        "/api/v1/mkt/tickers/",
        "/v1/mkt/tickers",
        "/api/v1/mkt/tickers",
    ])

    result = parse_tickers(data)

    if not result:
        raise RuntimeError(
            "Ticker endpoint responded but no usable prices were found. "
            f"Endpoint: {used_url}. "
            "The response format may have changed."
        )

    print(f"Bitpin tickers parsed: {len(result)}")
    return result


# ---------------- BINANCE CANDLES ----------------

def get_candles(symbol, interval):
    binance_symbol = symbol.replace("_", "").replace("-", "").upper()
    params = {
        "symbol": binance_symbol,
        "interval": interval,
        "limit": 100,
    }

    errors = []

    for host in BINANCE_HOSTS:
        try:
            data = get_json(host + "/api/v3/klines", params=params)

            if not isinstance(data, list) or len(data) < 60:
                raise ValueError("Insufficient candles")

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
            errors.append(f"{host}: {str(exc)[:100]}")

    raise RuntimeError(
        f"Candle error {symbol} {interval}: " + " | ".join(errors)
    )


# ---------------- INDICATORS ----------------

def ema(values, period):
    if len(values) < period:
        raise ValueError("Insufficient EMA values")

    value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for item in values[period:]:
        value = (item - value) * multiplier + value

    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        raise ValueError("Insufficient RSI values")

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0

    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def atr(candles, period=14):
    if len(candles) < period + 1:
        raise ValueError("Insufficient ATR candles")

    values = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        values.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close),
        ))

    return sum(values[-period:]) / period


def volume_ratio(candles):
    closed = candles[:-1]

    if len(closed) < 25:
        raise ValueError("Insufficient volume candles")

    average = sum(c["volume"] for c in closed[-21:-1]) / 20

    if average <= 0:
        return 0.0

    return closed[-1]["volume"] / average


def timeframe_analysis(candles):
    closed = candles[:-1]
    closes = [c["close"] for c in closed]

    if len(closes) < 60:
        raise ValueError("Insufficient closed candles")

    return {
        "close": closes[-1],
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "rsi": rsi(closes),
        "atr": atr(closed),
        "open": closed[-1]["open"],
        "last_close": closed[-1]["close"],
    }


# ---------------- SIGNAL LOGIC ----------------

def build_signal(symbol, price):
    candles15 = get_candles(symbol, "15m")
    time.sleep(0.1)
    candles1h = get_candles(symbol, "1h")

    a15 = timeframe_analysis(candles15)
    a1h = timeframe_analysis(candles1h)
    vol = volume_ratio(candles15)

    if a15["ema20"] > a15["ema50"] and a1h["ema20"] > a1h["ema50"]:
        side = "LONG"
    elif a15["ema20"] < a15["ema50"] and a1h["ema20"] < a1h["ema50"]:
        side = "SHORT"
    else:
        return None, "trend_mismatch"

    if side == "LONG":
        if not 42 <= a15["rsi"] <= 69:
            return None, "rsi15_out_of_range"
        if a1h["rsi"] < 48:
            return None, "rsi1h_not_confirming"
    else:
        if not 31 <= a15["rsi"] <= 58:
            return None, "rsi15_out_of_range"
        if a1h["rsi"] > 52:
            return None, "rsi1h_not_confirming"

    if vol < MIN_VOLUME_RATIO:
        return None, "low_volume"

    if price <= 0 or a15["atr"] <= 0:
        return None, "invalid_price_or_atr"

    score = 30
    gap = abs(a15["ema20"] - a15["ema50"]) / max(a15["close"], 1e-12)
    score += 15 if gap >= 0.002 else 8

    if side == "LONG":
        score += 15 if 48 <= a15["rsi"] <= 63 else 8
        score += 10 if a1h["rsi"] >= 55 else 5
        candle_confirm = a15["last_close"] > a15["open"]
    else:
        score += 15 if 37 <= a15["rsi"] <= 52 else 8
        score += 10 if a1h["rsi"] <= 45 else 5
        candle_confirm = a15["last_close"] < a15["open"]

    score += 20 if vol >= 1.5 else 12
    score += 5 if candle_confirm else 0

    if score < MIN_SCORE:
        return None, "score_below_minimum"

    entry = price
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

    margin = CAPITAL / MAX_SIGNALS
    notional = margin * LEVERAGE
    quantity = notional / entry

    return {
        "symbol": symbol,
        "side": side,
        "score": min(score, 100),
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi15": a15["rsi"],
        "rsi1h": a1h["rsi"],
        "volume": vol,
        "margin": margin,
        "notional": notional,
        "quantity": quantity,
        "loss": quantity * abs(entry - stop),
        "pnl1": quantity * abs(tp1 - entry),
        "pnl2": quantity * abs(tp2 - entry),
        "pnl3": quantity * abs(tp3 - entry),
    }, "signal"


# ---------------- REPORT ----------------

def fmt(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def make_report(signals, stats, market_count, analyzed, errors):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "🐋 ETH WHALE",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 BITPIN SMART MARKET WATCH",
        "🧪 PAPER SIGNALS ONLY",
        "⛔ Real Orders: OFF",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 سرمایه آزمایشی: {CAPITAL:.2f} USDT",
        f"⚙️ اهرم شبیه‌سازی: {LEVERAGE}x",
        f"🧩 مارجین هر موقعیت: {CAPITAL / MAX_SIGNALS:.2f} USDT",
        f"📦 ارزش فرضی هر موقعیت: {CAPITAL / MAX_SIGNALS * LEVERAGE:.2f} USDT",
        f"📉 حداکثر مارجین مجموع: {CAPITAL:.2f} USDT",
        "⏱ تایم‌فریم: 15m + 1h",
        "📈 قیمت لحظه‌ای: Bitpin",
        "🕯 کندل‌ها: Binance public API",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔎 بازارهای انتخاب‌شده: {market_count}",
        f"✅ تحلیل موفق: {analyzed}",
        f"⚠️ خطای کندل/تحلیل: {errors}",
        f"🎯 سیگنال معتبر: {len(signals)}",
        "",
    ]

    if signals:
        for i, s in enumerate(signals, 1):
            icon = "🟢" if s["side"] == "LONG" else "🔴"
            label = "🔥 STRONG" if s["score"] >= STRONG_SCORE else "✅ VALID"

            lines.extend([
                "━━━━━━━━━━━━━━━━━━━━",
                f"{icon} {i}. {s['symbol']} — {s['side']}",
                f"{label} | امتیاز: {s['score']}/100",
                f"🎯 ورود: {fmt(s['entry'])}",
                f"🛑 حد ضرر: {fmt(s['stop'])}",
                f"🥇 TP1: {fmt(s['tp1'])}",
                f"🥈 TP2: {fmt(s['tp2'])}",
                f"🥉 TP3: {fmt(s['tp3'])}",
                f"📊 RSI 15m: {s['rsi15']:.1f}",
                f"📊 RSI 1h: {s['rsi1h']:.1f}",
                f"📈 نسبت حجم: {s['volume']:.2f}x",
                f"💵 مارجین فرضی: {s['margin']:.2f} USDT",
                f"📦 ارزش موقعیت: {s['notional']:.2f} USDT",
                f"📏 مقدار فرضی: {s['quantity']:.8f}",
                f"⚠️ زیان تخمینی تا SL: {s['loss']:.2f} USDT",
                f"💰 سود تخمینی TP1: +{s['pnl1']:.2f} USDT",
                f"💰 سود تخمینی TP2: +{s['pnl2']:.2f} USDT",
                f"💰 سود تخمینی TP3: +{s['pnl3']:.2f} USDT",
                "",
            ])
    else:
        lines.extend([
            "🔍 سیگنال منطبق با فیلترها پیدا نشد.",
            "📋 دلایل رد بازارها:",
        ])

    lines.append("")
    lines.append("📋 آمار فیلترها:")

    if stats:
        for reason, count in stats.most_common(8):
            lines.append(f"• {reason}: {count}")
    else:
        lines.append("• اطلاعات تشخیصی در دسترس نیست")

    lines.extend([
        "",
        f"🕒 زمان اجرا: {now}",
        "🛡️ هیچ سفارش واقعی ثبت نشده است.",
        "⚠️ محاسبات فرضی‌اند و سود تضمین نمی‌شود.",
    ])

    return "\n".join(lines)


# ---------------- MAIN ----------------

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

        candidates = []

        for market in markets:
            symbol = str(
                market.get("code") or market.get("symbol") or ""
            ).upper().replace("-", "_")

            ticker = tickers.get(symbol)

            if not ticker:
                stats["missing_ticker"] += 1
                continue

            candidates.append((
                ticker["volume"],
                symbol,
                ticker["price"],
            ))

        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = candidates[:MAX_MARKETS]

        print("Markets selected:", len(selected))
        print("Ticker count:", len(tickers))

        for _, symbol, price in selected:
            try:
                signal, reason = build_signal(symbol, price)
                stats[reason] += 1
                analyzed += 1

                if signal:
                    signals.append(signal)
                    print(
                        "SIGNAL",
                        symbol,
                        signal["side"],
                        "score:",
                        signal["score"],
                    )

            except Exception as exc:
                errors += 1
                stats["candle_or_analysis_error"] += 1
                print("ERROR", symbol, str(exc)[:400])

            time.sleep(0.15)

        signals.sort(key=lambda s: s["score"], reverse=True)
        signals = signals[:MAX_SIGNALS]

        report = make_report(
            signals,
            stats,
            len(selected),
            analyzed,
            errors,
        )

        print(report)
        send_telegram(report)

        print("\nFULL DIAGNOSTICS")
        for reason, count in stats.most_common():
            print(f"{reason}: {count}")

    except Exception as exc:
        message = (
            "🐋 ETH WHALE\n"
            "⚠️ BOT RUN FAILED\n\n"
            + str(exc)[:3000]
            + "\n\n🔒 Real orders: OFF"
        )
        print(message)
        send_telegram(message)
        raise


if __name__ == "__main__":
    main()
