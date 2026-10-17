
import os
import json
import time
import base64
import logging
import random
import requests

from datetime import datetime, timezone
from urllib.parse import quote

# ============================================================
# ETH WHALE | BITPIN SPOT PAPER SIGNALS
# NO REAL ORDERS - NO FUTURES - NO LEVERAGE
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
BASE_URL = "https://api.bitpin.ir"
GITHUB_API = "https://api.github.com"

MARKETS_URL = f"{BASE_URL}/v1/mkt/markets/"
TRADES_URL = f"{BASE_URL}/api/v1/mth/matches/"

CAPITAL_USDT = 48.0
MAX_MARKETS = 25
MAX_SIGNALS = 3

CANDLE_MINUTES = 15
CANDLE_SECONDS = CANDLE_MINUTES * 60
MIN_CLOSED_CANDLES = 21
MAX_CANDLE_HISTORY = 300
MAX_SEEN_TRADE_IDS = 5000

SUPPORT_ZONE_PERCENT = 0.012
MAX_STOP_PERCENT = 0.045
MAX_TRADE_AGE_MINUTES = 30

# Rate-limit controls
REQUEST_DELAY_SECONDS = 1.5
MAX_RETRIES_429 = 3
RETRY_BASE_SECONDS = 5
REQUEST_TIMEOUT = 20

STATE_PATH = "data/market_history.json"

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or ""
).strip()

CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
    or ""
).strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
GITHUB_BRANCH = os.getenv("GITHUB_REF_NAME", "main")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Paper-Bot/8.0",
    "Accept": "application/json"
})


# ============================================================
# HELPERS
# ============================================================

def number(value, default=0.0):
    try:
        result = float(value)
        if result != result or abs(result) == float("inf"):
            return default
        return result
    except (TypeError, ValueError, OverflowError):
        return default


def utc_text(timestamp=None):
    if timestamp is None:
        timestamp = time.time()

    return datetime.fromtimestamp(
        timestamp, timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_timestamp(value):
    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 100000000000:
            stamp /= 1000.0
        return stamp if stamp > 0 else 0.0

    if isinstance(value, str):
        text = value.strip()

        try:
            stamp = float(text)
            if stamp > 100000000000:
                stamp /= 1000.0
            return stamp if stamp > 0 else 0.0
        except ValueError:
            pass

        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"

            dt = datetime.fromisoformat(text)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt.timestamp()
        except (ValueError, OverflowError):
            return 0.0

    return 0.0


def api_get(url, params=None, timeout=REQUEST_TIMEOUT):
    """GET with bounded retries for HTTP 429 and transient server errors."""
    for attempt in range(MAX_RETRIES_429 + 1):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=timeout
            )

            if response.status_code == 429 or response.status_code in (
                500, 502, 503, 504
            ):
                if attempt >= MAX_RETRIES_429:
                    response.raise_for_status()

                retry_after = number(
                    response.headers.get("Retry-After"), 0
                )

                delay = max(
                    retry_after,
                    RETRY_BASE_SECONDS * (2 ** attempt)
                )
                delay += random.uniform(0.5, 2.0)

                logging.warning(
                    "HTTP %s; retry %s/%s in %.1fs",
                    response.status_code,
                    attempt + 1,
                    MAX_RETRIES_429,
                    delay
                )

                time.sleep(delay)
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException:
            if attempt >= MAX_RETRIES_429:
                raise

            delay = RETRY_BASE_SECONDS * (2 ** attempt)
            delay += random.uniform(0.5, 2.0)

            logging.warning(
                "Request failed; retry %s/%s in %.1fs",
                attempt + 1,
                MAX_RETRIES_429,
                delay
            )
            time.sleep(delay)

    raise RuntimeError("Request retries exhausted.")


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Telegram credentials are missing.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        response = SESSION.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True
            },
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        return bool(response.json().get("ok"))

    except Exception as exc:
        logging.error("Telegram send failed: %s", exc)
        return False


def fmt_price(value):
    value = number(value)

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    return f"{value:.8f}".rstrip("0").rstrip(".")


# ============================================================
# GITHUB HISTORY
# ============================================================

def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }


def load_state():
    empty = {"markets": {}}

    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logging.warning("GitHub persistence is not configured.")
        return empty, None

    url = (
        f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}"
        f"/contents/{STATE_PATH}"
    )

    try:
        response = SESSION.get(
            url,
            headers=github_headers(),
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 404:
            return empty, None

        response.raise_for_status()
        payload = response.json()

        raw = base64.b64decode(
            payload.get("content", "")
        ).decode("utf-8")

        state = json.loads(raw)

        if not isinstance(state, dict):
            state = empty

        if not isinstance(state.get("markets"), dict):
            state["markets"] = {}

        logging.info("Saved history loaded from GitHub.")
        return state, payload.get("sha")

    except Exception as exc:
        logging.error("Could not load saved history: %s", exc)
        return empty, None


def save_state(state, sha):
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logging.warning("History was not saved permanently.")
        return False

    url = (
        f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}"
        f"/contents/{STATE_PATH}"
    )

    raw = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":")
    ).encode("utf-8")

    if len(raw) > 850000:
        logging.error("History file too large; save cancelled.")
        return False

    payload = {
        "message": "Update ETH WHALE market history",
        "content": base64.b64encode(raw).decode("ascii"),
        "branch": GITHUB_BRANCH
    }

    if sha:
        payload["sha"] = sha

    try:
        response = SESSION.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code not in (200, 201):
            logging.error(
                "History save failed: HTTP %s %s",
                response.status_code,
                response.text[:300]
            )
            return False

        logging.info("Market history saved to GitHub.")
        return True

    except Exception as exc:
        logging.error("Could not save history: %s", exc)
        return False


# ============================================================
# MARKET LIST
# ============================================================

def get_symbol(market):
    for key in ("symbol", "code", "market", "name"):
        value = market.get(key)

        if isinstance(value, str):
            value = value.upper().replace("-", "_").strip()

            if value.endswith("_USDT"):
                return value

    base = market.get("base_currency") or market.get("base")
    quote_currency = (
        market.get("quote_currency")
        or market.get("quote")
    )

    if isinstance(base, dict):
        base = base.get("code") or base.get("symbol")

    if isinstance(quote_currency, dict):
        quote_currency = (
            quote_currency.get("code")
            or quote_currency.get("symbol")
        )

    if base and str(quote_currency).upper() == "USDT":
        return str(base).upper() + "_USDT"

    return ""


def get_volume(market):
    keys = (
        "quote_volume", "quoteVolume", "volume_24h",
        "volume24h", "volume", "turnover"
    )

    for key in keys:
        value = number(market.get(key))
        if value > 0:
            return value

    info = market.get("price_info")

    if isinstance(info, dict):
        for key in keys:
            value = number(info.get(key))
            if value > 0:
                return value

    return 0.0


def fetch_markets():
    payload = api_get(MARKETS_URL)

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("results", [])
    else:
        rows = []

    if not isinstance(rows, list):
        raise RuntimeError("Unexpected Bitpin markets response.")

    found = {}

    for market in rows:
        if not isinstance(market, dict):
            continue

        symbol = get_symbol(market)

        if not symbol:
            continue

        base = symbol[:-5]

        # These markets returned HTTP 406 in previous runs.
        if base in {"BUSD", "DAI", "PERP", "RDNT"}:
            continue

        market["_bot_symbol"] = symbol
        market["_bot_volume"] = get_volume(market)
        found[symbol] = market

    markets = list(found.values())

    # Prioritize volume only where the API provides a value.
    markets.sort(
        key=lambda item: item.get("_bot_volume", 0),
        reverse=True
    )

    selected = markets[:MAX_MARKETS]

    if not selected:
        raise RuntimeError("No eligible USDT markets found.")

    logging.info(
        "USDT markets found: %s | selected: %s",
        len(markets), len(selected)
    )

    return selected


# ============================================================
# RECENT TRADES
# ============================================================

def fetch_trades(symbol):
    url = f"{TRADES_URL}{quote(symbol, safe='_')}/"

    try:
        payload = api_get(url)

    except requests.HTTPError as exc:
        response = exc.response

        if response is not None and response.status_code in (
            400, 404, 406
        ):
            logging.warning(
                "Skipping unsupported market %s (HTTP %s)",
                symbol,
                response.status_code
            )
            return []

        raise

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("results")
            or payload.get("trades")
            or payload.get("data")
            or []
        )
    else:
        rows = []

    if not isinstance(rows, list):
        return []

    valid = []

    for trade in rows:
        if not isinstance(trade, dict):
            continue

        price = number(trade.get("price"))

        stamp = parse_timestamp(
            trade.get("time")
            or trade.get("timestamp")
            or trade.get("created_at")
        )

        if price <= 0 or stamp <= 0:
            continue

        trade_id = trade.get("id")

        if trade_id is None:
            trade_id = (
                f"{int(stamp * 1000)}:{price}:"
                f"{trade.get('base_amount', '')}:"
                f"{trade.get('side', '')}"
            )

        base_amount = number(trade.get("base_amount"))
        quote_amount = number(
            trade.get("quote_amount"),
            price * base_amount
        )

        valid.append({
            "id": str(trade_id),
            "time": stamp,
            "price": price,
            "quote_amount": quote_amount
        })

    valid.sort(key=lambda item: item["time"])
    return valid


# ============================================================
# CANDLE HISTORY
# ============================================================

def empty_market_state():
    return {"candles": [], "seen_ids": []}


def update_market_history(old_state, trades, now_ts):
    if not isinstance(old_state, dict):
        old_state = empty_market_state()

    candles = old_state.get("candles", [])
    seen_ids = old_state.get("seen_ids", [])

    if not isinstance(candles, list):
        candles = []

    if not isinstance(seen_ids, list):
        seen_ids = []

    seen = set(str(value) for value in seen_ids)
    candle_map = {}

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        bucket = int(number(candle.get("t"), -1))

        if bucket >= 0:
            candle_map[bucket] = candle

    for trade in trades:
        trade_id = str(trade["id"])

        if trade_id in seen:
            continue

        seen.add(trade_id)

        stamp = trade["time"]
        price = trade["price"]
        bucket = int(stamp // CANDLE_SECONDS) * CANDLE_SECONDS

        candle = candle_map.get(bucket)

        if candle is None:
            candle = {
                "t": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "first_time": stamp,
                "last_time": stamp,
                "trades": 0,
                "volume": 0.0
            }
            candle_map[bucket] = candle

        candle["high"] = max(
            number(candle.get("high"), price), price
        )
        candle["low"] = min(
            number(candle.get("low"), price), price
        )

        if stamp < number(candle.get("first_time"), stamp):
            candle["first_time"] = stamp
            candle["open"] = price

        if stamp >= number(candle.get("last_time"), stamp):
            candle["last_time"] = stamp
            candle["close"] = price

        candle["trades"] = int(
            number(candle.get("trades"), 0)
        ) + 1

        candle["volume"] = (
            number(candle.get("volume"), 0)
            + number(trade.get("quote_amount"), 0)
        )

    cutoff = now_ts - MAX_CANDLE_HISTORY * CANDLE_SECONDS

    candle_list = [
        candle for bucket, candle in candle_map.items()
        if bucket >= cutoff
    ]

    candle_list.sort(key=lambda item: item["t"])

    seen_list = list(seen)

    if len(seen_list) > MAX_SEEN_TRADE_IDS:
        seen_list = seen_list[-MAX_SEEN_TRADE_IDS:]

    return {
        "candles": candle_list,
        "seen_ids": seen_list
    }


def get_closed_candles(market_state, now_ts):
    current_bucket = int(now_ts // CANDLE_SECONDS) * CANDLE_SECONDS

    return [
        candle
        for candle in market_state.get("candles", [])
        if number(candle.get("t"), current_bucket) < current_bucket
    ]


def consecutive_enough(candles, count):
    if len(candles) < count:
        return False

    recent = candles[-count:]

    for index in range(1, len(recent)):
        if (
            int(recent[index]["t"])
            - int(recent[index - 1]["t"])
        ) != CANDLE_SECONDS:
            return False

    return True


# ============================================================
# SIGNAL ANALYSIS
# ============================================================

def analyze_market(symbol, trades, market_state, now_ts):
    if not trades:
        return {
            "status": "WAIT",
            "reason": "داده معتبر معاملات موجود نیست"
        }

    last_trade = trades[-1]
    price = last_trade["price"]
    age_minutes = (now_ts - last_trade["time"]) / 60.0

    if age_minutes < -2:
        return {
            "status": "WAIT",
            "price": price,
            "reason": "زمان آخرین معامله نامعتبر است"
        }

    if age_minutes > MAX_TRADE_AGE_MINUTES:
        return {
            "status": "WAIT",
            "price": price,
            "reason": "آخرین معامله بیش از حد قدیمی است"
        }

    candles = get_closed_candles(market_state, now_ts)

    if not consecutive_enough(candles, MIN_CLOSED_CANDLES):
        return {
            "status": "WAIT",
            "price": price,
            "reason": (
                f"تاریخچه ناکافی؛ {MIN_CLOSED_CANDLES} "
                "کندل بسته‌شده پیوسته لازم است"
            )
        }

    recent = candles[-MIN_CLOSED_CANDLES:]
    confirmation = recent[-1]
    previous = recent[-2]
    support_candles = recent[:-1]

    support = min(
        number(candle.get("low"))
        for candle in support_candles
    )

    if support <= 0:
        return {
            "status": "WAIT",
            "price": price,
            "reason": "حمایت قابل محاسبه نیست"
        }

    distance = (price - support) / support
    near_support = -0.002 <= distance <= SUPPORT_ZONE_PERCENT

    bullish = (
        number(confirmation.get("close"))
        > number(confirmation.get("open"))
    )

    higher_close = (
        number(confirmation.get("close"))
        > number(previous.get("close"))
    )

    breakout_confirmation = (
        number(confirmation.get("close"))
        > number(previous.get("high"))
    )

    confirmed = bullish and higher_close and breakout_confirmation

    if not near_support:
        return {
            "status": "WAIT",
            "price": price,
            "support": support,
            "reason": "قیمت در محدوده مناسب حمایت نیست"
        }

    if not confirmed:
        return {
            "status": "WATCH",
            "price": price,
            "support": support,
            "reason": "نزدیک حمایت است اما تأیید صعودی کامل نیست"
        }

    entry = price

    stop = min(
        support * 0.99,
        number(confirmation.get("low")) * 0.995
    )

    risk = entry - stop

    if entry <= 0 or risk <= 0:
        return {
            "status": "WAIT",
            "price": price,
            "reason": "محاسبه حد ضرر نامعتبر است"
        }

    stop_percent = risk / entry * 100

    if stop_percent > MAX_STOP_PERCENT * 100:
        return {
            "status": "WATCH",
            "price": price,
            "support": support,
            "reason": "فاصله حد ضرر بیش از حد زیاد است"
        }

    budget = CAPITAL_USDT / MAX_SIGNALS

    return {
        "status": "BUY",
        "price": price,
        "support": support,
        "entry": entry,
        "stop": stop,
        "tp1": entry + risk,
        "tp2": entry + risk * 1.8,
        "tp3": entry + risk * 2.5,
        "stop_percent": stop_percent,
        "budget": budget,
        "quantity": budget / entry,
        "reason": "حمایت و کندل بسته‌شده تأیید شدند"
    }


# ============================================================
# TELEGRAM REPORT
# ============================================================

def format_signal(symbol, result, index):
    return (
        f"🟢 سیگنال خرید اسپات {index}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 بازار: {symbol}\n"
        f"📍 ورود فرضی: {fmt_price(result['entry'])}\n"
        f"🛑 حد ضرر: {fmt_price(result['stop'])}\n"
        f"🎯 TP1: {fmt_price(result['tp1'])}\n"
        f"🎯 TP2: {fmt_price(result['tp2'])}\n"
        f"🎯 TP3: {fmt_price(result['tp3'])}\n"
        f"📉 فاصله حد ضرر: {result['stop_percent']:.2f}%\n"
        f"💰 بودجه فرضی: {result['budget']:.2f} USDT\n"
        f"📦 مقدار فرضی: {result['quantity']:.8f}\n"
        f"📊 حمایت: {fmt_price(result['support'])}\n"
        f"🕒 {utc_text()}\n"
        f"🧪 فقط آزمایشی؛ بدون سفارش واقعی"
    )


# ============================================================
# MAIN SCAN
# ============================================================

def run_scan():
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing."
        )

    started = time.time()
    logging.info("Starting %s", BOT_NAME)

    state, state_sha = load_state()
    market_states = state.setdefault("markets", {})

    markets = fetch_markets()

    stats = {
        "checked": 0,
        "errors": 0,
        "wait": 0,
        "watch": 0
    }

    buy_signals = []
    watch_items = []
    wait_reasons = {}

    for market in markets:
        symbol = market.get("_bot_symbol")

        if not symbol:
            continue

        stats["checked"] += 1

        try:
            trades = fetch_trades(symbol)

            old_state = market_states.get(
                symbol,
                empty_market_state()
            )

            updated_state = update_market_history(
                old_state,
                trades,
                time.time()
            )

            market_states[symbol] = updated_state

            result = analyze_market(
                symbol,
                trades,
                updated_state,
                time.time()
            )

            status = result.get("status", "WAIT")

            if status == "BUY":
                buy_signals.append((symbol, result))

            elif status == "WATCH":
                stats["watch"] += 1

                if len(watch_items) < 5:
                    watch_items.append((symbol, result))

            else:
                stats["wait"] += 1
                reason = result.get(
                    "reason", "شرایط ورود کامل نیست"
                )
                wait_reasons[reason] = (
                    wait_reasons.get(reason, 0) + 1
                )

        except Exception as exc:
            stats["errors"] += 1
            logging.warning(
                "Analysis failed for %s: %s",
                symbol, exc
            )

        # Keep request rate low.
        time.sleep(REQUEST_DELAY_SECONDS)

    buy_signals.sort(
        key=lambda item: item[1].get("stop_percent", 100)
    )
    buy_signals = buy_signals[:MAX_SIGNALS]

    state["updated_at"] = utc_text()
    saved = save_state(state, state_sha)

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش اسکن بازار بیت‌پین",
        f"🕒 {utc_text()}",
        "━━━━━━━━━━━━━━━━━━",
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT",
        f"📈 بازارهای بررسی‌شده: {stats['checked']}",
        f"🟢 خریدهای تأییدشده: {len(buy_signals)}",
        f"🟡 موارد تحت نظر: {stats['watch']}",
        f"⚪ موارد انتظار: {stats['wait']}",
        f"⚠️ خطاهای تحلیل: {stats['errors']}",
        f"💾 ذخیره تاریخچه: {'موفق' if saved else 'ناموفق'}",
        f"⏱ زمان اجرا: {time.time() - started:.1f} ثانیه",
        "",
        "🧪 فقط سیگنال آزمایشی اسپات",
        "🚫 سفارش واقعی: خاموش",
        "━━━━━━━━━━━━━━━━━━"
    ]

    if buy_signals:
        lines.append("")

        for index, (symbol, result) in enumerate(
            buy_signals, start=1
        ):
            lines.append(format_signal(symbol, result, index))
            lines.append("")

    else:
        lines.extend([
            "",
            "⚪ فعلاً سیگنال خرید تأییدشده‌ای وجود ندارد."
        ])

    if watch_items:
        lines.extend([
            "",
            "🟡 موارد تحت نظر",
            "━━━━━━━━━━━━━━━━━━"
        ])

        for symbol, result in watch_items:
            lines.append(
                f"• {symbol} | قیمت: "
                f"{fmt_price(result.get('price', 0))} | "
                f"حمایت: {fmt_price(result.get('support', 0))}"
            )
            lines.append(f"  علت: {result.get('reason', '')}")

    if wait_reasons:
        lines.extend(["", "📌 دلایل پرتکرار انتظار:"])

        for reason, count in sorted(
            wait_reasons.items(),
            key=lambda item: item[1],
            reverse=True
        )[:3]:
            lines.append(f"• {reason}: {count}")

    message = "\n".join(lines)

    if len(message) > 3900:
        message = message[:3800] + "\nگزارش کوتاه شد."

    delivered = send_telegram(message)

    logging.info(
        "Scan complete. Telegram=%s | stats=%s",
        delivered, stats
    )


if __name__ == "__main__":
    try:
        run_scan()

    except Exception as exc:
        logging.exception("Scan failed")

        send_telegram(
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ اسکن کامل نشد\n"
            f"علت: {str(exc)[:700]}\n\n"
            "🧪 حالت آزمایشی\n"
            "🚫 سفارش واقعی خاموش"
        )

        raise
