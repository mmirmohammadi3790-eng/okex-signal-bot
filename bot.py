
import os
import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# ============================================================
# ETH WHALE | BITPIN SMART SIGNAL BOT
# PAPER TRADING ONLY - NO REAL ORDERS
# Capital: 48 USDT | Leverage: 3x
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
CAPITAL_USDT = 48.0
LEVERAGE = 3
MARGIN_PER_TRADE = 16.0
MAX_NOTIONAL = MARGIN_PER_TRADE * LEVERAGE

RISK_PERCENT = 1.0
MIN_SCORE = 70
STRONG_SCORE = 80
MIN_RR = 1.5
MIN_VOLUME_RATIO = 1.15
MAX_MARKETS = 30
MAX_SIGNALS = 3
TIMEOUT = 15
PAPER_MODE = True
REAL_ORDERS_ENABLED = False

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or ""
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BITPIN_BASES = [
    "https://api.bitpin.ir",
    "https://api.bitpin.org",
]
BINANCE_BASE = "https://api.binance.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-PaperBot/1.0",
    "Accept": "application/json",
})


# ---------------- TELEGRAM ----------------

def escape_html(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def telegram_send(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram credentials missing")
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
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("ok", False)

    except Exception as exc:
        logging.error("Telegram error: %s", exc)
        return False


# ---------------- HTTP ----------------

def get_json(url, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def rows_from(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "results", "data", "markets", "tickers",
            "items", "symbols", "payload"
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                result = rows_from(value)
                if result:
                    return result

    return []


def first_value(item, keys):
    if not isinstance(item, dict):
        return None

    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value

    return None


def normalize_symbol(value):
    return (
        str(value)
        .upper()
        .replace("-", "_")
        .replace("/", "_")
        .replace(" ", "")
    )


# ---------------- BITPIN MARKET DATA ----------------

def bitpin_get(paths):
    errors = []

    for base in BITPIN_BASES:
        for path in paths:
            try:
                return get_json(base + path)
            except Exception as exc:
                errors.append(
                    f"{path}: {type(exc).__name__}"
                )

    raise RuntimeError(
        "Bitpin API unavailable: " + "; ".join(errors[-4:])
    )


def load_markets():
    market_data = bitpin_get([
        "/api/v1/mkt/markets/",
        "/v1/mkt/markets/",
        "/api/v1/spot/public/pairs",
    ])

    ticker_data = bitpin_get([
        "/api/v1/mkt/tickers/",
        "/v1/mkt/tickers/",
        "/api/v1/spot/public/tickers",
    ])

    market_rows = rows_from(market_data)
    ticker_rows = rows_from(ticker_data)

    if not market_rows:
        raise RuntimeError(
            "Bitpin markets response contains no market list"
        )

    if not ticker_rows:
        raise RuntimeError(
            "Bitpin tickers response contains no ticker list"
        )

    ticker_map = {}

    for item in ticker_rows:
        symbol = first_value(
            item,
            ["symbol", "market", "pair", "code", "name"],
        )
        price = first_value(
            item,
            [
                "last", "last_price", "lastPrice",
                "price", "close", "last_trade_price"
            ],
        )

        if symbol is None or price is None:
            continue

        try:
            price = float(price)
            if price > 0:
                ticker_map[normalize_symbol(symbol)] = price
        except (TypeError, ValueError):
            continue

    excluded = {
        "USDT", "USDC", "BUSD", "DAI", "FDUSD",
        "TUSD", "USDE", "WBTC", "STETH",
    }

    markets = []

    for item in market_rows:
        symbol_raw = first_value(
            item,
            ["symbol", "market", "pair", "code", "name"],
        )

        if symbol_raw is None:
            continue

        symbol = normalize_symbol(symbol_raw)

        if not symbol.endswith("_USDT"):
            continue

        asset = symbol[:-5]

        if asset in excluded:
            continue

        if any(
            tag in asset
            for tag in ("3L", "3S", "5L", "5S", "2L", "2S")
        ):
            continue

        if symbol not in ticker_map:
            continue

        markets.append({
            "symbol": symbol,
            "asset": asset,
            "price": ticker_map[symbol],
        })

    if not markets:
        raise RuntimeError(
            "No USDT markets matched ticker symbols"
        )

    return markets


# ---------------- CANDLES ----------------

def load_candles(asset, interval, limit=150):
    symbol = asset.upper() + "USDT"

    data = get_json(
        BINANCE_BASE + "/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )

    if not isinstance(data, list) or len(data) < 60:
        raise RuntimeError(
            f"Insufficient {interval} candles for {symbol}"
        )

    columns = [
        "open_time", "open", "high", "low", "close",
        "volume", "close_time", "quote_volume",
        "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ]

    df = pd.DataFrame(data, columns=columns)

    for col in [
        "open", "high", "low", "close",
        "volume", "quote_volume",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Exclude the last potentially unfinished candle.
    df = df.iloc[:-1].copy()
    df.dropna(inplace=True)

    return df


# ---------------- INDICATORS ----------------

def indicators(frame):
    df = frame.copy()

    df["ema20"] = df["close"].ewm(
        span=20, adjust=False
    ).mean()

    df["ema50"] = df["close"].ewm(
        span=50, adjust=False
    ).mean()

    delta = df["close"].diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    avg_loss = losses.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    previous = df["close"].shift(1)

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous).abs(),
        (df["low"] - previous).abs(),
    ], axis=1).max(axis=1)

    df["atr"] = tr.ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    df["volume_avg"] = df["volume"].rolling(20).mean()

    df["volume_ratio"] = (
        df["volume"]
        / df["volume_avg"].replace(0, np.nan)
    )

    return df


# ---------------- SIGNAL ANALYSIS ----------------

def analyze_market(market):
    asset = market["asset"]

    df15 = indicators(load_candles(asset, "15m"))
    df1h = indicators(load_candles(asset, "1h"))

    a = df15.iloc[-1]
    b = df1h.iloc[-1]

    price = float(a["close"])
    atr = float(a["atr"])
    rsi15 = float(a["rsi"])
    rsi1h = float(b["rsi"])
    volume_ratio = float(a["volume_ratio"])

    if not all(np.isfinite(x) for x in [
        price, atr, rsi15, rsi1h
    ]):
        raise RuntimeError("Invalid indicator values")

    if price <= 0 or atr <= 0:
        raise RuntimeError("Invalid price or ATR")

    if not np.isfinite(volume_ratio):
        volume_ratio = 0.0

    e20_15 = float(a["ema20"])
    e50_15 = float(a["ema50"])
    e20_1h = float(b["ema20"])
    e50_1h = float(b["ema50"])

    recent = df15.tail(40)
    support = float(recent["low"].min())
    resistance = float(recent["high"].max())

    long_score = 0
    short_score = 0
    long_reasons = []
    short_reasons = []

    # 1. EMA trend: 25 points.
    if e20_15 > e50_15:
        long_score += 15
        long_reasons.append("EMA 15m صعودی")
    elif e20_15 < e50_15:
        short_score += 15
        short_reasons.append("EMA 15m نزولی")

    if e20_1h > e50_1h:
        long_score += 10
        long_reasons.append("EMA یک‌ساعته صعودی")
    elif e20_1h < e50_1h:
        short_score += 10
        short_reasons.append("EMA یک‌ساعته نزولی")

    # 2. RSI: 15 points.
    if 50 < rsi15 < 70 and rsi1h > 50:
        long_score += 15
        long_reasons.append("RSI تأیید خریدار")
    elif 30 < rsi15 < 50 and rsi1h < 50:
        short_score += 15
        short_reasons.append("RSI تأیید فروشنده")

    # 3. Volume: 15 points.
    if volume_ratio >= MIN_VOLUME_RATIO:
        if price > float(a["open"]):
            long_score += 15
            long_reasons.append("حجم صعودی")
        elif price < float(a["open"]):
            short_score += 15
            short_reasons.append("حجم نزولی")

    # 4. Price structure and room to barrier: 20 points.
    room_up = (resistance - price) / price
    room_down = (price - support) / price

    if (
        price > e20_15
        and price < resistance
        and room_up >= 0.005
    ):
        long_score += 20
        long_reasons.append("فضای کافی تا مقاومت")

    if (
        price < e20_15
        and price > support
        and room_down >= 0.005
    ):
        short_score += 20
        short_reasons.append("فضای کافی تا حمایت")

    # 5. Higher timeframe confirmation: 15 points.
    if e20_1h > e50_1h and rsi1h > 50:
        long_score += 15
        long_reasons.append("تأیید روند یک‌ساعته")

    if e20_1h < e50_1h and rsi1h < 50:
        short_score += 15
        short_reasons.append("تأیید روند یک‌ساعته")

    # 6. Risk/reward: 10 points.
    stop_distance = max(1.5 * atr, price * 0.003)

    long_sl = price - stop_distance
    long_tp1 = price + stop_distance * MIN_RR
    long_tp2 = price + stop_distance * 2
    long_tp3 = price + stop_distance * 3

    short_sl = price + stop_distance
    short_tp1 = price - stop_distance * MIN_RR
    short_tp2 = price - stop_distance * 2
    short_tp3 = price - stop_distance * 3

    if long_tp1 < resistance and long_sl > 0:
        long_score += 10
        long_reasons.append("نسبت سود به ضرر مناسب")

    if short_tp1 > support and short_tp3 > 0:
        short_score += 10
        short_reasons.append("نسبت سود به ضرر مناسب")

    long_confirmed = (
        e20_15 > e50_15
        and e20_1h > e50_1h
        and rsi1h > 50
    )

    short_confirmed = (
        e20_15 < e50_15
        and e20_1h < e50_1h
        and rsi1h < 50
    )

    if (
        long_score >= MIN_SCORE
        and long_confirmed
        and long_score > short_score
        and long_tp1 < resistance
    ):
        side = "LONG"
        score = long_score
        sl = long_sl
        tp1, tp2, tp3 = long_tp1, long_tp2, long_tp3
        reasons = long_reasons

    elif (
        short_score >= MIN_SCORE
        and short_confirmed
        and short_score > long_score
        and short_tp1 > support
    ):
        side = "SHORT"
        score = short_score
        sl = short_sl
        tp1, tp2, tp3 = short_tp1, short_tp2, short_tp3
        reasons = short_reasons

    else:
        return {
            "symbol": market["symbol"],
            "side": "WAIT",
            "score": max(long_score, short_score),
            "reason": (
                "روند یا امتیاز کافی نیست؛ "
                "یا فاصله تا حمایت/مقاومت مناسب نیست"
            ),
        }

    rr = abs(tp1 - price) / abs(price - sl)

    if rr < MIN_RR:
        return {
            "symbol": market["symbol"],
            "side": "WAIT",
            "score": score,
            "reason": "نسبت سود به ضرر ناکافی",
        }

    # Risk-based sizing with a maximum notional cap.
    risk_budget = CAPITAL_USDT * RISK_PERCENT / 100
    qty_by_risk = risk_budget / abs(price - sl)
    qty_by_notional = MAX_NOTIONAL / price

    quantity = min(qty_by_risk, qty_by_notional)

    notional = quantity * price
    margin = notional / LEVERAGE
    estimated_risk = quantity * abs(price - sl)

    return {
        "symbol": market["symbol"],
        "side": side,
        "score": score,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi15": rsi15,
        "rsi1h": rsi1h,
        "volume_ratio": volume_ratio,
        "support": support,
        "resistance": resistance,
        "rr": rr,
        "notional": notional,
        "margin": margin,
        "risk": estimated_risk,
        "reasons": reasons,
    }


# ---------------- MESSAGE FORMATTING ----------------

def fmt(value):
    value = float(value)

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.5f}".rstrip("0").rstrip(".")

    return f"{value:.8f}".rstrip("0").rstrip(".")


def signal_message(s):
    emoji = "🟢" if s["side"] == "LONG" else "🔴"
    strength = (
        "🔥 قوی"
        if s["score"] >= STRONG_SCORE
        else "✅ قابل بررسی"
    )

    reasons = "\n".join(
        "• " + escape_html(x)
        for x in s["reasons"]
    )

    return (
        f"<b>{BOT_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>{s['side']} | "
        f"{escape_html(s['symbol'])}</b>\n"
        f"⭐ امتیاز: <b>{s['score']}/100</b>\n"
        f"📌 قدرت: {strength}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Entry: <code>{fmt(s['entry'])}</code>\n"
        f"🛑 SL: <code>{fmt(s['sl'])}</code>\n"
        f"🥇 TP1: <code>{fmt(s['tp1'])}</code>\n"
        f"🥈 TP2: <code>{fmt(s['tp2'])}</code>\n"
        f"🥉 TP3: <code>{fmt(s['tp3'])}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI 15m: {s['rsi15']:.1f}\n"
        f"📊 RSI 1h: {s['rsi1h']:.1f}\n"
        f"📦 حجم/میانگین: {s['volume_ratio']:.2f}x\n"
        f"⚖️ R/R تا TP1: {s['rr']:.2f}\n"
        f"💵 مارجین تخمینی: {s['margin']:.2f} USDT\n"
        f"📈 ارزش موقعیت: {s['notional']:.2f} USDT\n"
        f"⚠️ ریسک تا SL: {s['risk']:.2f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>دلایل سیگنال</b>\n{reasons}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧪 PAPER TRADING ONLY\n"
        f"🚫 سفارش واقعی غیرفعال است"
    )


# ---------------- SCAN ENGINE ----------------

def run_scan():
    start = time.time()

    telegram_send(
        f"<b>{BOT_NAME}</b>\n"
        f"🔎 اسکن بازار آغاز شد\n"
        f"🧪 آزمایشی | بدون سفارش واقعی"
    )

    markets = load_markets()
    markets = markets[:MAX_MARKETS]

    signals = []
    rejected = []
    errors = 0

    for market in markets:
        try:
            result = analyze_market(market)

            if result["side"] in ("LONG", "SHORT"):
                signals.append(result)
            else:
                rejected.append(
                    (result["symbol"], result["reason"])
                )

        except Exception as exc:
            errors += 1
            logging.warning(
                "%s analysis failed: %s",
                market["symbol"],
                exc,
            )

        time.sleep(0.15)

    signals.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    selected = signals[:MAX_SIGNALS]

    for signal in selected:
        telegram_send(signal_message(signal))
        time.sleep(0.5)

    status = (
        "✅ سیگنال ارسال شد"
        if selected
        else "⚪ WAIT — سیگنال معتبر پیدا نشد"
    )

    report = (
        f"<b>{BOT_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>گزارش اسکن بازار</b>\n"
        f"{status}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔎 بازارهای بررسی‌شده: {len(markets)}\n"
        f"📈 سیگنال‌های معتبر: {len(signals)}\n"
        f"📨 سیگنال‌های ارسالی: {len(selected)}\n"
        f"⚪ بازارهای ردشده: {len(rejected)}\n"
        f"⚠️ خطاهای تحلیل: {errors}\n"
        f"⏱ زمان اسکن: {time.time() - start:.1f} ثانیه\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT\n"
        f"⚙️ اهرم محاسباتی: {LEVERAGE}x\n"
        f"🧪 Paper Trading: ON\n"
        f"🚫 Real Orders: OFF"
    )

    if rejected:
        report += "\n\n<b>نمونه دلایل WAIT</b>\n"

        for symbol, reason in rejected[:5]:
            report += (
                f"• {escape_html(symbol)}: "
                f"{escape_html(reason)}\n"
            )

    telegram_send(report)

    logging.info(
        "Scan complete: markets=%s signals=%s errors=%s",
        len(markets),
        len(selected),
        errors,
    )


# ---------------- ENTRY POINT ----------------

def main():
    if not PAPER_MODE or REAL_ORDERS_ENABLED:
        raise RuntimeError(
            "Safety check failed: paper mode is required"
        )

    command = os.getenv(
        "BOT_COMMAND", "scan"
    ).strip().lower()

    if command == "test":
        telegram_send(
            f"<b>{BOT_NAME}</b>\n"
            f"✅ اتصال تلگرام آزمایش شد\n"
            f"🧪 حالت آزمایشی فعال\n"
            f"🚫 سفارش واقعی غیرفعال"
        )
        return

    if command == "status":
        telegram_send(
            f"<b>{BOT_NAME}</b>\n"
            f"💰 سرمایه: {CAPITAL_USDT} USDT\n"
            f"⚙️ اهرم: {LEVERAGE}x\n"
            f"🧪 Paper Trading: ON\n"
            f"🚫 Real Orders: OFF"
        )
        return

    run_scan()


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        logging.exception("Bot failed")

        telegram_send(
            f"<b>{BOT_NAME}</b>\n"
            f"❌ <b>اسکن کامل نشد</b>\n"
            f"علت: <code>{escape_html(str(exc)[:800])}</code>\n"
            f"🧪 حالت آزمایشی فعال است\n"
            f"🚫 هیچ سفارش واقعی ثبت نشده است"
        )

        raise
