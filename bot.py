# -*- coding: utf-8 -*-
"""
🐋 ETH WHALE V5.1
SMART MARKET WATCH
PAPER TRADING ONLY
NO REAL ORDERS

Timeframes: 15m, 1h, 4h
Indicators: EMA20/EMA50, RSI14, ATR14, Volume
Maximum signals per scan: 3
"""

import os
import json
import time
import logging
from datetime import datetime, timezone

import requests


# ============================================================
# CONFIGURATION
# ============================================================

BOT_NAME = "🐋 ETH WHALE V5.1"

KRAKEN_API = "https://api.kraken.com/0/public/OHLC"

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_TOKEN", "").strip()
)

TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID", "").strip()
    or os.getenv("CHAT_ID", "").strip()
)

# Simulated account only
PAPER_CAPITAL_USDT = 48.0
LEVERAGE = 3
MARGIN_PER_TRADE = 16.0
MAX_OPEN_PAPER_TRADES = 3

# Balanced filters
MIN_TREND_STRENGTH = 55
MIN_SIGNAL_SCORE = 55
MAX_SIGNALS_PER_SCAN = 3

# Risk settings
ATR_STOP_MULTIPLIER = 1.25
TP_R_MULTIPLIERS = [1.0, 1.6, 2.2]

# Reject signals when an obstacle is too close
MIN_OBSTACLE_DISTANCE_PCT = 0.30

# Historical test
MIN_BACKTEST_TRADES = 20
BACKTEST_TP_R = 1.5
BACKTEST_HORIZON = 12

# Markets to scan
MARKETS = [
    {"name": "BTC", "pair": "XBTUSD"},
    {"name": "ETH", "pair": "ETHUSD"},
    {"name": "SOL", "pair": "SOLUSD"},
    {"name": "XRP", "pair": "XRPUSD"},
    {"name": "DOGE", "pair": "XDGUSD"},
    {"name": "LINK", "pair": "LINKUSD"},
    {"name": "ADA", "pair": "ADAUSD"},
    {"name": "AVAX", "pair": "AVAXUSD"},
    {"name": "LTC", "pair": "LTCUSD"},
    {"name": "BCH", "pair": "BCHUSD"},
]

HISTORY_FILE = "paper_history.json"

TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/5.1"
})


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram credentials are missing.")
        print(message)
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = SESSION.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            logging.error("Telegram rejected the message.")
            return False

        return True

    except Exception as exc:
        logging.error("Telegram error: %s", exc)
        return False


# ============================================================
# UTILITIES
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_text():
    return utc_now().strftime("%Y-%m-%d %H:%M UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pct_change(a, b):
    if not b:
        return 0.0
    return (a - b) / b * 100.0


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"trades": []}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return {"trades": []}

        if not isinstance(data.get("trades"), list):
            data["trades"] = []

        return data

    except Exception as exc:
        logging.error("Could not read paper history: %s", exc)
        return {"trades": []}


def save_history(history):
    temp_file = HISTORY_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                history,
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(temp_file, HISTORY_FILE)

    except Exception as exc:
        logging.error("Could not save paper history: %s", exc)


# ============================================================
# KRAKEN MARKET DATA
# ============================================================

def fetch_candles(pair, interval, limit=200):
    params = {
        "pair": pair,
        "interval": interval,
    }

    response = SESSION.get(
        KRAKEN_API,
        params=params,
        timeout=20,
    )

    response.raise_for_status()
    data = response.json()

    errors = data.get("error", [])

    if errors:
        raise RuntimeError("; ".join(errors))

    result = data.get("result", {})

    pair_keys = [
        key for key in result.keys()
        if key != "last"
    ]

    if not pair_keys:
        raise RuntimeError("No candle data returned by Kraken")

    raw = result[pair_keys[0]]

    candles = []

    for row in raw[-limit:]:
        if len(row) < 7:
            continue

        candles.append({
            "time": int(row[0]),
            "open": safe_float(row[1]),
            "high": safe_float(row[2]),
            "low": safe_float(row[3]),
            "close": safe_float(row[4]),
            "volume": safe_float(row[6]),
        })

    # Do not analyze a candle that has not closed yet.
    now_ts = int(time.time())
    interval_seconds = interval * 60

    candles = [
        candle for candle in candles
        if candle["time"] + interval_seconds <= now_ts
    ]

    if len(candles) < 60:
        raise RuntimeError(
            "Not enough closed candles: " + str(len(candles))
        )

    return candles


# ============================================================
# INDICATORS
# ============================================================

def ema_series(values, period):
    if len(values) < period:
        return [None] * len(values)

    output = [None] * len(values)

    initial = sum(values[:period]) / period
    output[period - 1] = initial

    multiplier = 2.0 / (period + 1.0)
    previous = initial

    for index in range(period, len(values)):
        previous = (
            values[index] * multiplier
            + previous * (1.0 - multiplier)
        )
        output[index] = previous

    return output


def rsi_series(values, period=14):
    output = [None] * len(values)

    if len(values) <= period:
        return output

    gains = []
    losses = []

    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    def calculate_rsi(avg_gain, avg_loss):
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    output[period] = calculate_rsi(
        average_gain,
        average_loss,
    )

    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]

        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        average_gain = (
            average_gain * (period - 1) + gain
        ) / period

        average_loss = (
            average_loss * (period - 1) + loss
        ) / period

        output[index] = calculate_rsi(
            average_gain,
            average_loss,
        )

    return output


def atr_series(candles, period=14):
    output = [None] * len(candles)

    if len(candles) <= period:
        return output

    true_ranges = []

    for index, candle in enumerate(candles):
        if index == 0:
            tr = candle["high"] - candle["low"]
        else:
            previous_close = candles[index - 1]["close"]

            tr = max(
                candle["high"] - candle["low"],
                abs(candle["high"] - previous_close),
                abs(candle["low"] - previous_close),
            )

        true_ranges.append(tr)

    current = sum(true_ranges[1:period + 1]) / period
    output[period] = current

    for index in range(period + 1, len(candles)):
        current = (
            current * (period - 1)
            + true_ranges[index]
        ) / period

        output[index] = current

    return output


def indicator_pack(candles):
    closes = [c["close"] for c in candles]

    ema20 = ema_series(closes, 20)
    ema50 = ema_series(closes, 50)
    rsi14 = rsi_series(closes, 14)
    atr14 = atr_series(candles, 14)

    volumes = [c["volume"] for c in candles]

    if len(volumes) >= 21:
        previous_volumes = volumes[-21:-1]
        average_volume = (
            sum(previous_volumes) / len(previous_volumes)
        )
    else:
        average_volume = 0.0

    volume_ratio = (
        volumes[-1] / average_volume
        if average_volume > 0
        else 0.0
    )

    return {
        "close": closes[-1],
        "ema20": ema20[-1],
        "ema50": ema50[-1],
        "rsi": rsi14[-1],
        "atr": atr14[-1],
        "volume_ratio": volume_ratio,
        "last_candle": candles[-1],
    }


# ============================================================
# TREND ANALYSIS
# ============================================================

def direction(indicators):
    if (
        indicators["ema20"] is None
        or indicators["ema50"] is None
    ):
        return "WAIT"

    price = indicators["close"]

    if (
        indicators["ema20"] > indicators["ema50"]
        and price > indicators["ema20"]
    ):
        return "LONG"

    if (
        indicators["ema20"] < indicators["ema50"]
        and price < indicators["ema20"]
    ):
        return "SHORT"

    return "WAIT"


def trend_confirmation(m15, h1, h4, desired_direction):
    score = 0
    reasons = []

    d15 = direction(m15)
    d1 = direction(h1)
    d4 = direction(h4)

    if d1 == desired_direction:
        score += 30
        reasons.append("تأیید روند ۱ساعته")

    if d15 == desired_direction:
        score += 25
        reasons.append("تأیید روند ۱۵دقیقه")

    rsi_value = h1["rsi"]

    if rsi_value is not None:
        if (
            desired_direction == "LONG"
            and 45 <= rsi_value <= 68
        ):
            score += 15
            reasons.append("RSI مناسب خرید")

        elif (
            desired_direction == "SHORT"
            and 32 <= rsi_value <= 55
        ):
            score += 15
            reasons.append("RSI مناسب فروش")

    if h1["volume_ratio"] >= 1.05:
        score += 15
        reasons.append("حجم تأییدکننده")

    candle = h1["last_candle"]

    if (
        desired_direction == "LONG"
        and candle["close"] > candle["open"]
    ):
        score += 15
        reasons.append("کندل صعودی بسته‌شده")

    elif (
        desired_direction == "SHORT"
        and candle["close"] < candle["open"]
    ):
        score += 15
        reasons.append("کندل نزولی بسته‌شده")

    if d4 == desired_direction:
        score += 5
        reasons.append("هم‌جهتی ۴ساعته")

    return min(score, 100), reasons


# ============================================================
# SUPPORT / RESISTANCE FILTER
# ============================================================

def nearby_obstacle(candles, price, trade_direction):
    recent = candles[-40:]

    if trade_direction == "LONG":
        resistance_levels = [
            c["high"] for c in recent
            if c["high"] > price
        ]

        if resistance_levels:
            resistance = min(resistance_levels)
            distance = pct_change(resistance, price)

            if distance < MIN_OBSTACLE_DISTANCE_PCT:
                return True, (
                    "مقاومت نزدیک؛ فاصله "
                    + format(distance, ".2f")
                    + "%"
                )

    elif trade_direction == "SHORT":
        support_levels = [
            c["low"] for c in recent
            if c["low"] < price
        ]

        if support_levels:
            support = max(support_levels)
            distance = abs(pct_change(support, price))

            if distance < MIN_OBSTACLE_DISTANCE_PCT:
                return True, (
                    "حمایت نزدیک؛ فاصله "
                    + format(distance, ".2f")
                    + "%"
                )

    return False, ""


# ============================================================
# SIGNAL GENERATION
# ============================================================

def analyze_market(market):
    name = market["name"]
    pair = market["pair"]

    candles_15m = fetch_candles(pair, 15, 200)
    time.sleep(0.2)

    candles_1h = fetch_candles(pair, 60, 200)
    time.sleep(0.2)

    candles_4h = fetch_candles(pair, 240, 100)

    m15 = indicator_pack(candles_15m)
    h1 = indicator_pack(candles_1h)
    h4 = indicator_pack(candles_4h)

    trade_direction = direction(h1)

    if trade_direction == "WAIT":
        return None, "عدم تأیید روند یک‌ساعته"

    if direction(m15) != trade_direction:
        # Keep the setup for scoring, but it must pass the threshold.
        pass

    trend_score, reasons = trend_confirmation(
        m15,
        h1,
        h4,
        trade_direction,
    )

    if trend_score < MIN_TREND_STRENGTH:
        return None, (
            "قدرت روند "
            + str(trend_score)
            + "/100؛ کمتر از حداقل "
            + str(MIN_TREND_STRENGTH)
        )

    price = h1["close"]
    atr = h1["atr"]
    rsi_value = h1["rsi"]

    if not price or not atr or atr <= 0:
        return None, "اطلاعات ATR یا قیمت معتبر نیست"

    blocked, obstacle_reason = nearby_obstacle(
        candles_1h,
        price,
        trade_direction,
    )

    if blocked:
        return None, obstacle_reason

    if trade_direction == "LONG":
        if rsi_value is None or not 40 <= rsi_value <= 70:
            return None, "RSI خارج از محدوده خرید"

        entry = price
        stop_loss = entry - ATR_STOP_MULTIPLIER * atr
        risk = entry - stop_loss

        tp1 = entry + risk * TP_R_MULTIPLIERS[0]
        tp2 = entry + risk * TP_R_MULTIPLIERS[1]
        tp3 = entry + risk * TP_R_MULTIPLIERS[2]

    else:
        if rsi_value is None or not 30 <= rsi_value <= 60:
            return None, "RSI خارج از محدوده فروش"

        entry = price
        stop_loss = entry + ATR_STOP_MULTIPLIER * atr
        risk = stop_loss - entry

        tp1 = entry - risk * TP_R_MULTIPLIERS[0]
        tp2 = entry - risk * TP_R_MULTIPLIERS[1]
        tp3 = entry - risk * TP_R_MULTIPLIERS[2]

    volume_component = min(
        100,
        max(0, int(h1["volume_ratio"] * 50)),
    )

    signal_score = int(
        trend_score * 0.75
        + volume_component * 0.25
    )

    if signal_score < MIN_SIGNAL_SCORE:
        return None, (
            "امتیاز سیگنال "
            + str(signal_score)
            + "؛ کمتر از حداقل "
            + str(MIN_SIGNAL_SCORE)
        )

    position_value = MARGIN_PER_TRADE * LEVERAGE

    return {
        "symbol": name,
        "pair": pair,
        "direction": trade_direction,
        "entry": entry,
        "stop": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "trend_score": trend_score,
        "signal_score": signal_score,
        "rsi": rsi_value,
        "volume_ratio": h1["volume_ratio"],
        "reasons": reasons,
        "candle_time": candles_1h[-1]["time"],
        "position_value": position_value,
        "margin": MARGIN_PER_TRADE,
    }, "سیگنال معتبر"


# ============================================================
# SIMPLE HISTORICAL TEST
# ============================================================

def historical_backtest(candles):
    """
    Simplified 1h historical test.
    Not a guarantee of future performance.
    Does not include fees, slippage, or funding.
    """

    closes = [c["close"] for c in candles]
    ema20 = ema_series(closes, 20)
    ema50 = ema_series(closes, 50)
    rsi_values = rsi_series(closes, 14)
    atr_values = atr_series(candles, 14)

    wins = 0
    losses = 0
    trades = 0

    index = 50

    while index < len(candles) - BACKTEST_HORIZON:
        close = closes[index]
        e20 = ema20[index]
        e50 = ema50[index]
        rsi_value = rsi_values[index]
        atr_value = atr_values[index]

        if (
            e20 is None
            or e50 is None
            or rsi_value is None
            or atr_value is None
            or atr_value <= 0
        ):
            index += 1
            continue

        trade_direction = "WAIT"

        if e20 > e50 and close > e20 and 40 <= rsi_value <= 68:
            trade_direction = "LONG"

        elif e20 < e50 and close < e20 and 32 <= rsi_value <= 60:
            trade_direction = "SHORT"

        if trade_direction == "WAIT":
            index += 1
            continue

        entry = close
        risk = ATR_STOP_MULTIPLIER * atr_value

        if trade_direction == "LONG":
            stop = entry - risk
            target = entry + risk * BACKTEST_TP_R
        else:
            stop = entry + risk
            target = entry - risk * BACKTEST_TP_R

        outcome = None

        for future_index in range(
            index + 1,
            min(
                index + BACKTEST_HORIZON + 1,
                len(candles),
            ),
        ):
            candle = candles[future_index]

            if trade_direction == "LONG":
                stop_hit = candle["low"] <= stop
                target_hit = candle["high"] >= target
            else:
                stop_hit = candle["high"] >= stop
                target_hit = candle["low"] <= target

            # Conservative handling if both are hit in one candle.
            if stop_hit:
                outcome = "LOSS"
                break

            if target_hit:
                outcome = "WIN"
                break

        if outcome is not None:
            trades += 1

            if outcome == "WIN":
                wins += 1
            else:
                losses += 1

            index += BACKTEST_HORIZON
        else:
            index += 1

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
    }


def run_historical_tests():
    total = {
        "trades": 0,
        "wins": 0,
        "losses": 0,
    }

    errors = 0

    for market in MARKETS:
        try:
            candles = fetch_candles(
                market["pair"],
                60,
                700,
            )

            result = historical_backtest(candles)

            total["trades"] += result["trades"]
            total["wins"] += result["wins"]
            total["losses"] += result["losses"]

        except Exception as exc:
            errors += 1
            logging.warning(
                "Backtest failed for %s: %s",
                market["name"],
                exc,
            )

        time.sleep(0.2)

    return total, errors


# ============================================================
# PAPER TRADE TRACKING
# ============================================================

def open_paper_trade(signal, history):
    trades = history.setdefault("trades", [])

    active = [
        trade for trade in trades
        if trade.get("status") == "OPEN"
    ]

    # Avoid duplicate open trades for the same market/direction.
    for trade in active:
        if (
            trade.get("symbol") == signal["symbol"]
            and trade.get("direction") == signal["direction"]
        ):
            return False

    if len(active) >= MAX_OPEN_PAPER_TRADES:
        return False

    trade = {
        "id": (
            signal["symbol"]
            + "-"
            + str(signal["candle_time"])
            + "-"
            + signal["direction"]
        ),
        "symbol": signal["symbol"],
        "direction": signal["direction"],
        "entry": signal["entry"],
        "stop": signal["stop"],
        "tp1": signal["tp1"],
        "tp2": signal["tp2"],
        "tp3": signal["tp3"],
        "margin": signal["margin"],
        "position_value": signal["position_value"],
        "opened_at": utc_now().isoformat(),
        "last_checked": signal["candle_time"],
        "status": "OPEN",
        "result": None,
        "exit_price": None,
        "closed_at": None,
        "pnl_usdt": None,
    }

    trades.append(trade)
    save_history(history)

    return True


def close_paper_trade(trade, exit_price, result):
    entry = safe_float(trade.get("entry"))
    position_value = safe_float(trade.get("position_value"))

    if entry <= 0:
        pnl = 0.0
    else:
        if trade["direction"] == "LONG":
            pnl = (exit_price - entry) / entry * position_value
        else:
            pnl = (entry - exit_price) / entry * position_value

    trade["status"] = "CLOSED"
    trade["result"] = result
    trade["exit_price"] = exit_price
    trade["closed_at"] = utc_now().isoformat()
    trade["pnl_usdt"] = round(pnl, 4)


def update_paper_trades(history):
    changed = False

    for trade in history.get("trades", []):
        if trade.get("status") != "OPEN":
            continue

        try:
            candles = fetch_candles(
                next(
                    market["pair"]
                    for market in MARKETS
                    if market["name"] == trade["symbol"]
                ),
                60,
                100,
            )

            for candle in candles:
                if candle["time"] <= int(
                    safe_float(trade.get("last_checked"))
                ):
                    continue

                direction_value = trade["direction"]

                if direction_value == "LONG":
                    stop_hit = candle["low"] <= trade["stop"]
                    tp3_hit = candle["high"] >= trade["tp3"]
                    tp2_hit = candle["high"] >= trade["tp2"]
                    tp1_hit = candle["high"] >= trade["tp1"]
                else:
                    stop_hit = candle["high"] >= trade["stop"]
                    tp3_hit = candle["low"] <= trade["tp3"]
                    tp2_hit = candle["low"] <= trade["tp2"]
                    tp1_hit = candle["low"] <= trade["tp1"]

                # Conservative if SL and a target occur in same candle.
                if stop_hit:
                    close_paper_trade(
                        trade,
                        trade["stop"],
                        "LOSS",
                    )
                    changed = True
                    break

                if tp3_hit:
                    close_paper_trade(
                        trade,
                        trade["tp3"],
                        "WIN",
                    )
                    changed = True
                    break

                if tp2_hit:
                    close_paper_trade(
                        trade,
                        trade["tp2"],
                        "WIN",
                    )
                    changed = True
                    break

                if tp1_hit:
                    close_paper_trade(
                        trade,
                        trade["tp1"],
                        "WIN",
                    )
                    changed = True
                    break

                trade["last_checked"] = candle["time"]
                changed = True

        except Exception as exc:
            logging.warning(
                "Paper tracking error for %s: %s",
                trade.get("symbol"),
                exc,
            )

        time.sleep(0.2)

    if changed:
        save_history(history)


def paper_statistics(history):
    trades = history.get("trades", [])

    closed = [
        trade for trade in trades
        if trade.get("status") == "CLOSED"
    ]

    opened = [
        trade for trade in trades
        if trade.get("status") == "OPEN"
    ]

    wins = sum(
        1 for trade in closed
        if trade.get("result") == "WIN"
    )

    losses = sum(
        1 for trade in closed
        if trade.get("result") == "LOSS"
    )

    pnl = sum(
        safe_float(trade.get("pnl_usdt"))
        for trade in closed
    )

    win_rate = (
        wins / len(closed) * 100.0
        if closed
        else None
    )

    return {
        "closed": len(closed),
        "opened": len(opened),
        "wins": wins,
        "losses": losses,
        "pnl": pnl,
        "win_rate": win_rate,
    }


# ============================================================
# MESSAGE FORMATTING
# ============================================================

def fmt_price(value):
    value = safe_float(value)

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.4f}"

    return f"{value:.7f}".rstrip("0").rstrip(".")


def signal_message(signal, number):
    direction_label = (
        "🟢 LONG"
        if signal["direction"] == "LONG"
        else "🔴 SHORT"
    )

    reason_text = "\n".join(
        "• " + reason
        for reason in signal["reasons"][:5]
    )

    return (
        f"#{number}  {signal['symbol']}-USD\n"
        f"{direction_label}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 ورود فرضی: {fmt_price(signal['entry'])}\n"
        f"🛑 حد ضرر: {fmt_price(signal['stop'])}\n"
        f"✅ TP1: {fmt_price(signal['tp1'])}\n"
        f"✅ TP2: {fmt_price(signal['tp2'])}\n"
        f"✅ TP3: {fmt_price(signal['tp3'])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 قدرت تأیید روند: {signal['trend_score']}/100\n"
        f"🧮 امتیاز سیگنال: {signal['signal_score']}/100\n"
        f"📈 RSI یک‌ساعته: {signal['rsi']:.1f}\n"
        f"📦 نسبت حجم: {signal['volume_ratio']:.2f}x\n"
        f"🧪 مارجین فرضی: {signal['margin']:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"💰 ارزش فرضی موقعیت: "
        f"{signal['position_value']:.2f} USDT\n"
        f"🧭 دلایل تأیید:\n{reason_text}\n"
        f"🚫 بدون سفارش واقعی"
    )


def build_report(
    signals,
    rejection_reasons,
    market_errors,
    backtest,
    history,
):
    stats = paper_statistics(history)

    lines = [
        "🐋 ETH WHALE V5.1",
        "━━━━━━━━━━━━━━━━━━",
        "📊 SMART MARKET WATCH",
        "🧪 PAPER TRADING ONLY",
        "🚫 سفارش واقعی: خاموش",
        f"🕒 {utc_text()}",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if signals:
        lines.append(
            f"✅ سیگنال‌های واجد شرایط: {len(signals)}"
        )
    else:
        lines.append(
            "⚪ WAIT — سیگنال واجد شرایط پیدا نشد"
        )
        lines.append(
            "سیگنال ضعیف برای پُر کردن سهمیه ساخته نمی‌شود."
        )

    lines.extend([
        "",
        f"🔎 بازارهای بررسی‌شده: {len(MARKETS)}",
        f"⚠️ خطاهای بازار: {market_errors}",
        f"🎚 حداقل قدرت روند: {MIN_TREND_STRENGTH}/100",
        f"🎚 حداقل امتیاز سیگنال: {MIN_SIGNAL_SCORE}/100",
        "",
        "📉 دلایل اصلی رد بازارها:",
    ])

    if rejection_reasons:
        ordered_reasons = sorted(
            rejection_reasons.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        for reason, count in ordered_reasons[:5]:
            lines.append(f"• {reason}: {count}")
    else:
        lines.append("• دلیل رد خاصی ثبت نشد")

    lines.extend([
        "",
        "🧪 آزمون تاریخی ساده ۱ساعته:",
    ])

    if backtest["trades"] >= MIN_BACKTEST_TRADES:
        historical_rate = (
            backtest["wins"] / backtest["trades"] * 100
        )

        lines.append(
            f"نرخ برد تاریخی: {historical_rate:.1f}%"
        )
        lines.append(
            f"معاملات آزمون: {backtest['trades']} "
            f"| برد: {backtest['wins']} "
            f"| باخت: {backtest['losses']}"
        )
        lines.append(
            "⚠️ آزمون ساده است؛ کارمزد، لغزش قیمت و "
            "تأمین مالی لحاظ نشده‌اند."
        )
    else:
        lines.append(
            "نرخ برد تاریخی: تأییدنشده؛ داده کافی نیست"
        )
        lines.append(
            f"معاملات آزمون: {backtest['trades']} "
            f"(حداقل لازم: {MIN_BACKTEST_TRADES})"
        )

    lines.extend([
        "",
        "📒 آمار معاملات آزمایشی ثبت‌شده:",
    ])

    if stats["closed"] >= MIN_BACKTEST_TRADES:
        lines.append(
            f"نرخ برد ثبت‌شده: {stats['win_rate']:.1f}%"
        )
    else:
        lines.append(
            "نرخ برد ثبت‌شده: تأییدنشده؛ "
            f"{stats['closed']} معامله بسته‌شده "
            f"(حداقل {MIN_BACKTEST_TRADES})"
        )

    lines.extend([
        f"معاملات باز آزمایشی: {stats['opened']}",
        f"سود/زیان بسته‌شده: {stats['pnl']:+.4f} USDT",
        "",
        "⚠️ قدرت روند، احتمال برد نیست.",
        "⚠️ تمام معاملات فقط شبیه‌سازی هستند.",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN SCAN
# ============================================================

def main():
    logging.info("Starting %s", BOT_NAME)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning(
            "Telegram credentials missing; "
            "messages will be printed to logs."
        )

    history = load_history()

    # Update existing simulated positions first.
    update_paper_trades(history)

    candidates = []
    rejection_reasons = {}
    market_errors = 0

    for market in MARKETS:
        try:
            signal, reason = analyze_market(market)

            if signal:
                candidates.append(signal)
                logging.info(
                    "%s: %s | trend=%s | score=%s",
                    signal["symbol"],
                    signal["direction"],
                    signal["trend_score"],
                    signal["signal_score"],
                )
            else:
                rejection_reasons[reason] = (
                    rejection_reasons.get(reason, 0) + 1
                )

                logging.info(
                    "%s skipped: %s",
                    market["name"],
                    reason,
                )

        except Exception as exc:
            market_errors += 1
            rejection_reasons["خطای دریافت یا تحلیل داده"] = (
                rejection_reasons.get(
                    "خطای دریافت یا تحلیل داده",
                    0,
                ) + 1
            )

            logging.error(
                "%s analysis error: %s",
                market["name"],
                exc,
            )

        time.sleep(0.25)

    # Best first; never force weak signals into the report.
    candidates.sort(
        key=lambda item: (
            item["trend_score"],
            item["signal_score"],
        ),
        reverse=True,
    )

    signals = candidates[:MAX_SIGNALS_PER_SCAN]

    # Register selected signals as paper trades.
    for signal in signals:
        open_paper_trade(signal, history)

    save_history(history)

    # Historical test runs on a separate market-data pass.
    backtest, backtest_errors = run_historical_tests()

    report = build_report(
        signals,
        rejection_reasons,
        market_errors + backtest_errors,
        backtest,
        history,
    )

    telegram_send(report)

    for index, signal in enumerate(signals, start=1):
        telegram_send(signal_message(signal, index))
        time.sleep(1)

    logging.info("Scan completed.")


if __name__ == "__main__":
    main()
