
import os
import sys
import json
import time
import base64
import logging
import threading
from datetime import datetime, timezone

import requests
import websocket

# ============================================================
# ETH WHALE | BITPIN WEBSOCKET PAPER SPOT SIGNAL BOT
# PAPER ONLY - NO REAL ORDERS - NO LEVERAGE
# ============================================================

BOT_NAME = "🐋 ETH WHALE"

BASE_URL = "https://api.bitpin.org"
WS_URL = "wss://centrifugo.bitpin.org/connection/websocket"

MARKETS_URL = BASE_URL + "/v1/mkt/markets/"
HISTORY_FILE = "data/market_history.json"

CAPITAL_USDT = 48.0
MAX_MARKETS = 25
MAX_SIGNALS = 3
TIMEFRAME = "15m"
CANDLE_SECONDS = 15 * 60
MIN_CANDLES = 21

PAPER_MODE = True
REAL_ORDERS_ENABLED = False

WS_LISTEN_SECONDS = 24
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
REQUEST_DELAY_SECONDS = 0.5

MAX_HISTORY_CANDLES = 250
MAX_MARKET_AGE_MINUTES = 30

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME", "main").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-Paper-Bot/10.0",
    "Accept": "application/json",
})

state_lock = threading.Lock()
received_candles = {}
subscribed_symbols = []
ws_connected = False
ws_ready = threading.Event()
ws_error = None


# ============================================================
# GENERAL HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_text():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(value):
    if not value:
        return ""

    value = str(value).strip().upper()
    value = value.replace("-", "_").replace("/", "_")

    return value


def symbol_from_market(market):
    for key in ("symbol", "code", "market", "name", "ticker"):
        value = market.get(key)

        if isinstance(value, str):
            symbol = normalize_symbol(value)

            if "_" in symbol and symbol.endswith("_USDT"):
                return symbol

    base = (
        market.get("currency1")
        or market.get("base_currency")
        or market.get("base")
    )
    quote = (
        market.get("currency2")
        or market.get("quote_currency")
        or market.get("quote")
    )

    if base and quote:
        if str(quote).upper() == "USDT":
            return normalize_symbol(f"{base}_USDT")

    return ""


def market_volume(market):
    for key in (
        "quote_volume",
        "volume_24h",
        "volume",
        "value",
        "amount",
        "trading_volume",
    ):
        value = safe_float(market.get(key))
        if value > 0:
            return value

    return 0.0


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
        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            logging.info("Telegram message sent.")
            return True

        logging.error(
            "Telegram error: HTTP %s %s",
            response.status_code,
            response.text[:300],
        )

    except requests.RequestException as exc:
        logging.error("Telegram request failed: %s", exc)

    return False


# ============================================================
# BITPIN MARKET LIST
# ============================================================

def get_markets():
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                MARKETS_URL,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, dict):
                markets = payload.get("results", [])
            elif isinstance(payload, list):
                markets = payload
            else:
                markets = []

            if not isinstance(markets, list) or not markets:
                raise ValueError(
                    "Bitpin returned an empty or unexpected market list."
                )

            selected = {}

            for market in markets:
                if not isinstance(market, dict):
                    continue

                symbol = symbol_from_market(market)

                if not symbol or not symbol.endswith("_USDT"):
                    continue

                if market.get("tradable") is False:
                    continue

                # Keep one entry per market.
                selected[symbol] = {
                    "symbol": symbol,
                    "volume": market_volume(market),
                }

            result = sorted(
                selected.values(),
                key=lambda item: item["volume"],
                reverse=True,
            )[:MAX_MARKETS]

            if not result:
                raise ValueError(
                    "No tradable USDT markets were recognized."
                )

            logging.info("Selected %s USDT markets.", len(result))
            return [item["symbol"] for item in result]

        except (
            requests.RequestException,
            ValueError,
            TypeError,
        ) as exc:
            last_error = exc
            logging.warning(
                "Market request attempt %s/%s failed: %s",
                attempt,
                MAX_RETRIES,
                exc,
            )

            if attempt < MAX_RETRIES:
                time.sleep(attempt * 3)

    raise RuntimeError(
        "Could not retrieve Bitpin markets: " + str(last_error)
    )


# ============================================================
# GITHUB HISTORY PERSISTENCE
# ============================================================

def github_file_url():
    if not GITHUB_REPOSITORY:
        return None

    return (
        "https://api.github.com/repos/"
        + GITHUB_REPOSITORY
        + "/contents/"
        + HISTORY_FILE
    )


def load_history():
    url = github_file_url()

    if url and GITHUB_TOKEN:
        try:
            response = session.get(
                url,
                headers={
                    "Authorization": "Bearer " + GITHUB_TOKEN,
                    "Accept": "application/vnd.github+json",
                },
                params={"ref": GITHUB_REF_NAME},
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                payload = response.json()
                encoded = payload.get("content", "")
                decoded = base64.b64decode(encoded).decode("utf-8")
                data = json.loads(decoded)

                if isinstance(data, dict):
                    logging.info("History loaded from GitHub.")
                    return data

            elif response.status_code != 404:
                logging.warning(
                    "GitHub history read returned HTTP %s.",
                    response.status_code,
                )

        except Exception as exc:
            logging.warning("GitHub history read failed: %s", exc)

    # Local fallback. On GitHub Actions, the workspace is temporary;
    # GitHub persistence is needed to retain history between runs.
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)

            if isinstance(data, dict):
                return data

    except Exception as exc:
        logging.warning("Local history read failed: %s", exc)

    return {"markets": {}}


def save_history(history):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)

    content = json.dumps(
        history,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        file.write(content)

    url = github_file_url()

    if not url or not GITHUB_TOKEN:
        logging.warning(
            "History saved locally only; GitHub persistence is unavailable."
        )
        return False

    headers = {
        "Authorization": "Bearer " + GITHUB_TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            existing = session.get(
                url,
                headers=headers,
                params={"ref": GITHUB_REF_NAME},
                timeout=REQUEST_TIMEOUT,
            )

            sha = None

            if existing.status_code == 200:
                sha = existing.json().get("sha")
            elif existing.status_code != 404:
                existing.raise_for_status()

            body = {
                "message": "Update ETH WHALE market candle history",
                "content": base64.b64encode(
                    content.encode("utf-8")
                ).decode("ascii"),
                "branch": GITHUB_REF_NAME,
            }

            if sha:
                body["sha"] = sha

            response = session.put(
                url,
                headers=headers,
                json=body,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code in (200, 201):
                logging.info("History persisted to GitHub.")
                return True

            logging.warning(
                "GitHub history save HTTP %s: %s",
                response.status_code,
                response.text[:250],
            )

            # A SHA conflict can happen if another run changed the file.
            if response.status_code not in (409, 422):
                response.raise_for_status()

        except Exception as exc:
            logging.warning(
                "GitHub save attempt %s/%s failed: %s",
                attempt,
                MAX_RETRIES,
                exc,
            )

        if attempt < MAX_RETRIES:
            time.sleep(attempt * 2)

    return False


# ============================================================
# WEBSOCKET CANDLE COLLECTION
# ============================================================

def process_ws_message(ws, raw_message):
    global ws_connected, ws_error

    try:
        message = json.loads(raw_message)
    except (json.JSONDecodeError, TypeError):
        return

    # Centrifugo connection response.
    if isinstance(message, dict) and "connect" in message:
        if message.get("error"):
            ws_error = str(message["error"])
            logging.error("WebSocket connect error: %s", ws_error)
            ws_ready.set()
            return

        ws_connected = True
        logging.info("WebSocket connected.")

        # Subscribe to public market channels.
        for index, symbol in enumerate(subscribed_symbols, start=2):
            command = {
                "id": index,
                "subscribe": {
                    "channel": "market:" + symbol,
                },
            }

            try:
                ws.send(json.dumps(command))
            except Exception as exc:
                logging.warning(
                    "Subscribe failed for %s: %s",
                    symbol,
                    exc,
                )

        ws_ready.set()
        return

    # Server-side push format:
    # {"push":{"channel":"market:BTC_USDT","pub":{"data":{...}}}}
    push = message.get("push") if isinstance(message, dict) else None

    if not isinstance(push, dict):
        return

    channel = push.get("channel", "")
    publication = push.get("pub", {})

    if not isinstance(publication, dict):
        return

    data = publication.get("data", {})

    if not isinstance(data, dict):
        return

    symbol = normalize_symbol(
        data.get("symbol")
        or channel.replace("market:", "")
    )

    if not symbol:
        return

    candles = data.get("candles", [])

    if not isinstance(candles, list):
        return

    now_ts = int(time.time())

    with state_lock:
        bucket = received_candles.setdefault(symbol, {})

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            if candle.get("resolution") != TIMEFRAME:
                continue

            timestamp = int(safe_float(candle.get("ts"), -1))

            if timestamp <= 0:
                continue

            # Do not use an unfinished candle for signal confirmation.
            if timestamp + CANDLE_SECONDS > now_ts:
                continue

            try:
                normalized = {
                    "ts": timestamp,
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(candle.get("volume", 0)),
                }
            except (KeyError, TypeError, ValueError):
                continue

            if (
                normalized["open"] <= 0
                or normalized["high"] <= 0
                or normalized["low"] <= 0
                or normalized["close"] <= 0
            ):
                continue

            bucket[timestamp] = normalized


def on_ws_open(ws):
    logging.info("WebSocket transport opened.")

    # Public market channels do not require a private user token.
    # This is the standard Centrifugo JSON connect command.
    try:
        ws.send(json.dumps({
            "id": 1,
            "connect": {},
        }))
    except Exception as exc:
        global ws_error
        ws_error = str(exc)
        ws_ready.set()


def on_ws_error(ws, error):
    global ws_error
    ws_error = str(error)
    logging.error("WebSocket error: %s", error)
    ws_ready.set()


def on_ws_close(ws, status_code, message):
    global ws_connected
    ws_connected = False
    logging.warning(
        "WebSocket closed: %s %s",
        status_code,
        message,
    )


def collect_candles(symbols):
    global received_candles, subscribed_symbols
    global ws_connected, ws_error

    with state_lock:
        received_candles = {}
        subscribed_symbols = list(symbols)

    ws_connected = False
    ws_error = None
    ws_ready.clear()

    app = websocket.WebSocketApp(
        WS_URL,
        on_open=on_ws_open,
        on_message=process_ws_message,
        on_error=on_ws_error,
        on_close=on_ws_close,
    )

    thread = threading.Thread(
        target=lambda: app.run_forever(
            ping_interval=20,
            ping_timeout=10,
        ),
        daemon=True,
    )
    thread.start()

    # Wait for a connection response or an error.
    ws_ready.wait(timeout=12)

    if not ws_connected:
        app.close()
        raise RuntimeError(
            "WebSocket did not confirm connection. "
            + str(ws_error or "No connection response received.")
        )

    # The documentation says market candle updates are sent
    # periodically. Keep the connection open to collect them.
    time.sleep(WS_LISTEN_SECONDS)
    app.close()
    thread.join(timeout=3)

    with state_lock:
        snapshot = {
            symbol: list(candles.values())
            for symbol, candles in received_candles.items()
        }

    total = sum(len(items) for items in snapshot.values())
    logging.info(
        "Received %s closed %s candles across %s markets.",
        total,
        TIMEFRAME,
        len(snapshot),
    )

    if total == 0:
        raise RuntimeError(
            "WebSocket connected but no closed 15m candles were received. "
            "Check the subscription protocol and Bitpin response."
        )

    return snapshot


# ============================================================
# HISTORY UPDATE
# ============================================================

def update_history(history, new_candles):
    if not isinstance(history, dict):
        history = {"markets": {}}

    markets = history.setdefault("markets", {})

    for symbol, candles in new_candles.items():
        old = markets.setdefault(symbol, [])

        by_timestamp = {}

        if isinstance(old, list):
            for candle in old:
                if not isinstance(candle, dict):
                    continue

                ts = int(safe_float(candle.get("ts"), -1))

                if ts > 0:
                    by_timestamp[ts] = candle

        for candle in candles:
            by_timestamp[int(candle["ts"])] = candle

        sorted_candles = [
            by_timestamp[ts]
            for ts in sorted(by_timestamp)
        ]

        markets[symbol] = sorted_candles[-MAX_HISTORY_CANDLES:]

    history["updated_at"] = utc_now().isoformat()
    return history


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if not values:
        return 0.0

    alpha = 2.0 / (period + 1.0)
    result = float(values[0])

    for value in values[1:]:
        result = alpha * float(value) + (1.0 - alpha) * result

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for index in range(1, len(values)):
        difference = values[index] - values[index - 1]
        gains.append(max(difference, 0.0))
        losses.append(max(-difference, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for index in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[index]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[index]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ============================================================
# SIGNAL ANALYSIS
# ============================================================

def analyze_market(symbol, candles):
    now_ts = int(time.time())

    valid = [
        candle for candle in candles
        if isinstance(candle, dict)
        and int(safe_float(candle.get("ts"), -1)) > 0
        and safe_float(candle.get("close")) > 0
        and int(safe_float(candle.get("ts"))) + CANDLE_SECONDS <= now_ts
    ]

    valid.sort(key=lambda candle: int(candle["ts"]))

    # Keep the most recent copy of each candle.
    unique = {}
    for candle in valid:
        unique[int(candle["ts"])] = candle

    candles = [unique[ts] for ts in sorted(unique)]

    # The last candle must be recent enough to be useful.
    if candles:
        age_minutes = (now_ts - int(candles[-1]["ts"])) / 60.0

        if age_minutes > MAX_MARKET_AGE_MINUTES + 15:
            return {
                "status": "WAIT",
                "reason": "آخرین کندل بیش از حد قدیمی است",
            }

    if len(candles) < MIN_CANDLES:
        return {
            "status": "WAIT",
            "reason": (
                f"تاریخچه ناکافی؛ {MIN_CANDLES} کندل بسته‌شده لازم است "
                f"(فعلی: {len(candles)})"
            ),
        }

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    volumes = [max(0.0, float(c.get("volume", 0))) for c in candles]

    last = candles[-1]
    previous = candles[-2]

    close = closes[-1]
    open_price = float(last["open"])
    low = float(last["low"])
    high = float(last["high"])

    ema9 = ema(closes[-20:], 9)
    ema20 = ema(closes[-20:], 20)
    prior_ema20 = ema(closes[-21:-1], 20)
    current_rsi = rsi(closes, 14)

    if current_rsi is None:
        return {
            "status": "WAIT",
            "reason": "داده کافی برای RSI وجود ندارد",
        }

    # Support is calculated from prior candles, excluding the current one.
    support_window = lows[-21:-1]
    support = min(support_window)

    if support <= 0:
        return {
            "status": "WAIT",
            "reason": "محاسبه حمایت معتبر نیست",
        }

    support_distance_pct = (close - support) / support * 100.0

    average_volume = (
        sum(volumes[-21:-1]) / max(1, len(volumes[-21:-1]))
    )
    current_volume = volumes[-1]

    bullish_candle = close > open_price
    trend_ok = close > ema9 and ema20 >= prior_ema20
    rsi_ok = 45 <= current_rsi <= 68
    near_support = 0 <= support_distance_pct <= 1.8

    volume_ok = (
        average_volume <= 0
        or current_volume >= average_volume * 0.8
    )

    # Reject a candle that is too extended above the support zone.
    not_overextended = close <= ema9 * 1.025

    score = 0
    if bullish_candle:
        score += 20
    if trend_ok:
        score += 25
    if rsi_ok:
        score += 20
    if near_support:
        score += 20
    if volume_ok:
        score += 10
    if not_overextended:
        score += 5

    checks_passed = all([
        bullish_candle,
        trend_ok,
        rsi_ok,
        near_support,
        volume_ok,
        not_overextended,
    ])

    if checks_passed and score >= 85:
        # Paper spot entry only; no real order is ever sent.
        entry = close
        stop = min(support * 0.99, low * 0.995)

        if stop <= 0 or stop >= entry:
            return {
                "status": "WAIT",
                "reason": "حد ضرر قابل‌محاسبه نیست",
            }

        risk = entry - stop
        tp1 = entry + risk * 1.5
        tp2 = entry + risk * 2.0
        tp3 = entry + risk * 3.0

        return {
            "status": "BUY",
            "symbol": symbol,
            "score": score,
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rsi": current_rsi,
            "support": support,
            "support_distance_pct": support_distance_pct,
            "candle_ts": int(last["ts"]),
        }

    if near_support and bullish_candle:
        return {
            "status": "WATCH",
            "score": score,
            "reason": "نزدیک حمایت و کندل صعودی؛ تأیید کامل نشده",
        }

    reasons = []

    if not near_support:
        reasons.append("فاصله از حمایت")
    if not bullish_candle:
        reasons.append("کندل صعودی تأیید نشده")
    if not trend_ok:
        reasons.append("روند EMA تأیید نشده")
    if not rsi_ok:
        reasons.append("RSI خارج از محدوده")
    if not volume_ok:
        reasons.append("حجم ضعیف")
    if not not_overextended:
        reasons.append("قیمت بیش از حد از EMA فاصله دارد")

    return {
        "status": "WAIT",
        "score": score,
        "reason": "، ".join(reasons) or "شرایط خرید کامل نیست",
    }


# ============================================================
# REPORT
# ============================================================

def fmt_price(value):
    value = safe_float(value)

    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}"
    return f"{value:.8f}"


def build_report(symbols, history, persistence_ok, duration):
    markets = history.get("markets", {})
    buys = []
    watches = 0
    waits = 0
    reasons = {}
    analysis_errors = 0

    for symbol in symbols:
        try:
            result = analyze_market(
                symbol,
                markets.get(symbol, []),
            )

            status = result.get("status", "WAIT")

            if status == "BUY":
                buys.append(result)
            elif status == "WATCH":
                watches += 1
            else:
                waits += 1
                reason = result.get("reason", "نامشخص")
                reasons[reason] = reasons.get(reason, 0) + 1

        except Exception as exc:
            analysis_errors += 1
            waits += 1
            reason = "خطای تحلیل"
            reasons[reason] = reasons.get(reason, 0) + 1
            logging.exception("Analysis failed for %s: %s", symbol, exc)

    buys.sort(key=lambda item: item.get("score", 0), reverse=True)
    buys = buys[:MAX_SIGNALS]

    # The simulated capital is divided among available signal slots.
    per_signal_budget = CAPITAL_USDT / MAX_SIGNALS

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش اسکن بازار بیت‌پین",
        "🕒 " + utc_text(),
        "━━━━━━━━━━━━━━━━━━",
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT",
        "📦 بودجه فرضی هر سیگنال: "
        f"{per_signal_budget:.2f} USDT",
        f"📈 بازارهای بررسی‌شده: {len(symbols)}",
        f"🟢 خریدهای تأییدشده: {len(buys)}",
        f"🟡 موارد تحت نظر: {watches}",
        f"⚪ موارد انتظار: {waits}",
        f"⚠️ خطاهای تحلیل: {analysis_errors}",
        "💾 ذخیره تاریخچه: "
        + ("موفق" if persistence_ok else "ناموفق/فقط محلی"),
        f"⏱ زمان اجرا: {duration:.1f} ثانیه",
        "🧪 فقط سیگنال آزمایشی اسپات",
        "🚫 سفارش واقعی: خاموش",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if buys:
        lines.append("🟢 سیگنال‌های خرید آزمایشی")

        for index, item in enumerate(buys, start=1):
            lines.extend([
                "",
                f"{index}. {item['symbol']} | امتیاز {item['score']}/100",
                f"🟢 Entry: {fmt_price(item['entry'])}",
                f"🛑 SL: {fmt_price(item['stop'])}",
                f"🎯 TP1: {fmt_price(item['tp1'])}",
                f"🎯 TP2: {fmt_price(item['tp2'])}",
                f"🎯 TP3: {fmt_price(item['tp3'])}",
                f"📊 RSI: {item['rsi']:.1f}",
                f"📍 حمایت: {fmt_price(item['support'])}",
                "📌 فاصله از حمایت: "
                f"{item['support_distance_pct']:.2f}%",
                f"💵 بودجه فرضی: {per_signal_budget:.2f} USDT",
            ])

    else:
        lines.append("⚪ فعلاً سیگنال خرید تأییدشده‌ای وجود ندارد.")

    if reasons:
        lines.extend(["", "📌 دلایل پرتکرار انتظار:"])

        for reason, count in sorted(
            reasons.items(),
            key=lambda pair: pair[1],
            reverse=True,
        )[:5]:
            lines.append(f"• {reason}: {count}")

    lines.extend([
        "",
        "⚠️ سوددهی یا نرخ برد تضمین‌شده نیست.",
        "این ربات سفارش ثبت نمی‌کند.",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    started = time.time()

    if not PAPER_MODE or REAL_ORDERS_ENABLED:
        raise RuntimeError(
            "Safety check failed: paper mode must be enabled "
            "and real orders must remain disabled."
        )

    telegram_send(
        BOT_NAME
        + "\n✅ نسخه WebSocket Paper Bot شروع شد."
        + f"\n💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT"
        + "\n📊 تایم‌فریم: 15m"
        + "\n🧪 فقط سیگنال اسپات آزمایشی"
        + "\n🚫 سفارش واقعی خاموش"
    )

    try:
        symbols = get_markets()
        history = load_history()

        new_candles = collect_candles(symbols)
        history = update_history(history, new_candles)

        persistence_ok = save_history(history)

        report = build_report(
            symbols,
            history,
            persistence_ok,
            time.time() - started,
        )

        print(report)
        telegram_send(report)

    except Exception as exc:
        logging.exception("Scan failed: %s", exc)

        error_report = (
            BOT_NAME
            + "\n━━━━━━━━━━━━━━━━━━"
            + "\n❌ اسکن کامل نشد"
            + "\nعلت: " + str(exc)[:700]
            + "\n🧪 حالت آزمایشی فعال است."
            + "\n🚫 هیچ سفارش واقعی ثبت نشده است."
        )

        print(error_report)
        telegram_send(error_report)
        sys.exit(1)


if __name__ == "__main__":
    main()
