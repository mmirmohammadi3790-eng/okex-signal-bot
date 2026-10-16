
# -*- coding: utf-8 -*-
"""
IRAN STOCK WHALE
TSETMC / Iran Stock Market
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
# 1. CONFIGURATION
# ============================================================

BOT_NAME = "IRAN STOCK WHALE"

API_BASES = [
    "https://cdn.tsetmc.com/api",
    "https://cdn10.tsetmc.com/api",
]

TELEGRAM_API = "https://api.telegram.org"

CAPITAL_TOMAN = 10_000_000
TOMAN_TO_RIAL = 10

RISK_PERCENT = 1.0
MAX_POSITION_PERCENT = 20.0

MIN_SCORE = 70
MAX_SIGNALS_PER_SCAN = 10

# صفر یعنی تمام نمادهایی که API برمی‌گرداند
MAX_SYMBOLS_PER_SCAN = 0

REQUEST_DELAY = 0.25
REQUEST_TIMEOUT = (6, 12)
RETRY_PER_HOST = 2

STATE_FILE = "bot_state.json"
LOG_FILE = "bot.log"

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()

CAPITAL_RIAL = CAPITAL_TOMAN * TOMAN_TO_RIAL

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
# 2. TIME / FORMAT
# ============================================================

def iran_now():
    return datetime.now(ZoneInfo("Asia/Tehran"))


def fa_num(value, decimals=0):
    try:
        result = f"{float(value):,.{decimals}f}"
        table = str.maketrans(
            "0123456789.,-",
            "۰۱۲۳۴۵۶۷۸۹٫٬−",
        )
        return result.translate(table)
    except (ValueError, TypeError):
        return str(value)


def rial_text(value):
    return f"{fa_num(value)} ریال"


def toman_text(value):
    return f"{fa_num(value)} تومان"


# ============================================================
# 3. TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram secrets are missing.")
        return False

    url = (
        f"{TELEGRAM_API}/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

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
            raise RuntimeError(
                "Telegram API returned ok=false"
            )

        return True

    except Exception as exc:
        log.error("Telegram error: %s", exc)
        return False


# ============================================================
# 4. STATE FILE
# ============================================================

def load_state():
    default = {
        "sent": {},
        "paper_trades": [],
        "last_scan": None,
    }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            return default

        state.setdefault("sent", {})
        state.setdefault("paper_trades", [])
        state.setdefault("last_scan", None)

        return state

    except (OSError, json.JSONDecodeError):
        return default


def save_state(state):
    temp_path = STATE_FILE + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(temp_path, STATE_FILE)


# ============================================================
# 5. API REQUEST WITH HOST FALLBACK
# ============================================================

def api_get(path, params=None):
    errors = []

    for base_url in API_BASES:
        for attempt in range(1, RETRY_PER_HOST + 1):
            try:
                url = base_url.rstrip("/") + "/" + path.lstrip("/")

                response = SESSION.get(
                    url,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                response.raise_for_status()
                data = response.json()

                if not isinstance(data, dict):
                    raise ValueError(
                        "Unexpected API response type"
                    )

                log.info(
                    "API connected: %s",
                    base_url,
                )

                return data

            except Exception as exc:
                error = (
                    f"{base_url} "
                    f"attempt={attempt}: {exc}"
                )

                errors.append(error)
                log.warning("%s", error)
                time.sleep(attempt)

    raise RuntimeError(
        "All API hosts failed: "
        + " | ".join(errors[-4:])
    )


# ============================================================
# 6. MARKET WATCH
# ============================================================

def number_from(row, *keys):
    for key in keys:
        value = row.get(key)

        if value is None:
            continue

        try:
            return float(value)
        except (TypeError, ValueError):
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
        rows = rows.get(
            "marketwatch",
            rows.get("data"),
        )

    if not isinstance(rows, list):
        raise RuntimeError(
            "Market-watch schema not recognized"
        )

    symbols = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        code = row.get("insCode")
        symbol = row.get("lVal18AFC")

        if not code or not symbol:
            continue

        last_price = number_from(
            row, "pDrCotVal", "pl"
        )
        closing_price = number_from(
            row, "pClosing", "pc"
        )
        yesterday_price = number_from(
            row, "priceYesterday", "py"
        )
        volume = number_from(
            row, "qTotTran5J", "tvol"
        )
        trade_value = number_from(
            row, "qTotCap", "tval"
        )

        if last_price <= 0 or closing_price <= 0:
            continue

        symbols.append({
            "code": str(code),
            "symbol": str(symbol).strip(),
            "name": str(
                row.get("lVal30") or symbol
            ).strip(),
            "last": last_price,
            "close": closing_price,
            "yesterday": yesterday_price,
            "volume": volume,
            "value": trade_value,
        })

    # Prefer symbols with higher reported trading value.
    symbols.sort(
        key=lambda item: item["value"],
        reverse=True,
    )

    if MAX_SYMBOLS_PER_SCAN > 0:
        symbols = symbols[:MAX_SYMBOLS_PER_SCAN]

    return symbols


# ============================================================
# 7. DAILY HISTORY
# ============================================================

def get_daily_history(ins_code):
    path = (
        "/ClosingPrice/"
        f"GetClosingPriceDailyList/{ins_code}/60"
    )

    data = api_get(path)
    rows = data.get("closingPriceDaily")

    if not isinstance(rows, list):
        return []

    history = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        close = number_from(
            row, "pClosing", "pDrCotVal"
        )
        volume = number_from(
            row, "qTotTran5J"
        )

        if close <= 0:
            continue

        history.append({
            "date": str(row.get("dEven", "")),
            "close": close,
            "volume": volume,
        })

    # Sort oldest to newest and remove duplicate dates.
    by_date = {}

    for item in history:
        by_date[item["date"]] = item

    history = sorted(
        by_date.values(),
        key=lambda item: item["date"],
    )

    return history


# ============================================================
# 8. TECHNICAL INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    result = sum(values[:period]) / period
    multiplier = 2.0 / (period + 1)

    for value in values[period:]:
        result = (
            value * multiplier
            + result * (1 - multiplier)
        )

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[index] - values[index - 1]
        for index in range(1, len(values))
    ]

    changes = changes[-period:]

    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0

    relative_strength = average_gain / average_loss

    return 100 - (
        100 / (1 + relative_strength)
    )


def volatility_proxy(values, period=14):
    """
    Close-to-close volatility estimate.
    This is not a true ATR: high/low candles are unavailable here.
    """
    if len(values) < period + 1:
        return None

    differences = [
        abs(values[i] - values[i - 1])
        for i in range(1, len(values))
    ]

    return sum(differences[-period:]) / period


# ============================================================
# 9. SIGNAL AND RISK MANAGEMENT
# ============================================================

def analyze_symbol(symbol, history):
    if len(history) < 50:
        return None

    closes = [item["close"] for item in history]
    historical_volumes = [
        item["volume"] for item in history
    ]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi_value = rsi(closes, 14)
    volatility = volatility_proxy(closes, 14)

    if any(
        value is None
        for value in (
            ema20,
            ema50,
            rsi_value,
            volatility,
        )
    ):
        return None

    price = symbol["last"]

    if price <= 0 or volatility <= 0:
        return None

    score = 0
    reasons = []

    # Trend filter
    if ema20 > ema50:
        score += 25
        reasons.append("EMA20 بالاتر از EMA50")

    if price > ema20:
        score += 20
        reasons.append("قیمت بالاتر از EMA20")

    # Momentum filter
    if 50 <= rsi_value <= 68:
        score += 20
        reasons.append("RSI در محدوده مثبت")

    # Compare current volume with historical daily average.
    if len(historical_volumes) >= 21:
        baseline = historical_volumes[-21:-1]
        average_volume = sum(baseline) / len(baseline)

        if (
            average_volume > 0
            and symbol["volume"] >= average_volume * 1.2
        ):
            score += 20
            reasons.append("حجم بالاتر از میانگین تاریخی")

    # Avoid chasing sharp price rises.
    if symbol["yesterday"] > 0:
        daily_change = (
            (price - symbol["yesterday"])
            / symbol["yesterday"]
        ) * 100

        if 0 < daily_change <= 3:
            score += 15
            reasons.append("رشد روزانه محدود")

        if daily_change > 4:
            return None

    if score < MIN_SCORE:
        return None

    stop_distance = max(
        volatility * 1.5,
        price * 0.015,
    )

    stop_distance = min(
        stop_distance,
        price * 0.04,
    )

    entry = price
    stop = entry - stop_distance

    if stop <= 0 or stop >= entry:
        return None

    target1 = entry + stop_distance * 1.5
    target2 = entry + stop_distance * 2.0
    target3 = entry + stop_distance * 3.0

    # All calculations here use RIAL.
    risk_budget_rial = (
        CAPITAL_RIAL * RISK_PERCENT / 100
    )

    max_position_rial = (
        CAPITAL_RIAL * MAX_POSITION_PERCENT / 100
    )

    risk_per_share = entry - stop

    shares_by_risk = int(
        risk_budget_rial / risk_per_share
    )

    shares_by_capital = int(
        max_position_rial / entry
    )

    shares = max(
        0,
        min(shares_by_risk, shares_by_capital),
    )

    position_rial = shares * entry
    risk_rial = shares * risk_per_share

    return {
        "symbol": symbol["symbol"],
        "name": symbol["name"],
        "entry": entry,
        "score": score,
        "rsi": rsi_value,
        "ema20": ema20,
        "ema50": ema50,
        "stop": stop,
        "tp1": target1,
        "tp2": target2,
        "tp3": target3,
        "shares": shares,
        "position_rial": position_rial,
        "position_toman": position_rial / TOMAN_TO_RIAL,
        "risk_rial": risk_rial,
        "risk_toman": risk_rial / TOMAN_TO_RIAL,
        "reasons": reasons,
    }


# ============================================================
# 10. TELEGRAM SIGNAL FORMAT
# ============================================================

def format_signal(signal):
    reason_text = "\n".join(
        "• " + reason
        for reason in signal["reasons"]
    )

    return (
        "🐋 IRAN STOCK WHALE\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧪 سیگنال خرید آزمایشی\n"
        "🚫 سفارش واقعی: غیرفعال\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🏷 نماد: {signal['symbol']}\n"
        f"📌 نام: {signal['name']}\n"
        f"⭐ امتیاز: {signal['score']}/100\n"
        f"📊 RSI: {fa_num(signal['rsi'], 1)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 ورود فرضی: {rial_text(signal['entry'])}\n"
        f"🛑 حد ضرر: {rial_text(signal['stop'])}\n"
        f"🎯 هدف اول: {rial_text(signal['tp1'])}\n"
        f"🎯 هدف دوم: {rial_text(signal['tp2'])}\n"
        f"🎯 هدف سوم: {rial_text(signal['tp3'])}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 تعداد فرضی: {fa_num(signal['shares'])} سهم\n"
        f"💵 ارزش موقعیت: {toman_text(signal['position_toman'])}\n"
        f"⚠️ ریسک تخمینی: {toman_text(signal['risk_toman'])}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔎 دلایل:\n{reason_text}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕒 {iran_now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "⚠️ سیگنال تضمین سود یا اجرای معامله نیست."
    )


# ============================================================
# 11. SCAN ALL RECEIVED SYMBOLS
# ============================================================

def run_scan():
    state = load_state()
    today = iran_now().strftime("%Y-%m-%d")

    try:
        symbols = get_market_watch()

    except Exception as exc:
        log.exception("Market watch request failed")

        telegram_send(
            "❌ اسکن بازار ناموفق بود.\n"
            f"علت: {str(exc)[:500]}\n"
            "هیچ سفارش واقعی ثبت نشده است."
        )
        return

    if not symbols:
        telegram_send(
            "⚠️ فهرست نمادها خالی است.\n"
            "سیگنالی تولید نشد؛ اتصال و قالب API را بررسی کن."
        )
        return

    telegram_send(
        "🐋 IRAN STOCK WHALE\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟢 دریافت فهرست نمادها موفق بود.\n"
        f"🔍 تعداد نمادهای دریافتی: {len(symbols)}\n"
        f"💰 سرمایه فرضی: {fa_num(CAPITAL_TOMAN)} تومان\n"
        "🧪 PAPER ONLY\n"
        "🚫 REAL ORDERS OFF"
    )

    signals = []
    errors = 0

    for index, symbol in enumerate(symbols, start=1):
        try:
            history = get_daily_history(symbol["code"])
            signal = analyze_symbol(symbol, history)

            if signal:
                key = f"{today}:{signal['symbol']}"

                if key not in state["sent"]:
                    signals.append(signal)

        except Exception as exc:
            errors += 1
            log.warning(
                "Symbol %s failed: %s",
                symbol["symbol"],
                exc,
            )

        if index % 50 == 0:
            log.info(
                "Progress: %s/%s symbols; errors=%s",
                index,
                len(symbols),
                errors,
            )

        time.sleep(REQUEST_DELAY)

    signals.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    signals = signals[:MAX_SIGNALS_PER_SCAN]
    sent_count = 0

    for signal in signals:
        key = f"{today}:{signal['symbol']}"

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
    state["last_scan_errors"] = errors

    try:
        save_state(state)
    except OSError:
        log.exception("State save failed")

    telegram_send(
        "📊 گزارش نهایی اسکن\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔍 نمادهای دریافتی: {len(symbols)}\n"
        f"⚠️ خطاهای بررسی نماد: {errors}\n"
        f"📈 سیگنال‌های واجد شرایط: {len(signals)}\n"
        f"📨 پیام‌های ارسال‌شده: {sent_count}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧪 حالت آزمایشی فعال است.\n"
        "🚫 سفارش واقعی: غیرفعال"
    )


# ============================================================
# 12. START
# ============================================================

def main():
    log.info("Starting %s", BOT_NAME)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID."
        )
        return

    startup_message = (
        "🐋 IRAN STOCK WHALE\n"
        "ربات راه‌اندازی شد.\n"
        "🧪 فقط سیگنال آزمایشی\n"
        "🚫 سفارش واقعی غیرفعال"
    )

    if not telegram_send(startup_message):
        log.error("Telegram startup test failed.")
        return

    run_scan()


if __name__ == "__main__":
    main()
