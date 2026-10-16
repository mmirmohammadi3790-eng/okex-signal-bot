
# ============================================================
# ETH WHALE - BITPIN SMART MARKET WATCH V4
# PAPER SIGNALS ONLY - NO REAL ORDERS
# Capital: 48 USDT | Leverage: 3x | Max signals: 3
# Timeframes: 15m + 1h
# EMA20/EMA50 | RSI14 | Volume | ATR | Risk Management
# ============================================================

import os
import time
import logging
from datetime import datetime, timezone

import requests


# ---------------- CONFIG ----------------

BOT_NAME = "ETH WHALE"
BITPIN_BASE = "https://api.bitpin.org"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

CAPITAL = 48.0
LEVERAGE = 3
MAX_SIGNALS = 3
MAX_MARKETS = 30

MIN_SCORE = 65
STRONG_SCORE = 80

MIN_VOLUME_RATIO = 1.15
MIN_RSI_LONG = 38
MAX_RSI_LONG = 68
MIN_RSI_SHORT = 32
MAX_RSI_SHORT = 62

CANDLE_LIMIT = 100
TIMEOUT = 12
PAUSE = 0.15

CANDLE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
]

HEADERS = {
    "User-Agent": "ETH-WHALE-PaperBot/4.0",
    "Accept": "application/json",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

session = requests.Session()
session.headers.update(HEADERS)


# ---------------- HTTP ----------------

def get_json(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# ---------------- BITPIN MARKETS ----------------

def fetch_markets():
    urls = [
        f"{BITPIN_BASE}/v1/mkt/markets/",
        f"{BITPIN_BASE}/api/v1/mkt/markets/",
    ]

    errors = []

    for url in urls:
        try:
            data = get_json(url)

            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = None
                for key in ("results", "markets", "data"):
                    if isinstance(data.get(key), list):
                        rows = data[key]
                        break
            else:
                rows = None

            if rows:
                logging.info("MARKETS OK: %d", len(rows))
                return rows

            errors.append(f"{url}: unexpected response")

        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError("Markets API failed: " + " | ".join(errors))


def fetch_tickers():
    urls = [
        f"{BITPIN_BASE}/v1/mkt/tickers/",
        f"{BITPIN_BASE}/api/v1/mkt/tickers/",
    ]

    errors = []

    for url in urls:
        try:
            data = get_json(url)

            if isinstance(data, list):
                return data

            if isinstance(data, dict):
                for key in ("tickers", "results", "data"):
                    value = data.get(key)

                    if isinstance(value, list):
                        return value

                    if isinstance(value, dict):
                        rows = []
                        for symbol, ticker in value.items():
                            if isinstance(ticker, dict):
                                item = dict(ticker)
                                item.setdefault("symbol", symbol)
                                rows.append(item)
                        if rows:
                            return rows

            errors.append(f"{url}: unexpected response")

        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError("Tickers API failed: " + " | ".join(errors))


def get_symbol(row):
    if not isinstance(row, dict):
        return ""

    for key in ("symbol", "code", "market", "name"):
        value = row.get(key)
        if value:
            return str(value).strip().upper().replace("-", "_")

    return ""


def is_usdt_symbol(symbol):
    return symbol.endswith("_USDT") or symbol.endswith("USDT")


def ticker_price(row):
    if not isinstance(row, dict):
        return None

    for key in ("price", "last", "last_price", "close", "lastPrice"):
        try:
            value = float(row[key])
            if value > 0:
                return value
        except (KeyError, TypeError, ValueError):
            continue

    return None


def build_ticker_map(rows):
    result = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        symbol = get_symbol(row)
        price = ticker_price(row)

        if symbol and price:
            result[symbol] = row
            result[symbol.replace("_", "")] = row

    return result


def get_price(symbol, ticker_map):
    row = ticker_map.get(symbol)
    if row is None:
        row = ticker_map.get(symbol.replace("_", ""))

    return ticker_price(row) if row else None


def get_volume(row):
    if not isinstance(row, dict):
        return 0.0

    for key in (
        "quote_volume",
        "quoteVolume",
        "quoteVolume24h",
        "volume",
        "base_volume",
        "baseVolume",
    ):
        try:
            value = float(row[key])
            if value >= 0:
                return value
        except (KeyError, TypeError, ValueError):
            continue

    return 0.0


# ---------------- CANDLES ----------------
# Candle source: Binance public API.
# Price source: Bitpin.
# No real orders are placed.

def fetch_candles(symbol, timeframe):
    binance_symbol = symbol.replace("_", "").replace("-", "")
    errors = []

    for host in CANDLE_HOSTS:
        try:
            response = session.get(
                host + "/api/v3/klines",
                params={
                    "symbol": binance_symbol,
                    "interval": timeframe,
                    "limit": CANDLE_LIMIT,
                },
                timeout=TIMEOUT,
            )

            if response.status_code != 200:
                errors.append(
                    f"{host} HTTP {response.status_code}: "
                    f"{response.text[:100]}"
                )
                continue

            data = response.json()

            if not isinstance(data, list):
                errors.append(f"{host}: response is not a list")
                continue

            candles = []

            for row in data:
                if not isinstance(row, list) or len(row) < 6:
                    continue

                try:
                    candles.append({
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    })
                except (ValueError, TypeError):
                    continue

            if len(candles) >= 52:
                logging.info(
                    "CANDLES OK | %s | %s | %d",
                    symbol,
                    timeframe,
                    len(candles),
                )
                return candles

            errors.append(
                f"{host}: only {len(candles)} candles"
            )

        except Exception as exc:
            errors.append(f"{host}: {repr(exc)}")

    logging.error(
        "CANDLES FAILED | %s | %s | %s",
        symbol,
        timeframe,
        " || ".join(errors)[:600],
    )

    return []


# ---------------- INDICATORS ----------------

def ema_series(values, period):
    if len(values) < period:
        return []

    multiplier = 2.0 / (period + 1)
    current = sum(values[:period]) / period
    result = [None] * (period - 1) + [current]

    for value in values[period:]:
        current = (
            value * multiplier
            + current * (1 - multiplier)
        )
        result.append(current)

    return result


def calculate_rsi(closes, period=14):
    if len(closes) <= period:
        return None

    changes = [
        closes[i] - closes[i - 1]
        for i in range(1, len(closes))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0

    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def calculate_atr(candles, period=14):
    if len(candles) <= period:
        return None

    ranges = []

    for i in range(1, len(candles)):
        candle = candles[i]
        previous_close = candles[i - 1]["close"]

        ranges.append(max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous_close),
            abs(candle["low"] - previous_close),
        ))

    atr = sum(ranges[:period]) / period

    for value in ranges[period:]:
        atr = (atr * (period - 1) + value) / period

    return atr


def analyze_candles(candles):
    if len(candles) < 52:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    ema20 = ema_series(closes, 20)
    ema50 = ema_series(closes, 50)
    rsi = calculate_rsi(closes)
    atr = calculate_atr(candles)

    if (
        not ema20
        or not ema50
        or rsi is None
        or atr is None
    ):
        return None

    avg_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = (
        volumes[-1] / avg_volume
        if avg_volume > 0 else 0
    )

    close = closes[-1]

    if close > ema20[-1] > ema50[-1]:
        trend = "LONG"
    elif close < ema20[-1] < ema50[-1]:
        trend = "SHORT"
    else:
        trend = "NEUTRAL"

    return {
        "close": close,
        "ema20": ema20[-1],
        "ema50": ema50[-1],
        "rsi": rsi,
        "atr": atr,
        "volume_ratio": volume_ratio,
        "trend": trend,
    }


# ---------------- SIGNAL ENGINE ----------------

def make_signal(symbol, price, a15, a1h):
    if not a15 or not a1h or price <= 0:
        return None

    # Both timeframes must agree.
    direction = a15["trend"]

    if direction not in ("LONG", "SHORT"):
        return None

    if a1h["trend"] != direction:
        return None

    # Mandatory volume filter.
    if a15["volume_ratio"] < MIN_VOLUME_RATIO:
        return None

    rsi15 = a15["rsi"]
    rsi1h = a1h["rsi"]

    if direction == "LONG":
        if not (MIN_RSI_LONG <= rsi15 <= MAX_RSI_LONG):
            return None
        if rsi1h <= 50:
            return None
        if rsi15 < 45:
            return None

    else:
        if not (MIN_RSI_SHORT <= rsi15 <= MAX_RSI_SHORT):
            return None
        if rsi1h >= 50:
            return None
        if rsi15 > 55:
            return None

    score = 0
    reasons = []

    # Trend agreement.
    score += 30
    reasons.append("تأیید روند در هر دو تایم‌فریم")

    # EMA separation.
    if direction == "LONG":
        separation = (
            a15["ema20"] - a15["ema50"]
        ) / a15["ema50"] * 100

    else:
        separation = (
            a15["ema50"] - a15["ema20"]
        ) / a15["ema50"] * 100

    if separation > 0.10:
        score += 15
        reasons.append("فاصله مناسب EMA")

    # RSI strength.
    if direction == "LONG" and 50 <= rsi15 <= 65:
        score += 15
        reasons.append("RSI مناسب خرید")

    elif direction == "SHORT" and 35 <= rsi15 <= 50:
        score += 15
        reasons.append("RSI مناسب فروش")

    # Volume confirmation is mandatory above.
    score += 20
    reasons.append("حجم حداقل 1.15 برابر میانگین")

    # Hourly RSI confirmation.
    if direction == "LONG" and rsi1h >= 55:
        score += 10
    elif direction == "SHORT" and rsi1h <= 45:
        score += 10

    # 15-minute candle agrees with direction.
    if direction == "LONG" and a15["close"] > a15["ema20"]:
        score += 10
    elif direction == "SHORT" and a15["close"] < a15["ema20"]:
        score += 10

    if score < MIN_SCORE:
        return None

    atr = a15["atr"]

    if atr <= 0:
        return None

    # Divide the simulated capital between up to 3 signals.
    margin_per_signal = CAPITAL / MAX_SIGNALS
    notional = margin_per_signal * LEVERAGE
    quantity = notional / price

    stop_distance = 1.5 * atr

    if direction == "LONG":
        stop = price - stop_distance
        tp1 = price + 1.5 * atr
        tp2 = price + 2.2 * atr
        tp3 = price + 3.0 * atr
    else:
        stop = price + stop_distance
        tp1 = price - 1.5 * atr
        tp2 = price - 2.2 * atr
        tp3 = price - 3.0 * atr

    estimated_loss = quantity * stop_distance

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "price": price,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "volume_ratio": a15["volume_ratio"],
        "margin": margin_per_signal,
        "notional": notional,
        "loss": estimated_loss,
        "reasons": reasons,
    }


# ---------------- TELEGRAM FORMAT ----------------

def fmt(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def make_message(selected, analyzed, failed, signals):
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    lines = [
        "🐋 <b>ETH WHALE</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>BITPIN SMART MARKET WATCH</b>",
        "🧪 PAPER SIGNALS ONLY",
        "⛔ Real Orders: <b>OFF</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 سرمایه آزمایشی: <b>{CAPITAL:.2f} USDT</b>",
        f"⚙️ اهرم شبیه‌سازی: <b>{LEVERAGE}x</b>",
        f"📦 ارزش فرضی هر موقعیت: <b>{CAPITAL / MAX_SIGNALS * LEVERAGE:.2f} USDT</b>",
        "⏱ تایم‌فریم: <b>15m + 1h</b>",
        "📈 قیمت لحظه‌ای: Bitpin",
        "🕯 کندل‌ها: Binance public API",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔎 بازارهای انتخاب‌شده: <b>{selected}</b>",
        f"✅ تحلیل موفق: <b>{analyzed}</b>",
        f"⚠️ خطای کندل/تحلیل: <b>{failed}</b>",
        f"🎯 سیگنال معتبر: <b>{len(signals)}</b>",
    ]

    if analyzed == 0:
        lines += [
            "━━━━━━━━━━━━━━━━━━━━",
            "🚨 <b>تحلیل انجام نشد</b>",
            "دریافت کندل ناموفق بوده است؛ سیگنال صادر نشد.",
        ]

    elif not signals:
        lines += [
            "━━━━━━━━━━━━━━━━━━━━",
            "🔍 سیگنال منطبق با فیلترهای جدید پیدا نشد.",
            "فیلتر حجم و RSI اجباری است.",
        ]

    for i, s in enumerate(signals, 1):
        emoji = "🟢" if s["direction"] == "LONG" else "🔴"
        quality = "⭐ قوی" if s["score"] >= STRONG_SCORE else "🔹 متعادل"

        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            f"{emoji} <b>سیگنال {i}: {s['symbol']}</b>",
            f"📍 جهت: <b>{s['direction']}</b> | {quality}",
            f"🧠 امتیاز: <b>{s['score']}/100</b>",
            f"💵 ورود فرضی: <code>{fmt(s['price'])}</code>",
            f"🛑 حد ضرر: <code>{fmt(s['stop'])}</code>",
            f"🎯 TP1: <code>{fmt(s['tp1'])}</code>",
            f"🎯 TP2: <code>{fmt(s['tp2'])}</code>",
            f"🎯 TP3: <code>{fmt(s['tp3'])}</code>",
            f"📊 RSI 15m: {s['rsi15']:.1f}",
            f"📊 RSI 1h: {s['rsi1h']:.1f}",
            f"🔊 حجم: {s['volume_ratio']:.2f}x میانگین",
            f"💰 مارجین فرضی: {s['margin']:.2f} USDT",
            f"📦 ارزش موقعیت: {s['notional']:.2f} USDT",
            f"⚠️ زیان تخمینی تا SL: {s['loss']:.3f} USDT",
            "📝 " + "، ".join(s["reasons"]),
            "⚠️ آزمایشی است؛ سود تضمین‌شده نیست.",
        ]

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🕒 زمان اجرا: {now}",
        "🛡️ هیچ سفارش واقعی ثبت نشده است.",
    ]

    return "\n".join(lines)


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram secrets missing")
        print(message)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Telegram maximum message length is 4096 characters.
    chunks = []
    while len(message) > 3800:
        cut = message.rfind("\n", 0, 3800)
        if cut < 1:
            cut = 3800
        chunks.append(message[:cut])
        message = message[cut:].lstrip("\n")
    chunks.append(message)

    all_ok = True

    for chunk in chunks:
        try:
            response = session.post(
                url,
                json={
                    "chat_id": CHAT_ID,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=TIMEOUT,
            )

            if response.status_code != 200:
                logging.error(
                    "Telegram HTTP %s: %s",
                    response.status_code,
                    response.text[:250],
                )
                all_ok = False
            elif not response.json().get("ok", False):
                logging.error("Telegram rejected message: %s", response.text[:250])
                all_ok = False

        except Exception:
            logging.exception("Telegram send failed")
            all_ok = False

        time.sleep(0.3)

    return all_ok


# ---------------- MAIN ----------------

def run_scan():
    markets = fetch_markets()
    tickers = fetch_tickers()
    ticker_map = build_ticker_map(tickers)

    candidates = []

    for market in markets:
        symbol = get_symbol(market)

        if not symbol or not is_usdt_symbol(symbol):
            continue

        price = get_price(symbol, ticker_map)

        if price is None or price <= 0:
            continue

        candidates.append((symbol, price))

    # Prefer higher-volume markets when the ticker supplies volume.
    def volume_key(item):
        row = ticker_map.get(item[0])
        if row is None:
            row = ticker_map.get(item[0].replace("_", ""))
        return get_volume(row) if row else 0.0

    candidates.sort(key=volume_key, reverse=True)
    candidates = candidates[:MAX_MARKETS]

    analyzed = 0
    failed = 0
    signals = []

    logging.info(
        "Candidates=%d | tickers=%d",
        len(candidates),
        len(ticker_map),
    )

    for symbol, price in candidates:
        try:
            c15 = fetch_candles(symbol, "15m")
            c1h = fetch_candles(symbol, "1h")

            if not c15 or not c1h:
                failed += 1
                continue

            a15 = analyze_candles(c15)
            a1h = analyze_candles(c1h)

            if not a15 or not a1h:
                failed += 1
                continue

            analyzed += 1

            signal = make_signal(symbol, price, a15, a1h)

            if signal:
                signals.append(signal)

        except Exception:
            failed += 1
            logging.exception("Analysis error for %s", symbol)

        time.sleep(PAUSE)

    signals.sort(key=lambda s: s["score"], reverse=True)
    signals = signals[:MAX_SIGNALS]

    message = make_message(
        selected=len(candidates),
        analyzed=analyzed,
        failed=failed,
        signals=signals,
    )

    print(message)
    send_telegram(message)

    logging.info(
        "SCAN COMPLETE | selected=%d | analyzed=%d | failed=%d | signals=%d",
        len(candidates),
        analyzed,
        failed,
        len(signals),
    )

    if candidates and analyzed == 0:
        raise RuntimeError(
            "No markets analyzed. See CANDLES FAILED logs above."
        )


def main():
    logging.info("ETH WHALE PAPER BOT STARTED")
    logging.info("REAL ORDERS ARE DISABLED")

    run_scan()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("BOT FAILED: %s", repr(exc))
        send_telegram(
            "🐋 <b>ETH WHALE — خطای اجرا</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "❌ اسکن کامل نشد.\n"
            "⛔ هیچ سفارش واقعی ارسال نشده است.\n"
            f"🔎 <code>{str(exc)[:700]}</code>"
        )
        raise
