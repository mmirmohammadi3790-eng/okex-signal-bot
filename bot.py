
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
# ETH WHALE | BITPIN SOLANA LONG/SHORT PAPER SIGNAL BOT
# ONLY SOL/USDT | 15m | NO REAL ORDERS | NO LEVERAGE
# ============================================================

BOT_NAME = "🐋 ETH WHALE | SOLANA"
BASE_URL = "https://api.bitpin.org"
WS_URL = "wss://centrifugo.bitpin.org/connection/websocket"
MARKETS_URL = BASE_URL + "/v1/mkt/markets/"
HISTORY_FILE = "data/market_history.json"

CAPITAL_USDT = 48.0
SYMBOL = "SOL_USDT"

TIMEFRAME = "15m"
CANDLE_SECONDS = 900
MIN_CANDLES = 21
MAX_HISTORY_CANDLES = 250

# Support/resistance tolerance
LEVEL_TOLERANCE_PCT = 0.004  # 0.4%

# Paper-only safety
PAPER_MODE = True
REAL_ORDERS_ENABLED = False

WS_LISTEN_SECONDS = 25
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME", "main").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

session = requests.Session()
session.headers.update({
    "User-Agent": "ETH-WHALE-SOL-Paper-Bot/11.0",
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

    return (
        str(value).strip().upper()
        .replace("-", "_")
        .replace("/", "_")
    )


def fmt_price(value):
    value = safe_float(value)

    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.5f}"
    return f"{value:.8f}"


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
            "Telegram HTTP %s: %s",
            response.status_code,
            response.text[:300],
        )

    except requests.RequestException as exc:
        logging.error("Telegram error: %s", exc)

    return False


# ============================================================
# MARKET CHECK: SOL/USDT ONLY
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

            for market in markets:
                if not isinstance(market, dict):
                    continue

                candidates = [
                    market.get("symbol"),
                    market.get("code"),
                    market.get("market"),
                    market.get("name"),
                    market.get("ticker"),
                ]

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
                    candidates.append(f"{base}_{quote}")

                for candidate in candidates:
                    if normalize_symbol(candidate) != SYMBOL:
                        continue

                    if market.get("tradable") is False:
                        continue

                    logging.info("SOL/USDT market found.")
                    return [SYMBOL]

            raise RuntimeError(
                "SOL_USDT was not found in the returned market list. "
                "Check Bitpin's actual market symbol format."
            )

        except Exception as exc:
            last_error = exc
            logging.warning(
                "Market check %s/%s failed: %s",
                attempt,
                MAX_RETRIES,
                exc,
            )

            if attempt < MAX_RETRIES:
                time.sleep(attempt * 2)

    raise RuntimeError(
        "Could not verify SOL/USDT market: " + str(last_error)
    )


# ============================================================
# GITHUB HISTORY
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
                    data.setdefault("markets", {})
                    logging.info("History loaded from GitHub.")
                    return data

            elif response.status_code != 404:
                logging.warning(
                    "GitHub read HTTP %s",
                    response.status_code,
                )

        except Exception as exc:
            logging.warning("GitHub history read failed: %s", exc)

    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)

            if isinstance(data, dict):
                data.setdefault("markets", {})
                return data

    except Exception as exc:
        logging.warning("Local history read failed: %s", exc)

    return {"markets": {}, "last_signal": {}}


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
        logging.warning("History saved locally only.")
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
                "message": "Update SOL paper signal history",
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
                "GitHub save HTTP %s: %s",
                response.status_code,
                response.text[:250],
            )

        except Exception as exc:
            logging.warning("GitHub save failed: %s", exc)

        if attempt < MAX_RETRIES:
            time.sleep(attempt * 2)

    return False


# ============================================================
# WEBSOCKET CANDLE COLLECTION
# Uses the channel protocol from the supplied bot.
# The channel and payload must match Bitpin's live response.
# ============================================================

def process_ws_message(ws, raw_message):
    global ws_connected, ws_error

    try:
        message = json.loads(raw_message)
    except (json.JSONDecodeError, TypeError):
        return

    if isinstance(message, dict) and "connect" in message:
        if message.get("error"):
            ws_error = str(message["error"])
            ws_ready.set()
            return

        ws_connected = True
        logging.info("WebSocket connected.")

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
                    "Subscription failed for %s: %s",
                    symbol,
                    exc,
                )

        ws_ready.set()
        return

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
        data.get("symbol") or str(channel).replace("market:", "")
    )

    if symbol != SYMBOL:
        return

    candles = data.get("candles", [])
    if not isinstance(candles, list):
        return

    now_ts = int(time.time())

    with state_lock:
        bucket = received_candles.setdefault(SYMBOL, {})

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            if candle.get("resolution") != TIMEFRAME:
                continue

            timestamp = int(safe_float(candle.get("ts"), -1))

            if timestamp <= 0:
                continue

            # Only closed candles are accepted.
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

            if min(
                normalized["open"],
                normalized["high"],
                normalized["low"],
                normalized["close"],
            ) <= 0:
                continue

            if normalized["high"] < normalized["low"]:
                continue

            bucket[timestamp] = normalized


def on_ws_open(ws):
    logging.info("WebSocket transport opened.")

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
    logging.info("WebSocket closed: %s %s", status_code, message)


def collect_candles(symbols):
    global received_candles, subscribed_symbols
    global ws_connected, ws_error

    with state_lock:
        received_candles = {}
        subscribed_symbols = [SYMBOL]

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

    ws_ready.wait(timeout=12)

    if not ws_connected:
        app.close()
        raise RuntimeError(
            "Bitpin WebSocket connection was not confirmed: "
            + str(ws_error or "no response")
        )

    time.sleep(WS_LISTEN_SECONDS)
    app.close()
    thread.join(timeout=3)

    with state_lock:
        snapshot = {
            symbol: list(candles.values())
            for symbol, candles in received_candles.items()
        }

    count = sum(len(items) for items in snapshot.values())
    logging.info("Received %s closed SOL 15m candles.", count)

    if count == 0:
        raise RuntimeError(
            "Connected, but no closed SOL 15m candles arrived. "
            "The Bitpin channel or payload may differ from this code."
        )

    return snapshot


# ============================================================
# HISTORY UPDATE
# ============================================================

def update_history(history, new_candles):
    history.setdefault("markets", {})
    history.setdefault("last_signal", {})

    markets = history["markets"]

    for symbol, candles in new_candles.items():
        if symbol != SYMBOL:
            continue

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

        markets[symbol] = [
            by_timestamp[ts]
            for ts in sorted(by_timestamp)
        ][-MAX_HISTORY_CANDLES:]

    history["updated_at"] = utc_now().isoformat()
    return history


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    alpha = 2.0 / (period + 1.0)
    result = float(values[0])

    for value in values[1:]:
        result = alpha * float(value) + (1 - alpha) * result

    return result


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
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ============================================================
# SUPPORT / RESISTANCE + CLOSED-CANDLE CONFIRMATION
# ============================================================

def analyze_market(symbol, candles):
    now_ts = int(time.time())

    if symbol != SYMBOL:
        return {"status": "WAIT", "reason": "Only SOL/USDT is enabled"}

    valid = []

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        ts = int(safe_float(candle.get("ts"), -1))

        if ts <= 0 or ts + CANDLE_SECONDS > now_ts:
            continue

        try:
            normalized = {
                "ts": ts,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": max(0.0, float(candle.get("volume", 0))),
            }
        except (KeyError, TypeError, ValueError):
            continue

        if min(
            normalized["open"],
            normalized["high"],
            normalized["low"],
            normalized["close"],
        ) <= 0:
            continue

        valid.append(normalized)

    unique = {c["ts"]: c for c in valid}
    candles = [unique[ts] for ts in sorted(unique)]

    if candles:
        age_minutes = (now_ts - candles[-1]["ts"]) / 60.0

        if age_minutes > 30:
            return {
                "status": "WAIT",
                "reason": "آخرین کندل SOL قدیمی است",
            }

    if len(candles) < MIN_CANDLES:
        return {
            "status": "WAIT",
            "reason": (
                f"تاریخچه ناکافی؛ حداقل {MIN_CANDLES} کندل بسته‌شده لازم است "
                f"(فعلی: {len(candles)})"
            ),
        }

    # Use previous 20 candles to define levels.
    # Current candle is excluded from level calculations.
    prior = candles[-21:-1]
    last = candles[-1]
    previous = candles[-2]

    support = min(c["low"] for c in prior)
    resistance = max(c["high"] for c in prior)

    if support <= 0 or resistance <= support:
        return {
            "status": "WAIT",
            "reason": "حمایت و مقاومت قابل‌اعتماد محاسبه نشد",
        }

    closes = [c["close"] for c in candles]
    current_rsi = rsi(closes, 14)
    ema9 = ema(closes[-30:], 9)
    ema20 = ema(closes[-40:], 20)

    if current_rsi is None or ema9 is None or ema20 is None:
        return {
            "status": "WAIT",
            "reason": "داده کافی برای اندیکاتورها وجود ندارد",
        }

    entry = last["close"]
    candle_range = max(last["high"] - last["low"], entry * 0.0005)
    tolerance_support = support * LEVEL_TOLERANCE_PCT
    tolerance_resistance = resistance * LEVEL_TOLERANCE_PCT

    bullish = last["close"] > last["open"]
    bearish = last["close"] < last["open"]

    # Confirmation requires the candle to test a level and close
    # back away from it. This is not an intrabar signal.
    tested_support = last["low"] <= support + tolerance_support
    rejected_support = (
        bullish
        and last["close"] > support
        and last["close"] > previous["close"]
    )

    tested_resistance = last["high"] >= resistance - tolerance_resistance
    rejected_resistance = (
        bearish
        and last["close"] < resistance
        and last["close"] < previous["close"]
    )

    average_volume = sum(c["volume"] for c in prior) / len(prior)
    volume_ok = (
        average_volume <= 0
        or last["volume"] >= average_volume * 0.70
    )

    # LONG: confirmed bounce from support.
    long_trend_ok = entry >= ema20 and current_rsi < 70

    if (
        tested_support
        and rejected_support
        and long_trend_ok
        and volume_ok
    ):
        stop = min(
            last["low"] - candle_range * 0.15,
            support - candle_range * 0.10,
        )

        risk = entry - stop

        if risk > 0:
            return {
                "status": "LONG",
                "symbol": SYMBOL,
                "entry": entry,
                "stop": stop,
                "tp1": entry + risk * 1.5,
                "tp2": entry + risk * 2.0,
                "tp3": entry + risk * 3.0,
                "rsi": current_rsi,
                "support": support,
                "resistance": resistance,
                "candle_ts": last["ts"],
                "reason": "حمایت لمس شد و کندل صعودی تأیید بسته شد",
            }

    # SHORT: confirmed rejection from resistance.
    short_trend_ok = entry <= ema20 and current_rsi > 30

    if (
        tested_resistance
        and rejected_resistance
        and short_trend_ok
        and volume_ok
    ):
        stop = max(
            last["high"] + candle_range * 0.15,
            resistance + candle_range * 0.10,
        )

        risk = stop - entry

        if risk > 0:
            return {
                "status": "SHORT",
                "symbol": SYMBOL,
                "entry": entry,
                "stop": stop,
                "tp1": entry - risk * 1.5,
                "tp2": entry - risk * 2.0,
                "tp3": entry - risk * 3.0,
                "rsi": current_rsi,
                "support": support,
                "resistance": resistance,
                "candle_ts": last["ts"],
                "reason": "مقاومت لمس شد و کندل نزولی تأیید بسته شد",
            }

    reasons = []

    if not tested_support and not tested_resistance:
        reasons.append("قیمت به حمایت یا مقاومت مهم نرسیده")
    if tested_support and not rejected_support:
        reasons.append("تأیید صعودی حمایت کامل نیست")
    if tested_resistance and not rejected_resistance:
        reasons.append("تأیید نزولی مقاومت کامل نیست")
    if not volume_ok:
        reasons.append("حجم کندل تأیید ضعیف است")
    if not long_trend_ok and not short_trend_ok:
        reasons.append("روند EMA یا RSI مناسب نیست")

    return {
        "status": "WAIT",
        "symbol": SYMBOL,
        "support": support,
        "resistance": resistance,
        "rsi": current_rsi,
        "candle_ts": last["ts"],
        "reason": "؛ ".join(reasons) or "شرایط ورود کامل نیست",
    }


# ============================================================
# REPORT + DUPLICATE SIGNAL PROTECTION
# ============================================================

def build_report(history, persistence_ok, duration):
    candles = history.get("markets", {}).get(SYMBOL, [])
    result = analyze_market(SYMBOL, candles)

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 تحلیل اختصاصی SOL/USDT | بیت‌پین",
        "🕒 " + utc_text(),
        "⏱ تایم‌فریم: 15 دقیقه",
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT",
        "🧪 PAPER ONLY",
        "🚫 سفارش واقعی: خاموش",
        "⚙️ اهرم: ندارد",
        "━━━━━━━━━━━━━━━━━━",
    ]

    status = result.get("status", "WAIT")

    if status in ("LONG", "SHORT"):
        candle_ts = str(result["candle_ts"])
        last_signal = history.setdefault("last_signal", {})

        if last_signal.get(SYMBOL) == candle_ts:
            status = "WAIT"
            result = {
                **result,
                "reason": "برای این کندل قبلاً سیگنال ارسال شده است",
            }
        else:
            # Record the candle to avoid duplicate alerts on repeated runs.
            last_signal[SYMBOL] = candle_ts

    if status in ("LONG", "SHORT"):
        label = "🟢 LONG" if status == "LONG" else "🔴 SHORT"

        lines.extend([
            f"📣 سیگنال تأییدشده: {label}",
            f"📍 ورود فرضی: {fmt_price(result['entry'])}",
            f"🛑 حد ضرر: {fmt_price(result['stop'])}",
            f"🎯 TP1: {fmt_price(result['tp1'])}",
            f"🎯 TP2: {fmt_price(result['tp2'])}",
            f"🎯 TP3: {fmt_price(result['tp3'])}",
            f"🧱 حمایت: {fmt_price(result['support'])}",
            f"🧱 مقاومت: {fmt_price(result['resistance'])}",
            f"📊 RSI: {result['rsi']:.1f}",
            "✅ " + result["reason"],
            "━━━━━━━━━━━━━━━━━━",
            "این سیگنال آزمایشی است؛ سفارش ثبت نشده است.",
        ])

    else:
        lines.extend([
            "⚪ وضعیت: WAIT",
            f"🧱 حمایت مهم: {fmt_price(result.get('support', 0))}",
            f"🧱 مقاومت مهم: {fmt_price(result.get('resistance', 0))}",
            (
                f"📊 RSI: {result['rsi']:.1f}"
                if result.get("rsi") is not None
                else "📊 RSI: داده کافی نیست"
            ),
            "📌 دلیل: " + result.get("reason", "سیگنال تأیید نشد"),
            "⛔ بدون کندل تأیید، ورود نداریم.",
        ])

    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        "💾 ذخیره تاریخچه: "
        + ("موفق" if persistence_ok else "ناموفق/فقط محلی"),
        f"⏱ زمان اجرا: {duration:.1f} ثانیه",
        "⚠️ نرخ برد یا سود تضمین‌شده نیست.",
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
        + "\n✅ ربات سیگنال سولانا شروع شد."
        + "\n📊 فقط SOL/USDT"
        + "\n⏱ تایم‌فریم 15m"
        + "\n🟢 LONG و 🔴 SHORT پس از کندل تأیید"
        + "\n🧪 فقط PAPER"
        + "\n🚫 سفارش واقعی خاموش"
    )

    try:
        symbols = get_markets()
        history = load_history()

        new_candles = collect_candles(symbols)
        history = update_history(history, new_candles)

        candles = history.get("markets", {}).get(SYMBOL, [])
        logging.info(
            "Stored closed SOL candles: %s",
            len(candles),
        )

        # Never generate a signal from insufficient candle history.
        if len(candles) < MIN_CANDLES:
            persistence_ok = save_history(history)

            report = (
                BOT_NAME
                + "\n━━━━━━━━━━━━━━━━━━"
                + "\n⚪ وضعیت: WAIT"
                + "\n📊 بازار: SOL/USDT"
                + f"\n🕯️ کندل‌های بسته‌شده موجود: {len(candles)}"
                + f"\n🕯️ حداقل موردنیاز: {MIN_CANDLES}"
                + "\nعلت: تاریخچه کافی نیست."
                + "\nربات برای جلوگیری از سیگنال اشتباه ورود نمی‌دهد."
                + "\n💾 ذخیره تاریخچه: "
                + ("موفق" if persistence_ok else "ناموفق/فقط محلی")
                + "\n🚫 سفارش واقعی ثبت نشده است."
            )
        else:
            # Save state before sending the report, including signal dedupe.
            report = build_report(
                history,
                False,
                time.time() - started,
            )
            persistence_ok = save_history(history)

            # Rebuild report only if needed would risk changing signal state;
            # append persistence status is already reported as pending above.
            report = report.replace(
                "ناموفق/فقط محلی",
                "موفق" if persistence_ok else "ناموفق/فقط محلی",
            )

        print(report)
        telegram_send(report)

    except Exception as exc:
        logging.exception("Scan failed: %s", exc)

        error_report = (
            BOT_NAME
            + "\n━━━━━━━━━━━━━━━━━━"
            + "\n❌ اسکن کامل نشد"
            + "\nعلت: " + str(exc)[:600]
            + "\n🧪 حالت آزمایشی فعال است."
            + "\n🚫 هیچ سفارش واقعی ثبت نشده است."
        )

        print(error_report)
        telegram_send(error_report)
        sys.exit(1)


if __name__ == "__main__":
    main()
