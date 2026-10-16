# ============================================================
# ETH WHALE V5.4
# Kraken Public Market Data | PAPER SIGNALS ONLY
# NO REAL ORDERS | NO PRIVATE API KEYS
# ============================================================

import os
import json
import time
import logging
import requests
import statistics
from datetime import datetime, timezone

BOT_NAME = "🐋 ETH WHALE"
VERSION = "5.4"

BASE_URL = "https://api.kraken.com/0/public"

CAPITAL_USDT = 48.0
LEVERAGE = 3
MARGIN_PER_TRADE = 16.0
POSITION_VALUE = MARGIN_PER_TRADE * LEVERAGE
MAX_SIGNALS = 3

MIN_SCORE = 62
STRONG_SCORE = 76

TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}

MARKETS = [
    "XBTUSD",
    "ETHUSD",
    "SOLUSD",
    "XRPUSD",
    "XXDGZUSD",
    "LINKUSD",
    "ADAUSD",
    "AVAXUSD",
    "LTCUSD",
    "BCHUSD",
]

HISTORY_FILE = "paper_history.json"
REQUEST_TIMEOUT = 20

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
log = logging.getLogger(BOT_NAME)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Paper-Signal-Bot/5.4"
})


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram credentials are not configured.")
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
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            log.error("Telegram rejected the message.")
            return False

        return True

    except requests.RequestException as exc:
        log.error("Telegram error: %s", exc)
        return False


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def safe_float(value, default=0.0):
    try:
        result = float(value)
        if result != result:
            return default
        return result
    except (TypeError, ValueError):
        return default


def format_price(value):
    value = safe_float(value)

    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.8f}".rstrip("0").rstrip(".")


def http_get(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    response = SESSION.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    errors = payload.get("error", [])

    if errors:
        raise RuntimeError("; ".join(errors))

    return payload.get("result", {})


# ============================================================
# MARKET DATA
# ============================================================

def fetch_ohlc(pair, interval, limit=120):
    result = http_get(
        "OHLC",
        {
            "pair": pair,
            "interval": interval,
        },
    )

    pair_key = next(
        (
            key for key in result
            if key != "last"
        ),
        None,
    )

    if not pair_key:
        raise RuntimeError(f"No OHLC data for {pair}")

    rows = result[pair_key]

    if not isinstance(rows, list):
        raise RuntimeError(f"Unexpected OHLC format for {pair}")

    candles = []

    for row in rows[-limit:]:
        if len(row) < 7:
            continue

        candles.append({
            "time": int(safe_float(row[0])),
            "open": safe_float(row[1]),
            "high": safe_float(row[2]),
            "low": safe_float(row[3]),
            "close": safe_float(row[4]),
            "vwap": safe_float(row[5]),
            "volume": safe_float(row[6]),
        })

    if len(candles) < 55:
        raise RuntimeError(
            f"Insufficient candles for {pair}: {len(candles)}"
        )

    return candles


def fetch_ticker(pair):
    result = http_get("Ticker", {"pair": pair})

    if not result:
        raise RuntimeError(f"No ticker for {pair}")

    ticker = next(iter(result.values()))

    last = safe_float(
        ticker.get("c", [0])[0]
    )
    bid = safe_float(
        ticker.get("b", [0])[0]
    )
    ask = safe_float(
        ticker.get("a", [0])[0]
    )
    volume_24h = safe_float(
        ticker.get("v", [0, 0])[1]
    )

    return {
        "last": last,
        "bid": bid,
        "ask": ask,
        "volume_24h": volume_24h,
    }


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period

    for value in values[period:]:
        current = (
            value * multiplier
            + current * (1.0 - multiplier)
        )

    return current


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

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
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close),
        )
        true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    return sum(true_ranges[-period:]) / period


def average_volume(candles, period=20):
    values = [
        candle["volume"]
        for candle in candles[-period:]
    ]

    if not values:
        return 0.0

    return sum(values) / len(values)


def calculate_indicators(candles):
    closes = [c["close"] for c in candles]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    current_rsi = rsi(closes, 14)
    current_atr = atr(candles, 14)

    vol_avg = average_volume(candles, 20)
    current_volume = candles[-1]["volume"]

    volume_ratio = (
        current_volume / vol_avg
        if vol_avg > 0
        else 0.0
    )

    return {
        "close": closes[-1],
        "ema20": ema20,
        "ema50": ema50,
        "rsi": current_rsi,
        "atr": current_atr,
        "volume_ratio": volume_ratio,
    }


# ============================================================
# TREND ANALYSIS
# ============================================================

def trend_direction(indicators):
    e20 = indicators["ema20"]
    e50 = indicators["ema50"]
    price = indicators["close"]

    if e20 is None or e50 is None:
        return "WAIT"

    if price > e20 > e50:
        return "LONG"

    if price < e20 < e50:
        return "SHORT"

    return "WAIT"


def timeframe_summary(pair, interval):
    candles = fetch_ohlc(pair, interval)
    indicators = calculate_indicators(candles)

    return {
        "candles": candles,
        "indicators": indicators,
        "trend": trend_direction(indicators),
    }


# ============================================================
# SIGNAL SCORING
# ============================================================

def score_signal(summary_15m, summary_1h, summary_4h):
    score_long = 0
    score_short = 0
    reasons = []

    s15 = summary_15m["indicators"]
    s1h = summary_1h["indicators"]
    s4h = summary_4h["indicators"]

    t15 = summary_15m["trend"]
    t1h = summary_1h["trend"]
    t4h = summary_4h["trend"]

    # 1-hour trend: primary direction
    if t1h == "LONG":
        score_long += 25
    elif t1h == "SHORT":
        score_short += 25
    else:
        reasons.append("روند یک‌ساعته نامشخص")

    # 4-hour confirmation
    if t4h == "LONG":
        score_long += 20
    elif t4h == "SHORT":
        score_short += 20
    else:
        reasons.append("تأیید روند چهارساعته وجود ندارد")

    # 15-minute confirmation
    if t15 == "LONG":
        score_long += 15
    elif t15 == "SHORT":
        score_short += 15
    else:
        reasons.append("روند ۱۵ دقیقه‌ای نامشخص")

    # RSI
    rsi_1h = s1h["rsi"]

    if rsi_1h is not None:
        if 52 <= rsi_1h <= 68:
            score_long += 12
        elif 32 <= rsi_1h <= 48:
            score_short += 12
        elif rsi_1h > 75 or rsi_1h < 25:
            reasons.append("RSI در محدوده افراطی است")
        else:
            reasons.append("RSI تأیید قوی نمی‌دهد")

    # Volume confirmation
    volume_ratio = s15["volume_ratio"]

    if volume_ratio >= 1.15:
        if t15 == "LONG":
            score_long += 10
        elif t15 == "SHORT":
            score_short += 10
    else:
        reasons.append("حجم معاملات پایین‌تر از حد تأیید است")

    # EMA separation
    if s1h["ema20"] and s1h["ema50"]:
        separation = (
            abs(s1h["ema20"] - s1h["ema50"])
            / max(s1h["close"], 1e-12)
        )

        if separation >= 0.002:
            if t1h == "LONG":
                score_long += 8
            elif t1h == "SHORT":
                score_short += 8
        else:
            reasons.append("فاصله EMAها کم است")

    # Avoid conflicting timeframes
    if t1h != t4h or t1h == "WAIT":
        reasons.append("تأیید دو تایم‌فریم اصلی کامل نیست")

    if score_long > score_short:
        direction = "LONG"
        score = score_long
    elif score_short > score_long:
        direction = "SHORT"
        score = score_short
    else:
        direction = "WAIT"
        score = max(score_long, score_short)

    if direction == "LONG" and not (
        t1h == "LONG" and t4h == "LONG"
    ):
        direction = "WAIT"

    if direction == "SHORT" and not (
        t1h == "SHORT" and t4h == "SHORT"
    ):
        direction = "WAIT"

    if score < MIN_SCORE:
        direction = "WAIT"

    return direction, score, reasons


# ============================================================
# SUPPORT / RESISTANCE AND TRADE LEVELS
# ============================================================

def recent_support_resistance(candles, lookback=30):
    sample = candles[-lookback:]

    support = min(c["low"] for c in sample)
    resistance = max(c["high"] for c in sample)

    return support, resistance


def build_trade(pair, direction, score, summary_15m):
    candles = summary_15m["candles"]
    indicators = summary_15m["indicators"]

    entry = indicators["close"]
    current_atr = indicators["atr"]

    if not current_atr or current_atr <= 0 or entry <= 0:
        return None

    support, resistance = recent_support_resistance(candles)

    stop_distance = max(
        current_atr * 1.5,
        entry * 0.004,
    )

    if direction == "LONG":
        stop = entry - stop_distance

        # Keep the stop below entry and use positive targets.
        stop = min(stop, entry - entry * 0.002)

        risk = entry - stop
        tp1 = entry + risk
        tp2 = entry + 1.8 * risk
        tp3 = entry + 2.5 * risk

        # Do not create a target beyond an extremely close
        # resistance without warning the user.
        resistance_warning = (
            resistance > entry and resistance < tp1
        )

    elif direction == "SHORT":
        stop = entry + stop_distance
        stop = max(stop, entry + entry * 0.002)

        risk = stop - entry
        tp1 = entry - risk
        tp2 = entry - 1.8 * risk
        tp3 = entry - 2.5 * risk

        resistance_warning = (
            support < entry and support > tp1
        )

    else:
        return None

    if risk <= 0:
        return None

    # Hypothetical position sizing only.
    quantity = POSITION_VALUE / entry

    return {
        "pair": pair,
        "direction": direction,
        "score": score,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk": risk,
        "quantity": quantity,
        "margin": MARGIN_PER_TRADE,
        "position_value": POSITION_VALUE,
        "support": support,
        "resistance": resistance,
        "resistance_warning": resistance_warning,
        "created_at": now_utc(),
        "status": "OPEN",
    }


# ============================================================
# PAPER HISTORY
# ============================================================

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {
            "trades": [],
            "scan_count": 0,
        }

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("History file must contain an object")

        data.setdefault("trades", [])
        data.setdefault("scan_count", 0)
        return data

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Could not read history: %s", exc)
        return {
            "trades": [],
            "scan_count": 0,
        }


def save_history(history):
    temporary_file = HISTORY_FILE + ".tmp"

    try:
        with open(
            temporary_file,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                history,
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(temporary_file, HISTORY_FILE)

    except OSError as exc:
        log.error("Could not save paper history: %s", exc)


def add_paper_trade(history, trade):
    # Avoid duplicate open paper trades for the same pair.
    for existing in history["trades"]:
        if (
            existing.get("pair") == trade["pair"]
            and existing.get("status") == "OPEN"
        ):
            return False

    history["trades"].append(trade)
    return True


def update_open_trades(history):
    """
    Update paper positions from public ticker prices.
    If stop and target are both crossed in the same scan,
    the conservative assumption is that the stop happened first.
    """
    for trade in history["trades"]:
        if trade.get("status") != "OPEN":
            continue

        pair = trade.get("pair")

        try:
            ticker = fetch_ticker(pair)
            price = ticker["last"]

            if price <= 0:
                continue

            direction = trade["direction"]
            stop = trade["stop"]
            tp1 = trade["tp1"]
            tp2 = trade["tp2"]
            tp3 = trade["tp3"]

            if direction == "LONG":
                if price <= stop:
                    trade["status"] = "STOPPED"
                    trade["exit_price"] = price
                    trade["closed_at"] = now_utc()
                    trade["result_r"] = -1.0
                elif price >= tp3:
                    trade["status"] = "TP3"
                    trade["exit_price"] = price
                    trade["closed_at"] = now_utc()
                    trade["result_r"] = 2.5
                elif price >= tp2:
                    trade["status"] = "TP2"
                    trade["exit_price"] = price
                    trade["closed_at"] = now_utc()
                    trade["result_r"] = 1.8
                elif price >= tp1:
                    trade["status"] = "TP1"
                    trade["exit_price"] = price
                    trade["closed_at"] = now_utc()
                    trade["result_r"] = 1.0

            elif direction == "SHORT":
                if price >= stop:
                    trade["status"] = "STOPPED"
                    trade["exit_price"] = price
                    trade["closed_at"] = now_utc()
                    trade["result_r"] = -1.0
                elif price <= tp3:
                    trade["status"] = "TP3"
                    trade["exit_price"] = price
                    trade["closed_at"] = now_utc()
                    trade["result_r"] = 2.5
                elif price <= tp2:
                    trade["status"] = "TP2"
                    trade["exit_price"] = price
                    trade["closed_at"] = now_utc()
                    trade["result_r"] = 1.8
                elif price <= tp1:
                    trade["status"] = "TP1"
                    trade["exit_price"] = price
                    trade["closed_at"] = now_utc()
                    trade["result_r"] = 1.0

            if trade.get("status") != "OPEN":
                trade["latest_price"] = price

        except Exception as exc:
            log.warning(
                "Could not update paper trade %s: %s",
                pair,
                exc,
            )


# ============================================================
# REPORTS
# ============================================================

def build_trade_message(trade):
    strength = (
        "قوی"
        if trade["score"] >= STRONG_SCORE
        else "متوسط"
    )

    warning = ""

    if trade.get("resistance_warning"):
        warning = (
            "\n⚠️ قیمت به محدوده حمایت/مقاومت نزدیک است؛ "
            "ورود نیازمند بررسی بیشتر است."
        )

    return (
        f"{BOT_NAME}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 سیگنال آزمایشی Kraken\n"
        f"🪙 بازار: {trade['pair']}\n"
        f"📍 جهت: {trade['direction']}\n"
        f"🎯 امتیاز: {trade['score']}/100 ({strength})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 ورود فرضی: {format_price(trade['entry'])}\n"
        f"🛑 حد ضرر: {format_price(trade['stop'])}\n"
        f"🎯 TP1: {format_price(trade['tp1'])}\n"
        f"🎯 TP2: {format_price(trade['tp2'])}\n"
        f"🎯 TP3: {format_price(trade['tp3'])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"💵 مارجین فرضی: {trade['margin']:.2f} USDT\n"
        f"📦 ارزش فرضی موقعیت: "
        f"{trade['position_value']:.2f} USDT\n"
        f"📐 مقدار فرضی: {trade['quantity']:.8f}\n"
        f"🕒 زمان: {trade['created_at']}\n"
        f"{warning}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧪 PAPER ONLY\n"
        f"🚫 هیچ سفارش واقعی ثبت نشده است."
    )


def build_market_report(scanned, errors, signals, rejected):
    lines = [
        f"{BOT_NAME}",
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش روند بازار",
        f"🕒 {now_utc()}",
        "━━━━━━━━━━━━━━━━━━",
        f"🔎 بازارهای بررسی‌شده: {scanned}",
        f"⚠️ خطاهای تحلیل: {errors}",
        f"📨 سیگنال‌های جدید: {len(signals)}",
    ]

    if signals:
        lines.append("")
        lines.append("📌 سیگنال‌های منتخب:")

        for trade in signals:
            lines.append(
                f"• {trade['pair']} | {trade['direction']} "
                f"| امتیاز {trade['score']}"
            )
    else:
        lines.extend([
            "",
            "⚪ WAIT — گزینه مناسب پیدا نشد",
        ])

        if rejected:
            lines.append("📌 دلایل اصلی رد بازارها:")

            for reason, count in sorted(
                rejected.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:4]:
                lines.append(f"• {reason}: {count}")

    lines.extend([
        "",
        "🧪 حالت آزمایشی فعال است.",
        "🚫 سفارش واقعی: خاموش",
    ])

    return "\n".join(lines)


def build_status(history):
    trades = history.get("trades", [])
    open_count = sum(
        1 for trade in trades
        if trade.get("status") == "OPEN"
    )
    closed = [
        trade for trade in trades
        if trade.get("status") != "OPEN"
    ]

    wins = sum(
        1 for trade in closed
        if safe_float(trade.get("result_r")) > 0
    )

    losses = sum(
        1 for trade in closed
        if safe_float(trade.get("result_r")) < 0
    )

    if closed:
        win_rate = wins / len(closed) * 100
        win_text = f"{win_rate:.1f}%"
        reliability = (
            "نمونه محدود؛ نتیجه قطعی نیست"
            if len(closed) < 30
            else "بر اساس معاملات کاغذی ثبت‌شده"
        )
    else:
        win_text = "هنوز داده کافی وجود ندارد"
        reliability = "نرخ برد تأیید نشده است"

    return (
        f"{BOT_NAME}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 وضعیت ربات {VERSION}\n"
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"📦 ارزش فرضی هر موقعیت: {POSITION_VALUE:.2f} USDT\n"
        f"📌 معاملات ثبت‌شده: {len(trades)}\n"
        f"🟢 موقعیت‌های باز: {open_count}\n"
        f"🏁 معاملات بسته‌شده: {len(closed)}\n"
        f"✅ برد: {wins} | ❌ باخت: {losses}\n"
        f"📈 نرخ برد: {win_text}\n"
        f"ℹ️ {reliability}\n"
        f"🚫 سفارش واقعی: خاموش"
    )


# ============================================================
# SCAN
# ============================================================

def scan_market(history):
    signals = []
    rejected = {}
    errors = 0
    scanned = 0

    update_open_trades(history)

    for pair in MARKETS:
        try:
            scanned += 1

            summary_15m = timeframe_summary(pair, 15)
            summary_1h = timeframe_summary(pair, 60)
            summary_4h = timeframe_summary(pair, 240)

            direction, score, reasons = score_signal(
                summary_15m,
                summary_1h,
                summary_4h,
            )

            if direction == "WAIT":
                if reasons:
                    for reason in reasons:
                        rejected[reason] = (
                            rejected.get(reason, 0) + 1
                        )
                else:
                    rejected["امتیاز پایین یا روند نامشخص"] = (
                        rejected.get(
                            "امتیاز پایین یا روند نامشخص",
                            0,
                        ) + 1
                    )
                continue

            trade = build_trade(
                pair,
                direction,
                score,
                summary_15m,
            )

            if not trade:
                rejected["اطلاعات کافی برای تعیین حد ضرر"] = (
                    rejected.get(
                        "اطلاعات کافی برای تعیین حد ضرر",
                        0,
                    ) + 1
                )
                continue

            signals.append(trade)

        except Exception as exc:
            errors += 1
            log.warning("Analysis failed for %s: %s", pair, exc)

        time.sleep(0.25)

    # Highest scores first; maximum 3 candidates per scan.
    signals.sort(
        key=lambda trade: trade["score"],
        reverse=True,
    )
    signals = signals[:MAX_SIGNALS]

    # Do not add new paper positions beyond the configured
    # maximum number of simultaneously open positions.
    current_open = sum(
        1 for trade in history["trades"]
        if trade.get("status") == "OPEN"
    )

    new_signals = []

    for trade in signals:
        if current_open >= MAX_SIGNALS:
            break

        if add_paper_trade(history, trade):
            new_signals.append(trade)
            current_open += 1

    history["scan_count"] = (
        safe_float(history.get("scan_count")) + 1
    )

    save_history(history)

    telegram_send(
        build_market_report(
            scanned,
            errors,
            new_signals,
            rejected,
        )
    )

    for trade in new_signals:
        telegram_send(build_trade_message(trade))

    log.info(
        "Scan completed: scanned=%s errors=%s new_signals=%s",
        scanned,
        errors,
        len(new_signals),
    )

    return {
        "scanned": scanned,
        "errors": errors,
        "signals": new_signals,
        "rejected": rejected,
    }


# ============================================================
# COMMAND HANDLER
# ============================================================

def handle_command(command, history):
    command = command.strip().lower()

    if command in ("/start", "/help"):
        return (
            f"{BOT_NAME}\n"
            "ربات بررسی بازار و سیگنال کاغذی Kraken\n\n"
            "/scan - اسکن بازار\n"
            "/status - وضعیت ربات\n"
            "/test - تست اتصال تلگرام\n"
            "/help - راهنما\n\n"
            "🧪 فقط سیگنال آزمایشی؛ سفارش واقعی ثبت نمی‌شود."
        )

    if command == "/status":
        return build_status(history)

    if command == "/test":
        return (
            f"{BOT_NAME}\n"
            "✅ تست پیام تلگرام موفق است.\n"
            "🧪 Paper mode فعال\n"
            "🚫 سفارش واقعی خاموش"
        )

    if command == "/scan":
        scan_market(history)
        return "✅ اسکن انجام شد. گزارش در پیام جداگانه ارسال شد."

    return "دستور ناشناخته است. برای راهنما /help را بفرست."


# ============================================================
# MAIN
# ============================================================

def main():
    log.info("%s version %s starting", BOT_NAME, VERSION)

    history = load_history()

    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        telegram_send(
            f"{BOT_NAME}\n"
            f"✅ ربات نسخه {VERSION} اجرا شد.\n"
            f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
            f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
            "🧪 PAPER SIGNALS ONLY\n"
            "🚫 سفارش واقعی خاموش"
        )
    else:
        log.warning(
            "Telegram credentials missing. "
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )

    try:
        result = scan_market(history)
        log.info("Initial scan result: %s", result)
    except Exception as exc:
        log.exception("Initial scan failed: %s", exc)
        telegram_send(
            f"{BOT_NAME}\n"
            f"❌ اسکن اولیه انجام نشد.\n"
            f"علت: {str(exc)[:500]}\n"
            "🧪 Paper mode فعال است؛ سفارش واقعی ثبت نشده."
        )


if __name__ == "__main__":
    main()
