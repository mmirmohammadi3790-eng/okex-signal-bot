
# -*- coding: utf-8 -*-
"""
ETH WHALE V5.2
Paper signals only. No real orders.
Kraken public market data.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone

import requests

BOT_NAME = "🐋 ETH WHALE V5.2"
API_URL = "https://api.kraken.com/0/public/OHLC"
HISTORY_FILE = "paper_history.json"

TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)
CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID", "").strip()
    or os.getenv("CHAT_ID", "").strip()
)

CAPITAL = 48.0
LEVERAGE = 3
MARGIN = 16.0
MAX_OPEN = 3
MAX_SIGNALS = 3

MIN_TREND = 55
MIN_SCORE = 55
ATR_MULT = 1.25
MIN_OBSTACLE_PCT = 0.30

# Approximate round-trip cost assumption, not a Kraken fee quote.
# Change this to match the actual fee and slippage assumption.
ROUND_TRIP_COST_PCT = 0.20

MIN_BACKTEST_TRADES = 20
BACKTEST_HORIZON = 12
BACKTEST_TP_R = 1.0

MARKETS = [
    ("BTC", "XBTUSD"),
    ("ETH", "ETHUSD"),
    ("SOL", "SOLUSD"),
    ("XRP", "XRPUSD"),
    ("DOGE", "XDGUSD"),
    ("LINK", "LINKUSD"),
    ("ADA", "ADAUSD"),
    ("AVAX", "AVAXUSD"),
    ("LTC", "LTCUSD"),
    ("BCH", "BCHUSD"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

S = requests.Session()
S.headers.update({"User-Agent": "ETH-WHALE-PaperBot/5.2"})


def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print(text)
        logging.warning("Telegram credentials are missing.")
        return

    try:
        response = S.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        response.raise_for_status()

        if not response.json().get("ok"):
            logging.error("Telegram did not accept the message.")

    except Exception as exc:
        logging.error("Telegram error: %s", exc)


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"trades": []}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"trades": []}

        data.setdefault("trades", [])
        return data

    except Exception as exc:
        logging.error("History load failed: %s", exc)
        return {"trades": []}


def save_history(history):
    tmp = HISTORY_FILE + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    os.replace(tmp, HISTORY_FILE)


def fetch_candles(pair, interval, limit=200):
    response = S.get(
        API_URL,
        params={"pair": pair, "interval": interval},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("error"):
        raise RuntimeError("; ".join(data["error"]))

    result = data.get("result", {})
    keys = [k for k in result if k != "last"]

    if not keys:
        raise RuntimeError("Kraken returned no candles.")

    candles = []
    interval_seconds = interval * 60
    now = int(time.time())

    for row in result[keys[0]][-limit:]:
        if len(row) < 7:
            continue

        candle = {
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[6]),
        }

        # Only closed candles.
        if candle["time"] + interval_seconds <= now:
            candles.append(candle)

    if len(candles) < 60:
        raise RuntimeError(
            f"Insufficient closed candles: {len(candles)}"
        )

    return candles


def ema(values, period):
    out = [None] * len(values)

    if len(values) < period:
        return out

    current = sum(values[:period]) / period
    out[period - 1] = current
    alpha = 2.0 / (period + 1)

    for i in range(period, len(values)):
        current = values[i] * alpha + current * (1 - alpha)
        out[i] = current

    return out


def rsi(values, period=14):
    out = [None] * len(values)

    if len(values) <= period:
        return out

    gains = []
    losses = []

    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    def value(gain, loss):
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100 - 100 / (1 + gain / loss)

    out[period] = value(avg_gain, avg_loss)

    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (
            avg_gain * (period - 1) + max(change, 0)
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + max(-change, 0)
        ) / period
        out[i] = value(avg_gain, avg_loss)

    return out


def atr(candles, period=14):
    out = [None] * len(candles)
    tr = []

    for i, c in enumerate(candles):
        if i == 0:
            tr.append(c["high"] - c["low"])
        else:
            previous = candles[i - 1]["close"]
            tr.append(max(
                c["high"] - c["low"],
                abs(c["high"] - previous),
                abs(c["low"] - previous),
            ))

    if len(candles) <= period:
        return out

    current = sum(tr[1:period + 1]) / period
    out[period] = current

    for i in range(period + 1, len(candles)):
        current = (current * (period - 1) + tr[i]) / period
        out[i] = current

    return out


def indicators(candles):
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rv = rsi(closes)
    av = atr(candles)

    avg_volume = (
        sum(volumes[-21:-1]) / len(volumes[-21:-1])
        if len(volumes) >= 21 else 0
    )

    return {
        "close": closes[-1],
        "ema20": e20[-1],
        "ema50": e50[-1],
        "rsi": rv[-1],
        "atr": av[-1],
        "volume_ratio": (
            volumes[-1] / avg_volume if avg_volume > 0 else 0
        ),
        "candle": candles[-1],
    }


def direction(ind):
    if ind["ema20"] is None or ind["ema50"] is None:
        return "WAIT"

    if ind["ema20"] > ind["ema50"] and ind["close"] > ind["ema20"]:
        return "LONG"

    if ind["ema20"] < ind["ema50"] and ind["close"] < ind["ema20"]:
        return "SHORT"

    return "WAIT"


def trend_score(m15, h1, h4, side):
    score = 0
    reasons = []

    if direction(h1) == side:
        score += 30
        reasons.append("تأیید روند ۱ساعته")

    if direction(m15) == side:
        score += 25
        reasons.append("تأیید روند ۱۵دقیقه")

    r = h1["rsi"]

    if r is not None:
        if side == "LONG" and 45 <= r <= 68:
            score += 15
            reasons.append("RSI مناسب خرید")
        elif side == "SHORT" and 32 <= r <= 55:
            score += 15
            reasons.append("RSI مناسب فروش")

    if h1["volume_ratio"] >= 1.05:
        score += 15
        reasons.append("حجم تأییدکننده")

    candle = h1["candle"]

    if side == "LONG" and candle["close"] > candle["open"]:
        score += 15
        reasons.append("کندل صعودی بسته‌شده")
    elif side == "SHORT" and candle["close"] < candle["open"]:
        score += 15
        reasons.append("کندل نزولی بسته‌شده")

    if direction(h4) == side:
        score += 5
        reasons.append("هم‌جهتی ۴ساعته")

    return min(score, 100), reasons


def obstacle_check(candles, price, side):
    recent = candles[-40:]

    if side == "LONG":
        levels = [c["high"] for c in recent if c["high"] > price]
        if levels:
            distance = (min(levels) - price) / price * 100
            if distance < MIN_OBSTACLE_PCT:
                return f"مقاومت نزدیک: {distance:.2f}%"

    else:
        levels = [c["low"] for c in recent if c["low"] < price]
        if levels:
            distance = (price - max(levels)) / price * 100
            if distance < MIN_OBSTACLE_PCT:
                return f"حمایت نزدیک: {distance:.2f}%"

    return None


def analyze(market):
    name, pair = market

    c15 = fetch_candles(pair, 15, 200)
    time.sleep(0.2)
    c1 = fetch_candles(pair, 60, 200)
    time.sleep(0.2)
    c4 = fetch_candles(pair, 240, 100)

    m15, h1, h4 = indicators(c15), indicators(c1), indicators(c4)
    side = direction(h1)

    if side == "WAIT":
        return None, "عدم تأیید روند یک‌ساعته"

    score, reasons = trend_score(m15, h1, h4, side)

    if score < MIN_TREND:
        return None, f"قدرت روند {score}/100"

    price = h1["close"]
    av = h1["atr"]
    rv = h1["rsi"]

    if not av or av <= 0 or rv is None:
        return None, "ATR یا RSI نامعتبر"

    if side == "LONG" and not 40 <= rv <= 70:
        return None, "RSI خارج از محدوده خرید"

    if side == "SHORT" and not 30 <= rv <= 60:
        return None, "RSI خارج از محدوده فروش"

    obstacle = obstacle_check(c1, price, side)
    if obstacle:
        return None, obstacle

    stop_distance = ATR_MULT * av

    if side == "LONG":
        stop = price - stop_distance
        targets = [
            price + stop_distance * 1.0,
            price + stop_distance * 1.6,
            price + stop_distance * 2.2,
        ]
    else:
        stop = price + stop_distance
        targets = [
            price - stop_distance * 1.0,
            price - stop_distance * 1.6,
            price - stop_distance * 2.2,
        ]

    volume_score = min(100, int(h1["volume_ratio"] * 50))
    signal_score = int(score * 0.75 + volume_score * 0.25)

    if signal_score < MIN_SCORE:
        return None, f"امتیاز سیگنال {signal_score}/100"

    return {
        "id": f"{name}-{c1[-1]['time']}-{side}",
        "symbol": name,
        "pair": pair,
        "direction": side,
        "entry": price,
        "stop": stop,
        "tp1": targets[0],
        "tp2": targets[1],
        "tp3": targets[2],
        "trend_score": score,
        "signal_score": signal_score,
        "rsi": rv,
        "volume_ratio": h1["volume_ratio"],
        "reasons": reasons,
        "candle_time": c1[-1]["time"],
        "margin": MARGIN,
        "position_value": MARGIN * LEVERAGE,
    }, "سیگنال معتبر"


# ------------------------------------------------------------
# Historical test: simple 1h EMA/RSI backtest.
# Assumes TP1 = 1R and conservative stop-first handling.
# ------------------------------------------------------------

def historical_backtest(candles):
    closes = [c["close"] for c in candles]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rv = rsi(closes)
    av = atr(candles)

    results = []
    i = 50

    while i < len(candles) - BACKTEST_HORIZON:
        price = closes[i]

        if None in (e20[i], e50[i], rv[i], av[i]) or av[i] <= 0:
            i += 1
            continue

        side = "WAIT"

        if e20[i] > e50[i] and price > e20[i] and 40 <= rv[i] <= 68:
            side = "LONG"
        elif e20[i] < e50[i] and price < e20[i] and 32 <= rv[i] <= 60:
            side = "SHORT"

        if side == "WAIT":
            i += 1
            continue

        risk = ATR_MULT * av[i]
        target_r = BACKTEST_TP_R
        outcome = None

        for j in range(i + 1, min(i + BACKTEST_HORIZON + 1, len(candles))):
            c = candles[j]

            if side == "LONG":
                stop_hit = c["low"] <= price - risk
                target_hit = c["high"] >= price + risk * target_r
            else:
                stop_hit = c["high"] >= price + risk
                target_hit = c["low"] <= price - risk * target_r

            if stop_hit:
                outcome = -1.0
                break

            if target_hit:
                outcome = target_r
                break

        if outcome is not None:
            # Approximate round-trip cost converted to R.
            fee_r = (
                ROUND_TRIP_COST_PCT / 100 * price / risk
            )
            results.append(outcome - fee_r)
            i += BACKTEST_HORIZON
        else:
            i += 1

    if not results:
        return {"trades": 0, "wins": 0, "losses": 0,
                "win_rate": None, "expectancy_r": None,
                "profit_factor": None, "max_dd_r": None}

    wins = sum(1 for x in results if x > 0)
    losses = len(results) - wins
    positive = sum(x for x in results if x > 0)
    negative = abs(sum(x for x in results if x < 0))

    equity = 0.0
    peak = 0.0
    max_dd = 0.0

    for value in results:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "trades": len(results),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(results) * 100,
        "expectancy_r": sum(results) / len(results),
        "profit_factor": positive / negative if negative else None,
        "max_dd_r": max_dd,
    }


def run_backtests():
    combined = []

    for name, pair in MARKETS:
        try:
            candles = fetch_candles(pair, 60, 700)
            result = historical_backtest(candles)
            # Combine individual market results by using each
            # completed trade's aggregate metrics as a weighted
            # approximation only. Do not fabricate trade records.
            combined.append(result)
        except Exception as exc:
            logging.warning("Backtest %s failed: %s", name, exc)

        time.sleep(0.2)

    total_trades = sum(x["trades"] for x in combined)
    total_wins = sum(x["wins"] for x in combined)
    total_losses = sum(x["losses"] for x in combined)

    # These metrics are weighted/aggregated from per-market tests.
    weighted_expectancy = None
    if total_trades:
        weighted_expectancy = sum(
            x["expectancy_r"] * x["trades"]
            for x in combined if x["expectancy_r"] is not None
        ) / total_trades

    pf_values = [
        x["profit_factor"] for x in combined
        if x["profit_factor"] is not None
    ]

    return {
        "trades": total_trades,
        "wins": total_wins,
        "losses": total_losses,
        "win_rate": (
            total_wins / total_trades * 100
            if total_trades else None
        ),
        "expectancy_r": weighted_expectancy,
        "profit_factor": (
            sum(pf_values) / len(pf_values) if pf_values else None
        ),
        "max_dd_r": max(
            (x["max_dd_r"] or 0 for x in combined),
            default=0,
        ),
    }


# ------------------------------------------------------------
# Paper tracking
# Each paper trade exits at its first target or stop.
# This keeps closed-trade statistics easy to interpret.
# ------------------------------------------------------------

def close_trade(trade, price, result):
    entry = trade["entry"]
    notional = trade["position_value"]

    if trade["direction"] == "LONG":
        gross = (price - entry) / entry * notional
    else:
        gross = (entry - price) / entry * notional

    estimated_cost = notional * ROUND_TRIP_COST_PCT / 100

    trade["status"] = "CLOSED"
    trade["result"] = result
    trade["exit_price"] = price
    trade["pnl_usdt"] = round(gross - estimated_cost, 4)
    trade["closed_at"] = datetime.now(timezone.utc).isoformat()


def update_paper(history):
    changed = False
    pairs = {name: pair for name, pair in MARKETS}

    for trade in history["trades"]:
        if trade.get("status") != "OPEN":
            continue

        try:
            candles = fetch_candles(pairs[trade["symbol"]], 60, 100)

            for c in candles:
                if c["time"] <= int(trade["last_checked"]):
                    continue

                if trade["direction"] == "LONG":
                    stop_hit = c["low"] <= trade["stop"]
                    tp_hit = c["high"] >= trade["tp1"]
                else:
                    stop_hit = c["high"] >= trade["stop"]
                    tp_hit = c["low"] <= trade["tp1"]

                # Conservative if stop and target are hit in same candle.
                if stop_hit:
                    close_trade(trade, trade["stop"], "LOSS")
                    changed = True
                    break

                if tp_hit:
                    close_trade(trade, trade["tp1"], "WIN")
                    changed = True
                    break

                trade["last_checked"] = c["time"]
                changed = True

        except Exception as exc:
            logging.warning("Paper update %s: %s", trade["symbol"], exc)

        time.sleep(0.2)

    if changed:
        save_history(history)


def register_paper_trade(signal, history):
    trades = history["trades"]

    # Prevent the same signal from being registered repeatedly,
    # even if the previous trade has already closed.
    if any(t.get("id") == signal["id"] for t in trades):
        return False

    opened = [t for t in trades if t.get("status") == "OPEN"]

    if len(opened) >= MAX_OPEN:
        return False

    trades.append({
        "id": signal["id"],
        "symbol": signal["symbol"],
        "direction": signal["direction"],
        "entry": signal["entry"],
        "stop": signal["stop"],
        "tp1": signal["tp1"],
        "tp2": signal["tp2"],
        "tp3": signal["tp3"],
        "margin": signal["margin"],
        "position_value": signal["position_value"],
        "status": "OPEN",
        "result": None,
        "pnl_usdt": None,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "last_checked": signal["candle_time"],
    })

    save_history(history)
    return True


def paper_stats(history):
    closed = [
        t for t in history["trades"]
        if t.get("status") == "CLOSED"
    ]
    opened = [
        t for t in history["trades"]
        if t.get("status") == "OPEN"
    ]

    wins = sum(t.get("result") == "WIN" for t in closed)
    losses = sum(t.get("result") == "LOSS" for t in closed)
    pnl = sum(float(t.get("pnl_usdt") or 0) for t in closed)

    equity = CAPITAL
    peak = CAPITAL
    max_dd = 0.0

    for t in sorted(closed, key=lambda x: x.get("closed_at", "")):
        equity += float(t.get("pnl_usdt") or 0)
        peak = max(peak, equity)

        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)

    return {
        "closed": len(closed),
        "opened": len(opened),
        "wins": wins,
        "losses": losses,
        "pnl": pnl,
        "win_rate": wins / len(closed) * 100 if closed else None,
        "max_dd": max_dd,
    }


def fmt_price(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.7f}".rstrip("0").rstrip(".")


def signal_message(s, index):
    side = "🟢 LONG" if s["direction"] == "LONG" else "🔴 SHORT"

    return (
        f"🐋 ETH WHALE V5.2\n"
        f"سیگنال برتر #{index}: {s['symbol']}\n"
        f"{side}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 ورود فرضی: {fmt_price(s['entry'])}\n"
        f"🛑 حد ضرر: {fmt_price(s['stop'])}\n"
        f"✅ TP1: {fmt_price(s['tp1'])}\n"
        f"✅ TP2: {fmt_price(s['tp2'])}\n"
        f"✅ TP3: {fmt_price(s['tp3'])}\n"
        f"📊 قدرت تأیید روند: {s['trend_score']}/100\n"
        f"🧮 امتیاز سیگنال: {s['signal_score']}/100\n"
        f"📈 RSI: {s['rsi']:.1f}\n"
        f"📦 نسبت حجم: {s['volume_ratio']:.2f}x\n"
        f"💵 مارجین فرضی: {MARGIN:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"💰 ارزش فرضی موقعیت: {MARGIN * LEVERAGE:.2f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        + "\n".join("• " + r for r in s["reasons"])
        + "\n🚫 سفارش واقعی: خاموش"
    )


def main():
    logging.info("Starting %s", BOT_NAME)
    history = load_history()
    update_paper(history)

    candidates = []
    rejected = {}
    errors = 0

    for name, pair in MARKETS:
        try:
            signal, reason = analyze((name, pair))

            if signal:
                candidates.append(signal)
                logging.info(
                    "%s %s trend=%s score=%s",
                    name, signal["direction"],
                    signal["trend_score"], signal["signal_score"],
                )
            else:
                rejected[reason] = rejected.get(reason, 0) + 1
                logging.info("%s skipped: %s", name, reason)

        except Exception as exc:
            errors += 1
            rejected["خطای دریافت/تحلیل داده"] = (
                rejected.get("خطای دریافت/تحلیل داده", 0) + 1
            )
            logging.error("%s failed: %s", name, exc)

        time.sleep(0.25)

    candidates.sort(
        key=lambda s: (s["trend_score"], s["signal_score"]),
        reverse=True,
    )
    signals = candidates[:MAX_SIGNALS]

    for signal in signals:
        register_paper_trade(signal, history)

    save_history(history)

    bt = run_backtests()
    stats = paper_stats(history)

    lines = [
        "🐋 ETH WHALE V5.2",
        "━━━━━━━━━━━━━━━━━━",
        "📊 SMART MARKET WATCH",
        "🧪 PAPER TRADING ONLY",
        "🚫 سفارش واقعی: خاموش",
        f"🕒 {now_text()}",
        "━━━━━━━━━━━━━━━━━━",
        (
            f"✅ سیگنال‌های واجد شرایط: {len(signals)}"
            if signals else
            "⚪ WAIT — سیگنال واجد شرایط پیدا نشد"
        ),
        "سیگنال ضعیف برای تکمیل سهمیه ساخته نمی‌شود.",
        "",
        f"🔎 بازارهای بررسی‌شده: {len(MARKETS)}",
        f"⚠️ خطاهای دریافت/تحلیل: {errors}",
        f"🎚 حداقل قدرت روند: {MIN_TREND}/100",
        f"🎚 حداقل امتیاز سیگنال: {MIN_SCORE}/100",
        "",
        "📉 دلایل اصلی رد بازارها:",
    ]

    if rejected:
        for reason, count in sorted(
            rejected.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]:
            lines.append(f"• {reason}: {count}")
    else:
        lines.append("• موردی ثبت نشد")

    lines.extend(["", "🧪 آزمون تاریخی ساده ۱ساعته:"])

    if bt["trades"] >= MIN_BACKTEST_TRADES:
        lines.append(f"نرخ برد پس از هزینه فرضی: {bt['win_rate']:.1f}%")
        lines.append(f"معاملات آزمون: {bt['trades']}")
        lines.append(
            "میانگین نتیجه: "
            f"{bt['expectancy_r']:+.3f}R در هر معامله"
        )
        lines.append(
            "Profit Factor تجمیعیِ تقریبی: "
            + (
                f"{bt['profit_factor']:.2f}"
                if bt["profit_factor"] is not None
                else "نامشخص"
            )
        )
        lines.append(
            f"بیشترین افت تجمعی در آزمون هر بازار: "
            f"{bt['max_dd_r']:.2f}R"
        )
        lines.append(
            "⚠️ آزمون ساده است؛ نرخ برد آینده را تضمین نمی‌کند."
        )
    else:
        lines.append(
            f"نرخ برد: تأییدنشده؛ {bt['trades']} معامله آزمون "
            f"(حداقل {MIN_BACKTEST_TRADES})"
        )

    lines.extend([
        "",
        "📒 معاملات آزمایشی ثبت‌شده:",
    ])

    if stats["closed"] >= MIN_BACKTEST_TRADES:
        lines.append(f"نرخ برد ثبت‌شده: {stats['win_rate']:.1f}%")
    else:
        lines.append(
            f"نرخ برد ثبت‌شده: تأییدنشده؛ {stats['closed']} "
            f"معامله بسته‌شده"
        )

    lines.extend([
        f"معاملات باز: {stats['opened']}",
        f"برد/باخت بسته‌شده: {stats['wins']}/{stats['losses']}",
        f"سود/زیان بسته‌شده پس از هزینه فرضی: {stats['pnl']:+.4f} USDT",
        f"افت سرمایه ثبت‌شده: {stats['max_dd']:.2f}%",
        "",
        f"💰 سرمایه آزمایشی: {CAPITAL:.2f} USDT",
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x",
        f"🧾 هزینه رفت‌وبرگشت فرضی: {ROUND_TRIP_COST_PCT:.2f}%",
        "قدرت روند، احتمال برد نیست.",
        "تمام معاملات شبیه‌سازی هستند.",
    ])

    send_telegram("\n".join(lines))

    for i, signal in enumerate(signals, 1):
        send_telegram(signal_message(signal, i))
        time.sleep(1)

    logging.info("Scan complete.")


if __name__ == "__main__":
    main()
