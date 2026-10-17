
import os
import json
import time
import base64
import logging
import requests

from datetime import datetime, timezone
from urllib.parse import quote

# ============================================================
# ETH WHALE | BITPIN SPOT SIGNAL BOT
# PAPER SIGNALS ONLY - NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"

BASE_URL = "https://api.bitpin.ir"
MARKETS_URL = f"{BASE_URL}/v1/mkt/markets/"
TRADES_URL = f"{BASE_URL}/api/v1/mth/matches/"
ORDERBOOK_URL = f"{BASE_URL}/api/v1/mth/orderbook/"

CAPITAL_USDT = 48.0
MAX_MARKETS = 40
MAX_SIGNALS = 3

CANDLE_MINUTES = 15
CANDLE_SECONDS = CANDLE_MINUTES * 60

MIN_CLOSED_CANDLES = 21
MAX_CANDLE_HISTORY = 300
MAX_SEEN_TRADE_IDS = 5000

SUPPORT_ZONE_PERCENT = 0.012
MAX_STOP_PERCENT = 0.045
MAX_TRADE_AGE_MINUTES = 30

STATE_PATH = "data/market_history.json"
GITHUB_API = "https://api.github.com"

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Paper-Signal-Bot/6.0",
    "Accept": "application/json"
})


# ============================================================
# GENERAL HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_text(timestamp=None):
    if timestamp is None:
        timestamp = time.time()

    return datetime.fromtimestamp(
        timestamp, timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def number(value, default=0.0):
    try:
        if isinstance(value, dict):
            return default

        result = float(value)

        if result != result or abs(result) == float("inf"):
            return default

        return result

    except (TypeError, ValueError, OverflowError):
        return default


def api_get(url, params=None, timeout=15):
    response = SESSION.get(
        url,
        params=params,
        timeout=timeout
    )
    response.raise_for_status()
    return response.json()


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


def get_symbol(market):
    for key in ("symbol", "code", "market", "name"):
        value = market.get(key)

        if isinstance(value, str) and "_USDT" in value.upper():
            symbol = value.upper().replace("-", "_").strip()

            if symbol.endswith("_USDT"):
                return symbol

    return ""


def get_market_volume(market):
    keys = (
        "quote_volume",
        "quoteVolume",
        "volume_24h",
        "volume",
        "volume24h",
        "turnover"
    )

    for key in keys:
        value = number(market.get(key), 0)

        if value > 0:
            return value

    info = market.get("price_info")

    if isinstance(info, dict):
        for key in keys:
            value = number(info.get(key), 0)

            if value > 0:
                return value

    return 0.0


# ============================================================
# GITHUB PERSISTENT HISTORY
# ============================================================

def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }


def load_state():
    empty_state = {"markets": {}}

    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logging.warning(
            "GitHub persistence is not configured. "
            "History will not survive a new Actions run."
        )
        return empty_state, None

    url = (
        f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}"
        f"/contents/{STATE_PATH}"
    )

    try:
        response = SESSION.get(
            url,
            headers=github_headers(),
            timeout=15
        )

        if response.status_code == 404:
            return empty_state, None

        response.raise_for_status()
        payload = response.json()

        encoded = payload.get("content", "")
        raw = base64.b64decode(encoded).decode("utf-8")
        state = json.loads(raw)

        if not isinstance(state, dict):
            return empty_state, payload.get("sha")

        if not isinstance(state.get("markets"), dict):
            state["markets"] = {}

        return state, payload.get("sha")

    except Exception as exc:
        logging.error("Could not load saved history: %s", exc)
        return empty_state, None


def save_state(state, sha):
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logging.warning(
            "History NOT saved permanently: GitHub token/repository "
            "is missing."
        )
        return False

    url = (
        f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}"
        f"/contents/{STATE_PATH}"
    )

    raw = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":")
    )

    encoded = base64.b64encode(
        raw.encode("utf-8")
    ).decode("ascii")

    payload = {
        "message": "Update ETH WHALE market history",
        "content": encoded
    }

    if sha:
        payload["sha"] = sha

    try:
        response = SESSION.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=25
        )

        if response.status_code not in (200, 201):
            logging.error(
                "Could not save history: HTTP %s %s",
                response.status_code,
                response.text[:500]
            )
            return False

        logging.info("Market history saved to GitHub.")
        return True

    except Exception as exc:
        logging.error("Saving history failed: %s", exc)
        return False


# ============================================================
# BITPIN MARKETS
# ============================================================

def fetch_markets():
    all_markets = []
    known_symbols = set()
    page = 1
    next_url = MARKETS_URL

    for _ in range(50):
        try:
            if next_url:
                if next_url == MARKETS_URL and page > 1:
                    payload = api_get(
                        MARKETS_URL,
                        params={"page": page}
                    )
                else:
                    payload = api_get(next_url)
            else:
                break

        except Exception as exc:
            if not all_markets:
                raise RuntimeError(
                    f"Could not retrieve Bitpin markets: {exc}"
                )

            logging.warning("Markets pagination stopped: %s", exc)
            break

        if isinstance(payload, list):
            rows = payload
            next_page = None
            total_count = len(rows)

        elif isinstance(payload, dict):
            rows = payload.get("results", [])
            next_page = payload.get("next")
            total_count = int(
                number(payload.get("count"), len(rows))
            )

        else:
            break

        if not isinstance(rows, list) or not rows:
            break

        added = 0

        for market in rows:
            if not isinstance(market, dict):
                continue

            symbol = get_symbol(market)

            if not symbol or symbol in known_symbols:
                continue

            known_symbols.add(symbol)
            market["_bot_symbol"] = symbol
            market["_bot_volume"] = get_market_volume(market)
            all_markets.append(market)
            added += 1

        if next_page:
            next_url = next_page
            page += 1
            continue

        next_url = None

        if len(known_symbols) >= total_count:
            break

        if added == 0:
            break

        # Try the next page when the endpoint is paginated.
        page += 1
        next_url = MARKETS_URL

    # Prefer markets with usable reported trading volume.
    all_markets.sort(
        key=lambda item: item.get("_bot_volume", 0),
        reverse=True
    )

    selected = all_markets[:MAX_MARKETS]

    if not selected:
        raise RuntimeError(
            "No USDT markets were found in Bitpin response."
        )

    logging.info(
        "USDT markets found: %s | selected: %s",
        len(all_markets),
        len(selected)
    )

    return selected


# ============================================================
# BITPIN RECENT TRADES
# ============================================================

def fetch_trades(symbol):
    safe_symbol = quote(symbol, safe="_")
    url = f"{TRADES_URL}{safe_symbol}/"

    payload = api_get(url, timeout=15)

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
                f"{int(stamp * 1000)}:"
                f"{price}:"
                f"{trade.get('base_amount', '')}:"
                f"{trade.get('side', '')}"
            )

        base_amount = number(
            trade.get("base_amount"),
            0.0
        )

        quote_amount = number(
            trade.get("quote_amount"),
            price * base_amount
        )

        valid.append({
            "id": str(trade_id),
            "time": stamp,
            "price": price,
            "base_amount": base_amount,
            "quote_amount": quote_amount
        })

    valid.sort(key=lambda item: item["time"])
    return valid


# ============================================================
# CANDLE HISTORY BUILDER
# Candles are reconstructed from trades observed by this bot.
# They are NOT guaranteed to be exchange-certified OHLC candles.
# ============================================================

def empty_market_state():
    return {
        "candles": [],
        "seen_ids": []
    }


def update_market_history(market_state, trades, now_ts):
    if not isinstance(market_state, dict):
        market_state = empty_market_state()

    candles = market_state.get("candles", [])
    seen_ids = market_state.get("seen_ids", [])

    if not isinstance(candles, list):
        candles = []

    if not isinstance(seen_ids, list):
        seen_ids = []

    seen = set(str(x) for x in seen_ids)
    candle_map = {}

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        bucket = int(number(candle.get("t"), -1))

        if bucket >= 0:
            candle_map[bucket] = candle

    # Process trades from oldest to newest.
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
            number(candle.get("high"), price),
            price
        )

        candle["low"] = min(
            number(candle.get("low"), price),
            price
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
            number(candle.get("volume"), 0.0)
            + number(trade.get("quote_amount"), 0.0)
        )

    # Keep only recent candles.
    cutoff = now_ts - (MAX_CANDLE_HISTORY * CANDLE_SECONDS)

    candle_list = [
        candle
        for bucket, candle in candle_map.items()
        if bucket >= cutoff
    ]

    candle_list.sort(key=lambda item: item["t"])

    # Limit the seen-ID cache.
    seen_list = list(seen)

    if len(seen_list) > MAX_SEEN_TRADE_IDS:
        seen_list = seen_list[-MAX_SEEN_TRADE_IDS:]

    return {
        "candles": candle_list,
        "seen_ids": seen_list
    }


def closed_candles(market_state, now_ts):
    candles = market_state.get("candles", [])
    current_bucket = int(now_ts // CANDLE_SECONDS) * CANDLE_SECONDS

    return [
        candle for candle in candles
        if number(candle.get("t"), current_bucket) < current_bucket
    ]


def has_consecutive_candles(candles, required):
    if len(candles) < required:
        return False

    recent = candles[-required:]

    for index in range(1, len(recent)):
        if (
            int(recent[index]["t"]) -
            int(recent[index - 1]["t"])
        ) != CANDLE_SECONDS:
            return False

    return True


# ============================================================
# MARKET ANALYSIS
# BUY requires support proximity AND a closed bullish candle.
# No short signals. No futures. No real orders.
# ============================================================

def analyze_market(symbol, trades, market_state, now_ts):
    if not trades:
        return {
            "status": "WAIT",
            "reason": "داده معاملات معتبر موجود نیست"
        }

    latest_trade = trades[-1]
    current_price = latest_trade["price"]

    age_minutes = (now_ts - latest_trade["time"]) / 60.0

    if age_minutes < -2:
        return {
            "status": "WAIT",
            "price": current_price,
            "reason": "زمان داده بازار نامعتبر است"
        }

    if age_minutes > MAX_TRADE_AGE_MINUTES:
        return {
            "status": "WAIT",
            "price": current_price,
            "reason": "آخرین معامله بیش از حد قدیمی است"
        }

    candles = closed_candles(market_state, now_ts)

    if not has_consecutive_candles(
        candles,
        MIN_CLOSED_CANDLES
    ):
        return {
            "status": "WAIT",
            "price": current_price,
            "reason": (
                f"تاریخچه کافی نیست؛ حداقل "
                f"{MIN_CLOSED_CANDLES} کندل بسته‌شده "
                f"پیوسته لازم است"
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
            "price": current_price,
            "reason": "محاسبه حمایت معتبر نیست"
        }

    distance = (current_price - support) / support

    near_support = (
        -0.002 <= distance <= SUPPORT_ZONE_PERCENT
    )

    bullish_candle = (
        number(confirmation.get("close"))
        > number(confirmation.get("open"))
    )

    improving_close = (
        number(confirmation.get("close"))
        > number(previous.get("close"))
    )

    close_above_previous_high = (
        number(confirmation.get("close"))
        > number(previous.get("high"))
    )

    confirmed = (
        bullish_candle
        and improving_close
        and close_above_previous_high
    )

    if not near_support:
        return {
            "status": "WAIT",
            "price": current_price,
            "support": support,
            "reason": "قیمت در محدوده مناسب حمایت نیست"
        }

    if not confirmed:
        return {
            "status": "WATCH",
            "price": current_price,
            "support": support,
            "reason": (
                "قیمت نزدیک حمایت است، اما کندل صعودی "
                "بسته‌شده تأیید کامل نداده است"
            )
        }

    entry = current_price

    # Place the simulated stop below support and confirmation low.
    stop = min(
        support * 0.99,
        number(confirmation.get("low")) * 0.995
    )

    risk = entry - stop

    if entry <= 0 or risk <= 0:
        return {
            "status": "WAIT",
            "price": current_price,
            "support": support,
            "reason": "محاسبه ورود یا حد ضرر نامعتبر است"
        }

    stop_percent = risk / entry

    if stop_percent > MAX_STOP_PERCENT:
        return {
            "status": "WATCH",
            "price": current_price,
            "support": support,
            "reason": "فاصله حد ضرر زیاد است"
        }

    tp1 = entry + risk * 1.0
    tp2 = entry + risk * 1.8
    tp3 = entry + risk * 2.5

    # Paper budget only; this does not place any order.
    simulated_budget = CAPITAL_USDT / MAX_SIGNALS
    estimated_quantity = simulated_budget / entry

    return {
        "status": "BUY",
        "price": current_price,
        "support": support,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "stop_percent": stop_percent * 100,
        "budget": simulated_budget,
        "quantity": estimated_quantity,
        "reason": "حمایت و کندل تأییدی بررسی شدند"
    }


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error(
            "Telegram credentials missing. "
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )
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
            timeout=20
        )

        if response.status_code != 200:
            logging.error(
                "Telegram error: %s %s",
                response.status_code,
                response.text[:500]
            )
            return False

        result = response.json()

        if not result.get("ok"):
            logging.error("Telegram did not confirm delivery.")
            return False

        return True

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


def format_signal(symbol, result, index):
    return (
        f"🟢 سیگنال خرید اسپات شماره {index}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 بازار: {symbol}\n"
        f"📍 ورود فرضی: {fmt_price(result['entry'])}\n"
        f"🛑 حد ضرر: {fmt_price(result['stop'])}\n"
        f"🎯 TP1: {fmt_price(result['tp1'])}\n"
        f"🎯 TP2: {fmt_price(result['tp2'])}\n"
        f"🎯 TP3: {fmt_price(result['tp3'])}\n"
        f"📉 ریسک تا حد ضرر: "
        f"{result['stop_percent']:.2f}%\n"
        f"💰 بودجه فرضی: {result['budget']:.2f} USDT\n"
        f"📦 مقدار فرضی: {result['quantity']:.8f}\n"
        f"📊 حمایت: {fmt_price(result['support'])}\n"
        f"🕒 {utc_text()}\n"
        f"🧪 PAPER ONLY — بدون سفارش واقعی"
    )


# ============================================================
# MAIN SCAN
# ============================================================

def run_scan():
    now_ts = time.time()

    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Telegram credentials missing. "
            "Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )

    logging.info("Starting %s", BOT_NAME)

    state, state_sha = load_state()
    market_states = state.setdefault("markets", {})

    markets = fetch_markets()

    stats = {
        "checked": 0,
        "errors": 0,
        "wait": 0,
        "watch": 0,
        "buy": 0
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

            old_market_state = market_states.get(
                symbol,
                empty_market_state()
            )

            new_market_state = update_market_history(
                old_market_state,
                trades,
                now_ts
            )

            market_states[symbol] = new_market_state

            result = analyze_market(
                symbol,
                trades,
                new_market_state,
                now_ts
            )

            status = result.get("status", "WAIT")

            if status == "BUY":
                stats["buy"] += 1
                buy_signals.append((symbol, result))

            elif status == "WATCH":
                stats["watch"] += 1

                if len(watch_items) < 5:
                    watch_items.append((symbol, result))

            else:
                stats["wait"] += 1
                reason = result.get(
                    "reason",
                    "شرایط ورود کامل نیست"
                )
                wait_reasons[reason] = (
                    wait_reasons.get(reason, 0) + 1
                )

        except Exception as exc:
            stats["errors"] += 1
            logging.warning(
                "Analysis failed for %s: %s",
                symbol,
                exc
            )

        # Avoid unnecessarily rapid requests.
        time.sleep(0.15)

    # Keep the highest-quality/closest-to-support candidates first.
    buy_signals.sort(
        key=lambda item: item[1].get("stop_percent", 100)
    )
    buy_signals = buy_signals[:MAX_SIGNALS]

    # Save the state before sending a report.
    state["updated_at"] = utc_text(now_ts)
    save_state(state, state_sha)

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش اسکن بازار بیت‌پین",
        f"🕒 {utc_text(now_ts)}",
        "━━━━━━━━━━━━━━━━━━",
        f"💰 سرمایه آزمایشی: {CAPITAL_USDT:.2f} USDT",
        f"📈 بازارهای بررسی‌شده: {stats['checked']}",
        f"🟢 خریدهای تأییدشده: {len(buy_signals)}",
        f"🟡 موارد تحت نظر: {stats['watch']}",
        f"⚪ موارد انتظار: {stats['wait']}",
        f"⚠️ خطاهای تحلیل: {stats['errors']}",
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
            "🟡 بازارهای نزدیک حمایت — WATCH",
            "━━━━━━━━━━━━━━━━━━"
        ])

        for symbol, result in watch_items:
            lines.append(
                f"• {symbol} | قیمت: "
                f"{fmt_price(result.get('price', 0))} | "
                f"حمایت: {fmt_price(result.get('support', 0))}"
            )
            lines.append(
                f"  علت: {result.get('reason', '')}"
            )

    if wait_reasons:
        lines.extend([
            "",
            "📌 دلایل پرتکرار WAIT:"
        ])

        common_reasons = sorted(
            wait_reasons.items(),
            key=lambda item: item[1],
            reverse=True
        )[:3]

        for reason, count in common_reasons:
            lines.append(f"• {reason}: {count}")

    message = "\n".join(lines)

    # Telegram message size safety.
    if len(message) > 3900:
        message = message[:3850] + "\n\nگزارش کوتاه شد."

    delivered = send_telegram(message)

    logging.info(
        "Scan complete. Telegram delivered=%s; stats=%s",
        delivered,
        stats
    )


if __name__ == "__main__":
    try:
        run_scan()

    except Exception as exc:
        logging.exception("Scan failed")

        error_message = (
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ اسکن کامل نشد\n"
            f"علت: {str(exc)[:700]}\n\n"
            "🧪 حالت آزمایشی\n"
            "🚫 سفارش واقعی خاموش"
        )

        send_telegram(error_message)
        raise
