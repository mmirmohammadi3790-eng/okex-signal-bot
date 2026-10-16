
# -*- coding: utf-8 -*-
"""
🐋 ETH WHALE V5
Balanced Market Scanner + Trend Confirmation + Backtest
MAX 3 SIGNALS | PAPER ONLY | NO REAL ORDERS

GitHub Secrets:
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID

Dependency: requests
"""

import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

import requests

# ==================== SETTINGS ====================

BOT_NAME = "🐋 ETH WHALE"
BASE_URL = "https://api.kraken.com/0/public"

MAX_SIGNALS = 3
MIN_SIGNAL_SCORE = 62
MIN_TREND_STRENGTH = 58

MIN_BACKTEST_TRADES = 20
BACKTEST_HORIZON = 12
BACKTEST_BARS = 250

HISTORY_FILE = Path("paper_history.json")
TIMEOUT = 20

MARKETS = [
    ("BTC/USD", "XBTUSD"),
    ("ETH/USD", "ETHUSD"),
    ("SOL/USD", "SOLUSD"),
    ("XRP/USD", "XRPUSD"),
    ("DOGE/USD", "XDGUSD"),
    ("LINK/USD", "LINKUSD"),
    ("ADA/USD", "ADAUSD"),
    ("AVAX/USD", "AVAXUSD"),
    ("LTC/USD", "LTCUSD"),
    ("BCH/USD", "BCHUSD"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "ETH-WHALE-PaperBot/5.0"})


# ==================== GENERAL ====================

def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def price_text(value):
    value = num(value)
    if abs(value) >= 1000:
        return f"${value:,.2f}"
    if abs(value) >= 1:
        return f"${value:,.4f}"
    return f"${value:.6f}"


def telegram_send(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        logging.warning("Telegram secrets missing.")
        print(message)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        response = HTTP.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        data = response.json()
        if not data.get("ok"):
            logging.error("Telegram error: %s", data)
            return False

        return True

    except Exception as exc:
        logging.error("Telegram send error: %s", exc)
        return False


# ==================== KRAKEN CANDLES ====================

def get_candles(pair, interval):
    response = HTTP.get(
        f"{BASE_URL}/OHLC",
        params={"pair": pair, "interval": interval},
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()

    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))

    result = payload.get("result", {})
    key = next((k for k in result if k != "last"), None)

    if not key or not result[key]:
        raise RuntimeError("No candle data")

    candles = []

    for row in result[key]:
        if len(row) < 8:
            continue

        candles.append({
            "time": int(float(row[0])),
            "open": num(row[1]),
            "high": num(row[2]),
            "low": num(row[3]),
            "close": num(row[4]),
            "volume": num(row[6]),
        })

    # Exclude any candle whose interval has not finished.
    now = int(time.time())
    candles = [
        c for c in candles
        if c["time"] + interval * 60 <= now
    ]

    if len(candles) < 60:
        raise RuntimeError(
            f"Insufficient closed candles: {len(candles)}"
        )

    return candles


# ==================== INDICATORS ====================

def ema(values, period):
    if len(values) < period:
        return [None] * len(values)

    output = [None] * (period - 1)
    current = sum(values[:period]) / period
    output.append(current)

    alpha = 2 / (period + 1)

    for value in values[period:]:
        current = alpha * value + (1 - alpha) * current
        output.append(current)

    return output


def rsi(values, period=14):
    output = [None] * len(values)

    if len(values) <= period:
        return output

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def calculate(gain, loss):
        if loss == 0:
            return 100 if gain > 0 else 50
        return 100 - 100 / (1 + gain / loss)

    output[period] = calculate(avg_gain, avg_loss)

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

        output[i + 1] = calculate(avg_gain, avg_loss)

    return output


def atr(candles, period=14):
    tr = []

    for i, candle in enumerate(candles):
        if i == 0:
            value = candle["high"] - candle["low"]
        else:
            previous_close = candles[i - 1]["close"]
            value = max(
                candle["high"] - candle["low"],
                abs(candle["high"] - previous_close),
                abs(candle["low"] - previous_close),
            )

        tr.append(value)

    output = [None] * len(candles)

    if len(tr) < period:
        return output

    current = sum(tr[:period]) / period
    output[period - 1] = current

    for i in range(period, len(tr)):
        current = (
            current * (period - 1) + tr[i]
        ) / period
        output[i] = current

    return output


def volume_ratio(candles, period=20):
    if len(candles) < period + 1:
        return 1.0

    previous = candles[-period - 1:-1]
    average = sum(c["volume"] for c in previous) / len(previous)

    if average <= 0:
        return 1.0

    return candles[-1]["volume"] / average


def indicators(candles):
    closes = [c["close"] for c in candles]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rs = rsi(closes, 14)
    ats = atr(candles, 14)

    return {
        "candles": candles,
        "close": closes[-1],
        "ema20": e20[-1],
        "ema50": e50[-1],
        "rsi": rs[-1],
        "atr": ats[-1],
        "volume_ratio": volume_ratio(candles),
    }


def direction(data):
    if data["ema20"] is None or data["ema50"] is None:
        return "WAIT"

    if (
        data["ema20"] > data["ema50"]
        and data["close"] > data["ema20"]
    ):
        return "LONG"

    if (
        data["ema20"] < data["ema50"]
        and data["close"] < data["ema20"]
    ):
        return "SHORT"

    return "WAIT"


def support_resistance(candles, lookback=30):
    recent = candles[-lookback:]
    current = recent[-1]["close"]

    supports = [
        c["low"] for c in recent
        if c["low"] < current
    ]
    resistances = [
        c["high"] for c in recent
        if c["high"] > current
    ]

    support = max(supports) if supports else min(
        c["low"] for c in recent
    )
    resistance = min(resistances) if resistances else max(
        c["high"] for c in recent
    )

    return support, resistance


# ==================== TREND CONFIRMATION ====================

def trend_confirmation(m15, h1, h4):
    side = direction(h1)
    score = 0
    reasons = []

    if side == "WAIT":
        return 0, side, ["روند یک‌ساعته خنثی است"]

    # 30 points: 1h EMA and price alignment
    score += 30
    reasons.append("هم‌جهتی EMA20 و EMA50 در یک‌ساعته")

    # 25 points: 15m confirmation
    if direction(m15) == side:
        score += 25
        reasons.append("تأیید روند در ۱۵ دقیقه")
    else:
        reasons.append("تایم‌فریم ۱۵ دقیقه تأیید کامل ندارد")

    # 15 points: RSI momentum
    if side == "LONG":
        if 52 <= h1["rsi"] <= 68:
            score += 15
            reasons.append("RSI مناسب روند صعودی")
        elif h1["rsi"] > 50:
            score += 8
    else:
        if 32 <= h1["rsi"] <= 48:
            score += 15
            reasons.append("RSI مناسب روند نزولی")
        elif h1["rsi"] < 50:
            score += 8

    # 15 points: volume confirmation
    if h1["volume_ratio"] >= 1.5:
        score += 15
        reasons.append("حجم قوی")
    elif h1["volume_ratio"] >= 1.1:
        score += 9
        reasons.append("حجم نسبتاً مناسب")
    else:
        reasons.append("حجم ضعیف است")

    # 15 points: last closed 1h candle
    last = h1["candles"][-1]
    body = last["close"] - last["open"]

    if (side == "LONG" and body > 0) or (
        side == "SHORT" and body < 0
    ):
        score += 15
        reasons.append("کندل بسته‌شده هم‌جهت است")
    else:
        reasons.append("کندل اخیر تأیید کامل نمی‌دهد")

    # Bonus confirmation from 4h
    if direction(h4) == side:
        score = min(100, score + 5)
        reasons.append("تأیید اضافه از تایم‌فریم ۴ ساعته")

    return min(score, 100), side, reasons


# ==================== SIGNAL FILTER ====================

def build_signal(symbol, pair, m15, h1, h4):
    trend_score, side, reasons = trend_confirmation(
        m15, h1, h4
    )

    if side == "WAIT":
        return None, "روند خنثی"

    if trend_score < MIN_TREND_STRENGTH:
        return None, "قدرت تأیید روند پایین"

    entry = h1["close"]
    atr_value = h1["atr"] or entry * 0.01

    support, resistance = support_resistance(h1["candles"])

    if side == "LONG":
        if resistance > entry and (
            resistance - entry
        ) / entry < 0.003:
            return None, "مقاومت بیش از حد نزدیک است"

        sl = entry - 1.25 * atr_value
        risk = entry - sl
        tp1 = entry + risk
        tp2 = entry + 1.6 * risk
        tp3 = entry + 2.2 * risk

        obstacle_pct = (
            (resistance - entry) / entry * 100
            if resistance > entry else 99
        )

    else:
        if support < entry and (
            entry - support
        ) / entry < 0.003:
            return None, "حمایت بیش از حد نزدیک است"

        sl = entry + 1.25 * atr_value
        risk = sl - entry
        tp1 = entry - risk
        tp2 = entry - 1.6 * risk
        tp3 = entry - 2.2 * risk

        obstacle_pct = (
            (entry - support) / entry * 100
            if support < entry else 99
        )

    # Independent signal score; not win probability.
    score = 25
    score += 20 if direction(m15) == side else 0

    if side == "LONG":
        score += 15 if 52 <= h1["rsi"] <= 68 else (
            8 if h1["rsi"] > 50 else 0
        )
    else:
        score += 15 if 32 <= h1["rsi"] <= 48 else (
            8 if h1["rsi"] < 50 else 0
        )

    score += 15 if h1["volume_ratio"] >= 1.5 else (
        9 if h1["volume_ratio"] >= 1.1 else 0
    )
    score += 15 if obstacle_pct >= 0.8 else (
        8 if obstacle_pct >= 0.5 else 0
    )

    last = h1["candles"][-1]
    if (side == "LONG" and last["close"] > last["open"]) or (
        side == "SHORT" and last["close"] < last["open"]
    ):
        score += 10

    score = min(score, 100)

    if score < MIN_SIGNAL_SCORE:
        return None, "امتیاز سیگنال پایین"

    return {
        "symbol": symbol,
        "pair": pair,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "score": score,
        "trend": trend_score,
        "rsi": h1["rsi"],
        "volume": h1["volume_ratio"],
        "support": support,
        "resistance": resistance,
        "reasons": reasons,
        "candle_time": h1["candles"][-1]["time"],
    }, None


# ==================== HISTORICAL BACKTEST ====================

def backtest(candles):
    """
    Simple 1h historical test.
    Signals use only information available at candle i.
    The following candles determine TP/SL.
    If TP and SL are both touched in the same candle, SL is counted first.
    Kraken's public OHLC endpoint has a limited recent history.
    """

    if len(candles) < 100:
        return {"trades": 0, "wins": 0, "rate": None}

    closes = [c["close"] for c in candles]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rs = rsi(closes, 14)
    ats = atr(candles, 14)

    start = max(55, len(candles) - BACKTEST_BARS - BACKTEST_HORIZON)
    end = len(candles) - BACKTEST_HORIZON

    trades = 0
    wins = 0
    i = start

    while i < end:
        if any(x[i] is None for x in (e20, e50, rs, ats)):
            i += 1
            continue

        if ats[i] <= 0:
            i += 1
            continue

        entry = closes[i]
        side = None

        if e20[i] > e50[i] and entry > e20[i] and rs[i] >= 52:
            side = "LONG"
        elif e20[i] < e50[i] and entry < e20[i] and rs[i] <= 48:
            side = "SHORT"

        if side is None:
            i += 1
            continue

        risk = 1.25 * ats[i]

        if side == "LONG":
            sl = entry - risk
            tp = entry + 1.5 * risk
        else:
            sl = entry + risk
            tp = entry - 1.5 * risk

        outcome = None
        last_j = min(len(candles), i + BACKTEST_HORIZON + 1)
        exit_j = None

        for j in range(i + 1, last_j):
            c = candles[j]

            if side == "LONG":
                hit_sl = c["low"] <= sl
                hit_tp = c["high"] >= tp
            else:
                hit_sl = c["high"] >= sl
                hit_tp = c["low"] <= tp

            if hit_sl:
                outcome = "LOSS"
                exit_j = j
                break

            if hit_tp:
                outcome = "WIN"
                exit_j = j
                break

        if outcome is not None:
            trades += 1
            if outcome == "WIN":
                wins += 1
            i = max(i + 1, exit_j)
        else:
            i += 1

    return {
        "trades": trades,
        "wins": wins,
        "rate": wins / trades * 100 if trades else None,
    }


def backtest_label(result):
    if (
        result["trades"] < MIN_BACKTEST_TRADES
        or result["rate"] is None
    ):
        return (
            "تأییدنشده؛ "
            f"{result['trades']} معامله بک‌تست"
        )

    return (
        f"{result['rate']:.1f}% "
        f"({result['wins']}/{result['trades']} برد در بک‌تست)"
    )


# ==================== PAPER HISTORY ====================

def load_history():
    try:
        if HISTORY_FILE.exists():
            data = json.loads(
                HISTORY_FILE.read_text(encoding="utf-8")
            )
            data.setdefault("open", [])
            data.setdefault("closed", [])
            return data
    except Exception as exc:
        logging.warning("History read error: %s", exc)

    return {"open": [], "closed": []}


def save_history(history):
    try:
        HISTORY_FILE.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logging.error("History save error: %s", exc)


def update_paper_history(history, candle_map):
    remaining = []
    closed = history.get("closed", [])

    for trade in history.get("open", []):
        candles = candle_map.get(trade["pair"])

        if not candles:
            remaining.append(trade)
            continue

        last = candles[-1]

        # Only evaluate a candle newer than the signal candle.
        if last["time"] <= trade.get("last_checked", 0):
            remaining.append(trade)
            continue

        side = trade["side"]
        hit_sl = (
            last["low"] <= trade["sl"]
            if side == "LONG"
            else last["high"] >= trade["sl"]
        )
        hit_tp = (
            last["high"] >= trade["tp1"]
            if side == "LONG"
            else last["low"] <= trade["tp1"]
        )

        # Conservative rule: SL takes priority if both hit.
        if hit_sl:
            trade["outcome"] = "LOSS"
            trade["closed_at"] = last["time"]
            closed.append(trade)
        elif hit_tp:
            trade["outcome"] = "WIN"
            trade["closed_at"] = last["time"]
            closed.append(trade)
        else:
            trade["last_checked"] = last["time"]
            remaining.append(trade)

    history["open"] = remaining
    history["closed"] = closed[-2000:]


def add_paper_signals(history, signals):
    existing = {
        (t["pair"], t["side"])
        for t in history.get("open", [])
    }

    for signal in signals:
        key = (signal["pair"], signal["side"])

        if key in existing:
            continue

        history["open"].append({
            "pair": signal["pair"],
            "symbol": signal["symbol"],
            "side": signal["side"],
            "entry": signal["entry"],
            "sl": signal["sl"],
            "tp1": signal["tp1"],
            "opened_at": int(time.time()),
            "last_checked": signal["candle_time"],
            "mode": "PAPER_ONLY",
        })

        existing.add(key)


def tracked_win_rate(history):
    closed = history.get("closed", [])
    wins = sum(1 for t in closed if t.get("outcome") == "WIN")
    losses = sum(1 for t in closed if t.get("outcome") == "LOSS")
    total = wins + losses

    if total < MIN_BACKTEST_TRADES:
        return (
            f"تأییدنشده؛ {total} معامله بسته‌شده "
            f"(حداقل {MIN_BACKTEST_TRADES})"
        )

    return f"{wins / total * 100:.1f}% ({wins} برد از {total})"


# ==================== TELEGRAM REPORT ====================

def build_report(signals, errors, history, backtests):
    lines = [
        f"<b>{BOT_NAME} V5</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>SMART MARKET WATCH</b>",
        "🧪 <b>PAPER TRADING ONLY</b>",
        f"🕒 {now_text()}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not signals:
        lines += [
            "⚪ <b>WAIT — سیگنال واجد شرایط پیدا نشد</b>",
            "فیلتر متعادل فعال است؛ سیگنال ضعیف به زور اضافه نمی‌شود.",
        ]

    for index, signal in enumerate(signals, 1):
        bt = backtests.get(
            signal["pair"],
            {"trades": 0, "wins": 0, "rate": None},
        )

        icon = "🟢" if signal["side"] == "LONG" else "🔴"

        lines += [
            "",
            f"<b>{index}. {icon} {signal['symbol']} — {signal['side']}</b>",
            f"📍 Entry: <code>{price_text(signal['entry'])}</code>",
            f"🛑 SL: <code>{price_text(signal['sl'])}</code>",
            f"🎯 TP1: <code>{price_text(signal['tp1'])}</code>",
            f"🎯 TP2: <code>{price_text(signal['tp2'])}</code>",
            f"🎯 TP3: <code>{price_text(signal['tp3'])}</code>",
            f"⭐ امتیاز سیگنال: <b>{signal['score']}/100</b>",
            f"💪 قدرت تأیید روند: <b>{signal['trend']}/100</b>",
            f"📊 نرخ برد بک‌تست: <b>{backtest_label(bt)}</b>",
            f"RSI: {signal['rsi']:.1f} | حجم: {signal['volume']:.2f}x",
            f"حمایت: {price_text(signal['support'])}",
            f"مقاومت: {price_text(signal['resistance'])}",
        ]

        for reason in signal["reasons"][:4]:
            lines.append(f"• {reason}")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🧪 <b>آمار معاملات آزمایشی ثبت‌شده</b>",
        f"📈 نرخ برد ثبت‌شده: <b>{tracked_win_rate(history)}</b>",
        f"📂 موقعیت‌های آزمایشی باز: {len(history.get('open', []))}",
        f"🔎 بازارهای دارای خطا: {len(errors)}",
    ]

    if errors:
        lines.append("⚠️ <b>خطاهای دریافت داده:</b>")
        for error in errors[:4]:
            lines.append(f"• {error}")

    lines += [
        "",
        "⚠️ قدرت روند و امتیاز سیگنال، احتمال برد نیستند.",
        "⚠️ بک‌تست ساده است و تضمین عملکرد آینده نیست.",
        "🚫 هیچ سفارش واقعی ثبت نمی‌شود.",
    ]

    return "\n".join(lines)


# ==================== MAIN SCAN ====================

def main():
    logging.info("Starting ETH WHALE V5")
    market_data = {}
    backtests = {}
    candidates = []
    errors = []

    for symbol, pair in MARKETS:
        try:
            candles15 = get_candles(pair, 15)
            candles1h = get_candles(pair, 60)
            candles4h = get_candles(pair, 240)

            m15 = indicators(candles15)
            h1 = indicators(candles1h)
            h4 = indicators(candles4h)

            market_data[pair] = candles1h
            backtests[pair] = backtest(candles1h)

            signal, reason = build_signal(
                symbol, pair, m15, h1, h4
            )

            if signal:
                candidates.append(signal)
                logging.info(
                    "%s %s score=%s trend=%s",
                    symbol,
                    signal["side"],
                    signal["score"],
                    signal["trend"],
                )
            else:
                logging.info("%s skipped: %s", symbol, reason)

        except Exception as exc:
            errors.append(f"{symbol}: {str(exc)[:100]}")
            logging.warning("Market error %s: %s", symbol, exc)

        time.sleep(0.2)

    # Rank by trend confirmation, then signal score.
    candidates.sort(
        key=lambda s: (s["trend"], s["score"]),
        reverse=True,
    )
    signals = candidates[:MAX_SIGNALS]

    history = load_history()
    update_paper_history(history, market_data)
    add_paper_signals(history, signals)
    save_history(history)

    report = build_report(
        signals, errors, history, backtests
    )
    telegram_send(report)

    logging.info(
        "Finished. signals=%s errors=%s",
        len(signals),
        len(errors),
    )


if __name__ == "__main__":
    main()
