
# -*- coding: utf-8 -*-
"""
IRAN STOCK WHALE
Iran Bourse + Farabourse
Telegram alerts | Paper trading only
NO REAL ORDERS
"""

import os
import json
import time
import logging
import requests

from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# CONFIGURATION
# ============================================================

BOT_NAME = "IRAN STOCK WHALE"
BASE_URL = "https://cdn.tsetmc.com/api"
TELEGRAM_API = "https://api.telegram.org"

CAPITAL_TOMAN = 10_000_000
RISK_PERCENT = 1.0
MAX_POSITION_PERCENT = 20.0

MIN_SCORE = 70
MAX_SIGNALS_PER_SCAN = 10
MAX_SYMBOLS_PER_SCAN = 0  # 0 = all received symbols
REQUEST_DELAY = 0.6
RETRY_COUNT = 3

STATE_FILE = "bot_state.json"
LOG_FILE = "bot.log"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

CAPITAL_RIAL = CAPITAL_TOMAN * 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(BOT_NAME)


# ============================================================
# TIME AND FORMATTING
# ============================================================

def iran_now():
    return datetime.now(ZoneInfo("Asia/Tehran"))


def fa_num(value, decimals=0):
    try:
        s = f"{float(value):,.{decimals}f}"
        return s.translate(
            str.maketrans("0123456789.,-", "۰۱۲۳۴۵۶۷۸۹٫٬−")
        )
    except (ValueError, TypeError):
        return str(value)


def price_text(value):
    return f"{fa_num(value)} ریال"


# ============================================================
# HTTP AND TELEGRAM
# ============================================================

def api_get(path, params=None):
    url = BASE_URL + path
    last_error = None

    for attempt in range(RETRY_COUNT):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=(10, 30),
                allow_redirects=True,
            )
            response.raise_for_status()

            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Unexpected API response format")

            return data

        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            log.warning(
                "API attempt %s failed: %s",
                attempt + 1,
                exc,
            )
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"TSETMC API unavailable: {last_error}")


def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials are missing.")
        return False

    url = f"{TELEGRAM_API}/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        response.raise_for_status()

        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(str(result))

        return True

    except Exception:
        log.exception("Telegram message failed")
        return False


# ============================================================
# PERSISTENT STATE
# ============================================================

def load_state():
    default = {
        "sent": {},
        "paper_trades": [],
        "last_scan": None,
    }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if not isinstance(state, dict):
            return default

        state.setdefault("sent", {})
        state.setdefault("paper_trades", [])
        state.setdefault("last_scan", None)
        return state

    except (OSError, json.JSONDecodeError):
        return default


def save_state(state):
    temp = STATE_FILE + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    os.replace(temp, STATE_FILE)


# ============================================================
# MARKET WATCH
# ============================================================

def as_float(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                continue
    return 0.0


def get_market_watch():
    params = {
        "market": 0,
        "paperTypes[0]": 1,
        "paperTypes[1]": 2,
        "paperTypes[2]": 3,
        "paperTypes[3]": 4,
        "paperTypes[4]": 5,
        "paperTypes[5]": 6,
        "paperTypes[6]": 7,
        "paperTypes[7]": 8,
        "paperTypes[8]": 9,
        "withBestLimits": "false",
        "hEven": 0,
        "RefID": 0,
    }

    data = api_get(
        "/ClosingPrice/GetMarketWatch",
        params=params,
    )

    rows = data.get("marketwatch")

    if isinstance(rows, dict):
        rows = rows.get("marketwatch", rows.get("data"))

    if not isinstance(rows, list):
        raise RuntimeError(
            "Market-watch response did not contain a symbol list"
        )

    result = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        code = row.get("insCode")
        symbol = row.get("lVal18AFC")

        if not code or not symbol:
            continue

        last = as_float(row, "pDrCotVal", "pl")
        close = as_float(row, "pClosing", "pc")
        yesterday = as_float(row, "priceYesterday", "py")
        volume = as_float(row, "qTotTran5J", "tvol")
        value = as_float(row, "qTotCap", "tval")

        if last <= 0 or close <= 0:
            continue

        result.append({
            "code": str(code),
            "symbol": str(symbol).strip(),
            "name": str(row.get("lVal30") or symbol).strip(),
            "last": last,
            "close": close,
            "yesterday": yesterday,
            "volume": volume,
            "value": value,
        })

    result.sort(key=lambda x: x["value"], reverse=True)

    if MAX_SYMBOLS_PER_SCAN > 0:
        result = result[:MAX_SYMBOLS_PER_SCAN]

    return result


# ============================================================
# DAILY PRICE HISTORY
# ============================================================

def get_daily_history(ins_code):
    data = api_get(
        f"/ClosingPrice/GetClosingPriceDailyList/{ins_code}/60"
    )

    rows = data.get("closingPriceDaily")

    if not isinstance(rows, list):
        return []

    rows = sorted(
        rows,
        key=lambda row: str(row.get("dEven", "")),
    )

    history = []

    for row in rows:
        close = as_float(row, "pClosing", "pDrCotVal")
        volume = as_float(row, "qTotTran5J")

        if close > 0:
            history.append({
                "date": str(row.get("dEven", "")),
                "close": close,
                "volume": volume,
            })

    # Remove duplicate dates and retain chronological order.
    unique = {}

    for item in history:
        unique[item["date"]] = item

    return sorted(
        unique.values(),
        key=lambda item: item["date"],
    )


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    result = sum(values[:period]) / period
    alpha = 2 / (period + 1)

    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result

    return result


def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    recent = changes[-period:]
    gains = [max(x, 0) for x in recent]
    losses = [max(-x, 0) for x in recent]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_volatility(closes, period=14):
    """
    Close-to-close volatility proxy.
    Not a true ATR because intraday high/low candles are not used.
    """
    if len(closes) < period + 1:
        return None

    changes = [
        abs(closes[i] - closes[i - 1])
        for i in range(1, len(closes))
    ]

    return sum(changes[-period:]) / period


# ============================================================
# SIGNAL ENGINE
# ============================================================

def analyze_symbol(symbol, history):
    if len(history) < 50:
        return None

    closes = [x["close"] for x in history]
    volumes = [x["volume"] for x in history]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi_value = calculate_rsi(closes, 14)
    volatility = calculate_volatility(closes)

    if any(
        x is None
        for x in (ema20, ema50, rsi_value, volatility)
    ):
        return None

    price = symbol["last"]

    if price <= 0 or volatility <= 0:
        return None

    score = 0
    reasons = []

    # Trend
    if ema20 > ema50:
        score += 25
        reasons.append("EMA20 بالاتر از EMA50")

    # Price momentum
    if price > ema20:
        score += 20
        reasons.append("قیمت بالاتر از EMA20")

    # RSI
    if 50 <= rsi_value <= 68:
        score += 20
        reasons.append("RSI در محدوده مثبت")

    # Volume confirmation
    if len(volumes) >= 21:
        baseline = volumes[-21:-1]
        avg_volume = sum(baseline) / len(baseline)

        if avg_volume > 0 and symbol["volume"] >= avg_volume * 1.2:
            score += 20
            reasons.append("حجم جاری بالاتر از میانگین")

    # Daily price movement filter
    if symbol["yesterday"] > 0:
        change_pct = (
            (price - symbol["yesterday"])
            / symbol["yesterday"]
        ) * 100

        if 0 < change_pct <= 3:
            score += 15
            reasons.append("رشد روزانه کنترل‌شده")

        if change_pct > 4:
            return None

    if score < MIN_SCORE:
        return None

    # Stop and targets in Rial
    stop_distance = max(
        volatility * 1.5,
        price * 0.015,
    )
    stop_distance = min(stop_distance, price * 0.04)

    entry = price
    stop = entry - stop_distance

    if stop <= 0 or stop >= entry:
        return None

    tp1 = entry + stop_distance * 1.5
    tp2 = entry + stop_distance * 2.0
    tp3 = entry + stop_distance * 3.0

    # Correct unit conversion:
    # TSETMC prices are Rial; capital configuration is Toman.
    risk_budget_rial = CAPITAL_RIAL * RISK_PERCENT / 100
    max_position_rial = CAPITAL_RIAL * MAX_POSITION_PERCENT / 100

    risk_per_share_rial = entry - stop

    shares_by_risk = int(
        risk_budget_rial / risk_per_share_rial
    )
    shares_by_capital = int(
        max_position_rial / entry
    )

    shares = max(
        0,
        min(shares_by_risk, shares_by_capital),
    )

    position_rial = shares * entry
    risk_rial = shares * risk_per_share_rial

    return {
        "symbol": symbol["symbol"],
        "name": symbol["name"],
        "entry": entry,
        "score": score,
        "rsi": rsi_value,
        "ema20": ema20,
        "ema50": ema50,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "shares": shares,
        "position_rial": position_rial,
        "position_toman": position_rial / 10,
        "risk_rial": risk_rial,
        "risk_toman": risk_rial / 10,
        "reasons": reasons,
    }


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def format_signal(s):
    reasons = "\n".join(
        f"• {item}" for item in s["reasons"]
    )

    return (
        "🇮🇷 IRAN STOCK WHALE\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧪 سیگنال خرید آزمایشی\n"
        "🚫 سفارش واقعی: غیرفعال\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🏷 نماد: {s['symbol']}\n"
        f"📌 نام: {s['name']}\n"
        f"⭐ امتیاز: {s['score']}/100\n"
        f"📈 RSI: {fa_num(s['rsi'], 1)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 ورود فرضی: {price_text(s['entry'])}\n"
        f"🛑 حد ضرر: {price_text(s['stop'])}\n"
        f"🎯 هدف ۱: {price_text(s['tp1'])}\n"
        f"🎯 هدف ۲: {price_text(s['tp2'])}\n"
        f"🎯 هدف ۳: {price_text(s['tp3'])}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 تعداد فرضی: {fa_num(s['shares'])} سهم\n"
        f"💵 ارزش موقعیت: {fa_num(s['position_toman'])} تومان\n"
        f"⚠️ ریسک فرضی: {fa_num(s['risk_toman'])} تومان\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔎 دلایل:\n{reasons}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕒 {iran_now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "⚠️ قیمت‌ها و اهداف تضمین اجرا یا سود نیستند."
    )


# ============================================================
# SCAN
# ============================================================

def run_scan():
    state = load_state()
    today = iran_now().strftime("%Y-%m-%d")

    try:
        symbols = get_market_watch()
    except Exception as exc:
        log.exception("Cannot retrieve market watch")
        telegram_send(
            "❌ اسکن بازار انجام نشد.\n"
            f"علت: {str(exc)[:250]}\n"
            "🚫 هیچ سفارش واقعی ارسال نشده است."
        )
        return

    if not symbols:
        telegram_send(
            "⚠️ فهرست نمادها خالی است؛ "
            "سیگنالی تولید نشد."
        )
        return

    telegram_send(
        "🐋 IRAN STOCK WHALE\n"
        "🟢 اسکن شروع شد\n"
        f"🔍 نمادهای دریافتی: {len(symbols)}\n"
        f"💰 سرمایه فرضی: {fa_num(CAPITAL_TOMAN)} تومان\n"
        "🧪 حالت آزمایشی | سفارش واقعی OFF"
    )

    signals = []

    for index, symbol in enumerate(symbols, start=1):
        try:
            history = get_daily_history(symbol["code"])
            signal = analyze_symbol(symbol, history)

            if signal:
                key = f"{today}:{signal['symbol']}"

                if key not in state["sent"]:
                    signals.append(signal)

        except Exception as exc:
            log.warning(
                "Skipping %s due to error: %s",
                symbol["symbol"],
                exc,
            )

        if index % 50 == 0:
            log.info("Progress: %s/%s", index, len(symbols))

        time.sleep(REQUEST_DELAY)

    signals.sort(
        key=lambda item: item["score"],
        reverse=True,
    )
    signals = signals[:MAX_SIGNALS_PER_SCAN]

    sent_count = 0

    for signal in signals:
        key = f"{today}:{signal['symbol']}"

        # Mark as sent only after Telegram confirms delivery.
        if telegram_send(format_signal(signal)):
            sent_count += 1
            state["sent"][key] = iran_now().isoformat()

            state["paper_trades"].append({
                "date": today,
                "symbol": signal["symbol"],
                "entry": signal["entry"],
                "stop": signal["stop"],
                "tp1": signal["tp1"],
                "tp2": signal["tp2"],
                "tp3": signal["tp3"],
                "shares": signal["shares"],
                "status": "PAPER_OPEN",
            })

    state["last_scan"] = iran_now().isoformat()
    state["last_scan_symbols"] = len(symbols)
    state["last_scan_signals"] = len(signals)

    try:
        save_state(state)
    except OSError:
        log.exception("Could not save state")

    telegram_send(
        "📊 گزارش اسکن بورس\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔍 نمادهای بررسی‌شده: {len(symbols)}\n"
        f"📈 سیگنال‌های واجد شرایط: {len(signals)}\n"
        f"📨 پیام‌های ارسال‌شده: {sent_count}\n"
        "🧪 PAPER ONLY\n"
        "🚫 سفارش واقعی: OFF"
    )


# ============================================================
# STARTUP
# ============================================================

def main():
    log.info("Starting %s", BOT_NAME)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first."
        )
        return

    if telegram_send(
        "🐋 IRAN STOCK WHALE\n"
        "ربات راه‌اندازی شد.\n"
        "🧪 فقط سیگنال آزمایشی\n"
        "🚫 سفارش واقعی غیرفعال"
    ):
        run_scan()
    else:
        log.error("Startup Telegram test failed; scan aborted.")


if __name__ == "__main__":
    main()
