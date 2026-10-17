
# ============================================================
# ETH WHALE V5.5
# BITPIN SPOT USDT | PAPER TRADING ONLY
# SUPPORT + CLOSED CANDLE CONFIRMATION
# NO REAL ORDERS | NO API KEYS REQUIRED
# ============================================================

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone

BOT_NAME = "🐋 ETH WHALE"
VERSION = "5.5"

BASE_URL = "https://api.bitpin.ir/v1"
CAPITAL_USDT = 48.0
MAX_SIGNALS = 3
MAX_MARKETS = 30
MIN_SCORE = 62

# Spot only: no leverage, no short selling.
MARGIN_PER_TRADE = CAPITAL_USDT / MAX_SIGNALS

HISTORY_FILE = "paper_history.json"
TIMEOUT = 15
SUPPORT_LOOKBACK = 40
SUPPORT_ZONE_PCT = 0.008
STOP_BUFFER_PCT = 0.003
RISK_PER_TRADE_PCT = 0.01

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
)
TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("ETH_WHALE")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Bitpin-Spot/5.5"
})


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def num(value, default=0.0):
    try:
        x = float(value)
        if x != x or abs(x) == float("inf"):
            return default
        return x
    except (TypeError, ValueError):
        return default


def fmt(value):
    value = num(value)
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def get_json(url, params=None):
    response = SESSION.get(
        url, params=params or {}, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram secrets are missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = SESSION.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        if not response.json().get("ok"):
            log.error("Telegram did not accept the message.")
            return False

        return True

    except Exception as exc:
        log.error("Telegram error: %s", exc)
        return False


def extract_list(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ("results", "data", "tickers", "markets"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                return list(value.values())

    return []


# ============================================================
# BITPIN MARKETS
# ============================================================

def fetch_markets():
    payload = get_json(BASE_URL + "/mkt/markets/")
    markets = extract_list(payload)

    if not markets:
        raise RuntimeError("Bitpin returned no market list.")

    selected = []

    for market in markets:
        if not isinstance(market, dict):
            continue

        base = market.get("currency1", {})
        quote = market.get("currency2", {})

        if not isinstance(base, dict):
            base = {}
        if not isinstance(quote, dict):
            quote = {}

        symbol = (
            market.get("code")
            or market.get("symbol")
            or ""
        )

        quote_code = (
            quote.get("code")
            or market.get("quote")
            or ""
        )

        if not symbol:
            if base.get("code") and quote_code:
                symbol = base["code"] + "_" + quote_code

        if (
            quote_code == "USDT"
            and symbol
            and market.get("tradable", True)
        ):
            selected.append({
                "symbol": symbol,
                "name": market.get("title_fa")
                        or market.get("title")
                        or symbol,
            })

    # Avoid excessive requests and rate limits.
    # Priority: larger, commonly traded spot pairs.
    priority = [
        "BTC_USDT", "ETH_USDT", "SOL_USDT",
        "XRP_USDT", "BNB_USDT", "LINK_USDT",
        "ADA_USDT", "DOGE_USDT", "AVAX_USDT",
        "LTC_USDT", "BCH_USDT", "TRX_USDT",
        "DOT_USDT", "UNI_USDT", "ATOM_USDT",
        "NEAR_USDT", "SUI_USDT", "APT_USDT",
        "ARB_USDT", "OP_USDT", "FIL_USDT",
        "ETC_USDT", "AAVE_USDT", "ICP_USDT",
        "PEPE_USDT", "SHIB_USDT", "TON_USDT",
        "POL_USDT", "INJ_USDT", "FET_USDT",
    ]

    by_symbol = {m["symbol"]: m for m in selected}
    ordered = [by_symbol[s] for s in priority if s in by_symbol]

    for market in selected:
        if market["symbol"] not in {
            m["symbol"] for m in ordered
        }:
            ordered.append(market)

    return ordered[:MAX_MARKETS]


# ============================================================
# CANDLES
# ============================================================

def parse_candle(row):
    """
    Supports common object and array OHLC formats.
    The API response is validated before use.
    """
    if isinstance(row, dict):
        timestamp = num(
            row.get("timestamp", row.get("time", row.get("t")))
        )
        o = num(row.get("open", row.get("o")))
        h = num(row.get("high", row.get("h")))
        l = num(row.get("low", row.get("l")))
        c = num(row.get("close", row.get("c")))
        v = num(row.get("volume", row.get("v", 0)))

    elif isinstance(row, (list, tuple)) and len(row) >= 5:
        timestamp = num(row[0])
        o = num(row[1])
        h = num(row[2])
        l = num(row[3])
        c = num(row[4])
        v = num(row[5]) if len(row) > 5 else 0.0

    else:
        return None

    # Reject malformed and impossible candles.
    if min(o, h, l, c) <= 0:
        return None
    if h < max(o, c, l) or l > min(o, c, h):
        return None

    return {
        "time": timestamp,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
    }


def fetch_candles(symbol, interval):
    """
    Bitpin public API deployments may expose different candle
    routes/parameters. Try known route shapes and validate data.

    If no supported endpoint returns valid OHLC data, fail safely.
    Never fabricate candles or issue a signal from ticker prices.
    """
    routes = [
        (
            BASE_URL + "/mkt/ohlc/" + symbol + "/",
            {"interval": interval},
        ),
        (
            BASE_URL + "/mkt/candles/" + symbol + "/",
            {"interval": interval},
        ),
        (
            BASE_URL + "/mkt/ohlc/",
            {"symbol": symbol, "interval": interval},
        ),
        (
            BASE_URL + "/mkt/candles/",
            {"symbol": symbol, "interval": interval},
        ),
    ]

    errors = []

    for url, params in routes:
        try:
            payload = get_json(url, params)

            if isinstance(payload, dict) and payload.get("error"):
                continue

            rows = extract_list(payload)
            candles = []

            for row in rows:
                candle = parse_candle(row)
                if candle:
                    candles.append(candle)

            candles.sort(key=lambda c: c["time"])

            # Remove duplicate timestamps.
            unique = {}
            for candle in candles:
                unique[candle["time"]] = candle

            candles = list(unique.values())
            candles.sort(key=lambda c: c["time"])

            if len(candles) >= 55:
                return candles

        except Exception as exc:
            errors.append(str(exc)[:100])

    raise RuntimeError(
        "No validated OHLC endpoint found for "
        + symbol + " interval=" + str(interval)
        + ". Check Bitpin candle API documentation. "
        + "; ".join(errors[-2:])
    )


def closed_candles(candles, interval_minutes):
    """
    Exclude the newest candle if its expected closing time
    has not passed. Requires timestamps in seconds or milliseconds.
    """
    if not candles:
        return []

    now = time.time()
    interval_seconds = interval_minutes * 60
    result = []

    for candle in candles:
        ts = candle["time"]

        if ts > 10_000_000_000:
            ts /= 1000.0

        if ts <= 0:
            continue

        # Allow a small delay after the expected candle close.
        if ts + interval_seconds <= now - 2:
            item = dict(candle)
            item["time"] = ts
            result.append(item)

    return result


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    result = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)

    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

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
        return 100.0

    return 100 - 100 / (1 + avg_gain / avg_loss)


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close),
        ))

    return sum(ranges[-period:]) / period


def volume_ratio(candles):
    if len(candles) < 21:
        return 0.0

    baseline = candles[-21:-1]
    average = sum(c["volume"] for c in baseline) / len(baseline)

    if average <= 0:
        return 0.0

    return candles[-1]["volume"] / average


def trend(candles):
    closes = [c["close"] for c in candles]
    fast = ema(closes, 20)
    slow = ema(closes, 50)
    price = closes[-1]

    if fast is None or slow is None:
        return "WAIT"

    if price > fast > slow:
        return "LONG"
    if price < fast < slow:
        return "SHORT"

    return "WAIT"


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def swing_levels(candles, lookback=40):
    sample = candles[-lookback:]
    lows = []
    highs = []

    # Only confirmed local pivots; skip the last two candles.
    for i in range(2, len(sample) - 2):
        current = sample[i]

        if all(
            current["low"] < sample[j]["low"]
            for j in (i - 2, i - 1, i + 1, i + 2)
        ):
            lows.append(current["low"])

        if all(
            current["high"] > sample[j]["high"]
            for j in (i - 2, i - 1, i + 1, i + 2)
        ):
            highs.append(current["high"])

    return lows, highs


def candle_confirmation(previous, current):
    """
    Returns bullish engulfing / bullish rejection,
    or bearish patterns. Candle must already be closed.
    """
    o, h, l, c = (
        current["open"], current["high"],
        current["low"], current["close"]
    )
    po, pc = previous["open"], previous["close"]

    body = abs(c - o)
    candle_range = max(h - l, 1e-12)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)

    bullish_engulfing = (
        pc < po and c > o
        and o <= pc and c >= po
    )

    bearish_engulfing = (
        pc > po and c < o
        and o >= pc and c <= po
    )

    bullish_rejection = (
        c > o
        and lower_wick >= max(body * 1.5, candle_range * 0.30)
        and c >= l + candle_range * 0.60
    )

    bearish_rejection = (
        c < o
        and upper_wick >= max(body * 1.5, candle_range * 0.30)
        and c <= l + candle_range * 0.40
    )

    if bullish_engulfing or bullish_rejection:
        return "BULLISH"
    if bearish_engulfing or bearish_rejection:
        return "BEARISH"

    return "NONE"


# ============================================================
# SIGNAL ANALYSIS: SPOT BUY ONLY
# ============================================================

def analyze_market(market):
    symbol = market["symbol"]

    # Supported intervals must be confirmed against Bitpin API.
    # 15 and 60 are the most common minute-based representations.
    candles_15 = closed_candles(fetch_candles(symbol, 15), 15)
    candles_1h = closed_candles(fetch_candles(symbol, 60), 60)
    candles_4h = closed_candles(fetch_candles(symbol, 240), 240)

    if min(len(candles_15), len(candles_1h), len(candles_4h)) < 55:
        raise RuntimeError("Insufficient closed candles.")

    current = candles_15[-1]
    previous = candles_15[-2]
    price = current["close"]

    support_levels, resistance_levels = swing_levels(candles_1h)

    if not support_levels:
        return {"kind": "WAIT", "symbol": symbol,
                "reason": "حمایت معتبر پیدا نشد"}

    support = max(
        (level for level in support_levels if level <= price * 1.01),
        default=None,
    )

    if support is None:
        return {"kind": "WAIT", "symbol": symbol,
                "reason": "حمایت مناسب زیر قیمت پیدا نشد"}

    distance = (price - support) / support

    # Only watch the support zone; do not chase a distant price.
    if distance < -0.003 or distance > SUPPORT_ZONE_PCT:
        return {"kind": "WAIT", "symbol": symbol,
                "reason": "قیمت در محدوده خرید حمایت نیست"}

    candle_signal = candle_confirmation(previous, current)

    # Need trend confirmation on the two higher timeframes.
    t1h = trend(candles_1h)
    t4h = trend(candles_4h)

    if candle_signal != "BULLISH":
        return {
            "kind": "WATCH",
            "symbol": symbol,
            "price": price,
            "support": support,
            "reason": "نزدیک حمایت؛ کندل صعودی تأیید نشده",
        }

    if t1h != "LONG" or t4h != "LONG":
        return {
            "kind": "WATCH",
            "symbol": symbol,
            "price": price,
            "support": support,
            "reason": "کندل صعودی است اما روند ۱ساعته/۴ساعته تأیید نیست",
        }

    current_rsi = rsi([c["close"] for c in candles_15])
    atr_value = atr(candles_15)
    vol_ratio = volume_ratio(candles_15)

    if not atr_value or atr_value <= 0:
        return {"kind": "WAIT", "symbol": symbol,
                "reason": "ATR معتبر نیست"}

    if current_rsi is None or not 45 <= current_rsi <= 70:
        return {"kind": "WAIT", "symbol": symbol,
                "reason": "RSI برای ورود مناسب نیست"}

    if vol_ratio < 1.0:
        return {"kind": "WAIT", "symbol": symbol,
                "reason": "حجم کندل تأیید کافی نیست"}

    entry = price
    stop = min(
        support * (1 - STOP_BUFFER_PCT),
        entry - atr_value * 1.2,
    )

    if stop <= 0 or stop >= entry:
        return {"kind": "WAIT", "symbol": symbol,
                "reason": "حد ضرر معتبر نیست"}

    risk = entry - stop

    # Spot cash sizing: no leverage.
    risk_budget = CAPITAL_USDT * RISK_PER_TRADE_PCT
    quantity_by_risk = risk_budget / risk
    quantity_by_capital = MARGIN_PER_TRADE / entry
    quantity = min(quantity_by_risk, quantity_by_capital)

    if quantity <= 0:
        return {"kind": "WAIT", "symbol": symbol,
                "reason": "اندازه موقعیت معتبر نیست"}

    resistance_above = sorted(
        level for level in resistance_levels if level > entry
    )

    tp1 = entry + risk
    tp2 = entry + 2 * risk
    tp3 = entry + 3 * risk

    # Do not claim an easy target beyond nearby resistance.
    warning = ""
    if resistance_above and resistance_above[0] < tp2:
        warning = "مقاومت نزدیک؛ اهداف نیازمند بررسی هستند."
        tp1 = min(tp1, resistance_above[0] * 0.997)
        tp2 = max(tp1, entry + 1.5 * risk)
        tp3 = entry + 2 * risk

    score = 62
    if vol_ratio >= 1.5:
        score += 5
    if candle_signal == "BULLISH":
        score += 5
    if current_rsi is not None and 50 <= current_rsi <= 65:
        score += 4

    return {
        "kind": "BUY",
        "symbol": symbol,
        "name": market["name"],
        "score": min(score, 76),
        "entry": entry,
        "support": support,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "quantity": quantity,
        "capital_used": quantity * entry,
        "risk_usdt": quantity * risk,
        "rsi": current_rsi,
        "volume_ratio": vol_ratio,
        "warning": warning,
        "created_at": now_utc(),
        "status": "OPEN",
    }


# ============================================================
# PAPER HISTORY
# ============================================================

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"trades": [], "scan_count": 0}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Invalid history object")
        data.setdefault("trades", [])
        data.setdefault("scan_count", 0)
        return data
    except Exception as exc:
        log.warning("History load failed: %s", exc)
        return {"trades": [], "scan_count": 0}


def save_history(history):
    temp = HISTORY_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    os.replace(temp, HISTORY_FILE)


def update_paper_trades(history):
    for trade in history["trades"]:
        if trade.get("status") != "OPEN":
            continue

        try:
            # Do not invent an exit price if ticker data fails.
            payload = get_json(BASE_URL + "/mkt/tickers/")
            rows = extract_list(payload)

            ticker = next(
                (
                    row for row in rows
                    if isinstance(row, dict)
                    and (
                        row.get("symbol") == trade["symbol"]
                        or row.get("code") == trade["symbol"]
                    )
                ),
                None,
            )

            if not ticker:
                continue

            price = num(ticker.get("price", ticker.get("last")))
            if price <= 0:
                continue

            trade["latest_price"] = price

            if price <= trade["stop"]:
                trade["status"] = "STOPPED"
                trade["exit_price"] = price
                trade["closed_at"] = now_utc()
            elif price >= trade["tp3"]:
                trade["status"] = "TP3"
                trade["exit_price"] = price
                trade["closed_at"] = now_utc()
            elif price >= trade["tp2"]:
                trade["status"] = "TP2"
                trade["exit_price"] = price
                trade["closed_at"] = now_utc()
            elif price >= trade["tp1"]:
                trade["status"] = "TP1"
                trade["exit_price"] = price
                trade["closed_at"] = now_utc()

            if trade.get("status") != "OPEN":
                trade["pnl_usdt"] = (
                    price - trade["entry"]
                ) * trade["quantity"]

        except Exception as exc:
            log.warning(
                "Paper update failed for %s: %s",
                trade["symbol"], exc,
            )


def trade_message(t):
    return (
        f"{BOT_NAME}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🟢 BUY SPOT — تأیید حمایت\n"
        f"🪙 {t['symbol']}\n"
        f"⭐ امتیاز: {t['score']}/100\n"
        f"💵 ورود فرضی: {fmt(t['entry'])}\n"
        f"🧱 حمایت: {fmt(t['support'])}\n"
        f"🛑 حد ضرر: {fmt(t['stop'])}\n"
        f"🎯 TP1: {fmt(t['tp1'])}\n"
        f"🎯 TP2: {fmt(t['tp2'])}\n"
        f"🎯 TP3: {fmt(t['tp3'])}\n"
        f"💰 مصرف سرمایه فرضی: {t['capital_used']:.2f} USDT\n"
        f"📦 مقدار فرضی: {t['quantity']:.8f}\n"
        f"⚠️ ریسک تخمینی: {t['risk_usdt']:.2f} USDT\n"
        f"📊 RSI: {t['rsi']:.1f}\n"
        f"📈 نسبت حجم: {t['volume_ratio']:.2f}x\n"
        f"{t['warning']}\n"
        f"🕒 {t['created_at']}\n"
        f"🧪 PAPER ONLY — سفارش واقعی خاموش"
    )


# ============================================================
# SCAN REPORT
# ============================================================

def scan_market(history):
    markets = fetch_markets()
    update_paper_trades(history)

    signals = []
    watches = []
    errors = 0
    reasons = {}

    for market in markets:
        try:
            result = analyze_market(market)

            if result["kind"] == "BUY":
                signals.append(result)
            elif result["kind"] == "WATCH":
                watches.append(result)
            else:
                reason = result.get("reason", "WAIT")
                reasons[reason] = reasons.get(reason, 0) + 1

        except Exception as exc:
            errors += 1
            log.warning(
                "Market failed: %s | %s",
                market["symbol"], exc,
            )

        time.sleep(0.15)

    signals.sort(
        key=lambda item: item["score"],
        reverse=True,
    )
    signals = signals[:MAX_SIGNALS]

    open_symbols = {
        t["symbol"] for t in history["trades"]
        if t.get("status") == "OPEN"
    }

    open_count = len(open_symbols)
    new_signals = []

    for trade in signals:
        if trade["symbol"] in open_symbols:
            continue
        if open_count >= MAX_SIGNALS:
            break

        history["trades"].append(trade)
        open_symbols.add(trade["symbol"])
        open_count += 1
        new_signals.append(trade)

    history["scan_count"] += 1
    save_history(history)

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        f"📊 BITPIN SPOT USDT | V{VERSION}",
        f"🕒 {now_utc()}",
        f"🔎 بازارهای بررسی‌شده: {len(markets)}",
        f"⚠️ خطاهای تحلیل: {errors}",
        f"🟢 سیگنال خرید جدید: {len(new_signals)}",
        f"👀 بازارهای در انتظار تأیید: {len(watches)}",
        "",
    ]

    if new_signals:
        lines.append("📌 خریدهای تأییدشده:")
        for trade in new_signals:
            lines.append(
                f"• {trade['symbol']} | "
                f"امتیاز {trade['score']} | "
                f"ورود {fmt(trade['entry'])}"
            )
    else:
        lines.append("⚪ فعلاً خرید تأییدشده‌ای وجود ندارد.")

    if watches:
        lines.append("")
        lines.append("👀 WATCH — منتظر تأیید:")
        for item in watches[:5]:
            lines.append(
                f"• {item['symbol']}: {item['reason']}"
            )

    if errors:
        lines.append("")
        lines.append(
            "⚠️ ممکن است endpoint کندل بیت‌پین با این نسخه "
            "سازگار نباشد؛ تا رفع خطا، سیگنال تولید نشده است."
        )

    lines.extend([
        "",
        f"💰 سرمایه کاغذی: {CAPITAL_USDT:.2f} USDT",
        "📈 فقط خرید اسپات؛ بدون شورت و اهرم",
        "🧪 PAPER ONLY | سفارش واقعی خاموش",
    ])

    telegram_send("\n".join(lines))

    for trade in new_signals:
        telegram_send(trade_message(trade))

    return {
        "markets": len(markets),
        "errors": errors,
        "signals": len(new_signals),
        "watches": len(watches),
    }


def build_status(history):
    trades = history.get("trades", [])
    opened = sum(
        1 for t in trades if t.get("status") == "OPEN"
    )
    closed = [t for t in trades if t.get("status") != "OPEN"]

    wins = sum(
        1 for t in closed
        if num(t.get("pnl_usdt")) > 0
    )
    losses = sum(
        1 for t in closed
        if num(t.get("pnl_usdt")) < 0
    )

    if len(closed) >= 30:
        win_rate = f"{wins / len(closed) * 100:.1f}%"
    else:
        win_rate = "داده کافی نیست"

    return (
        f"{BOT_NAME}\n"
        f"📊 نسخه {VERSION} | Bitpin Spot USDT\n"
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
        f"📦 کل معاملات: {len(trades)}\n"
        f"🟢 باز: {opened} | 🏁 بسته: {len(closed)}\n"
        f"✅ برد: {wins} | ❌ باخت: {losses}\n"
        f"📈 نرخ برد: {win_rate}\n"
        f"🧪 سفارش واقعی خاموش"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    log.info("%s V%s starting", BOT_NAME, VERSION)
    history = load_history()

    telegram_send(
        f"{BOT_NAME}\n"
        f"✅ نسخه {VERSION} اجرا شد.\n"
        f"💰 سرمایه کاغذی: {CAPITAL_USDT:.2f} USDT\n"
        "📈 Bitpin Spot USDT\n"
        "🧪 فقط معاملات کاغذی؛ سفارش واقعی خاموش"
    )

    try:
        result = scan_market(history)
        log.info("Scan result: %s", result)

    except Exception as exc:
        log.exception("Scan failed")
        telegram_send(
            f"{BOT_NAME}\n"
            f"❌ اسکن ناموفق بود.\n"
            f"علت: {str(exc)[:700]}\n"
            "هیچ سفارش واقعی ثبت نشده است."
        )


if __name__ == "__main__":
    main()
