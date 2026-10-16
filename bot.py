import os
import json
import time
import base64
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ============================================================
# ETH WHALE - BITPIN PAPER SIGNAL BOT
# PAPER TRADING ONLY - NO REAL ORDERS
# ============================================================

BITPIN_BASE = "https://api.bitpin.ir"

CAPITAL_USDT = 100.0
LEVERAGE = 3
POSITION_USDT = CAPITAL_USDT * LEVERAGE
PAPER_MODE = True

MAX_SIGNALS_PER_RUN = 3
MAX_WORKERS = 6
MAX_MARKETS = 0
TRADES_TO_ANALYZE = 30

MIN_CHANGE_PERCENT = 0.35
MIN_DIRECTIONAL_CONSISTENCY = 60.0

STOP_PERCENT = 0.80
TP1_PERCENT = 0.80
TP2_PERCENT = 1.60
TP3_PERCENT = 2.40

SIGNAL_COOLDOWN_HOURS = 6
REQUEST_TIMEOUT = 15
STATE_FILE = "bot_state.json"

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or ""
).strip()

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME", "main").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Eth-Whale-Bitpin-Paper-Bot/3.0",
    "Accept": "application/json",
})


# ============================================================
# HELPERS
# ============================================================

def now_ts():
    return time.time()


def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def as_float(value):
    try:
        number = float(value)
        if number > 0:
            return number
    except (TypeError, ValueError):
        pass
    return None


def format_price(value):
    value = float(value)

    if value >= 100:
        return f"{value:.4f}"
    if value >= 1:
        return f"{value:.6f}"
    if value >= 0.01:
        return f"{value:.7f}"

    return f"{value:.8f}"


def get_json(url, params=None, headers=None):
    response = SESSION.get(
        url,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def extract_list(data):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in (
        "results",
        "data",
        "markets",
        "trades",
        "matches",
        "items",
    ):
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            for nested_key in (
                "results",
                "items",
                "data",
                "trades",
            ):
                nested = value.get(nested_key)

                if isinstance(nested, list):
                    return nested

    if isinstance(data.get("tickers"), dict):
        rows = []

        for symbol, item in data["tickers"].items():
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("symbol", symbol)
                rows.append(row)

        return rows

    return []


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Telegram token or chat ID is missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            logging.error("Telegram returned ok=false: %s", result)
            return False

        logging.info("Telegram message sent.")
        return True

    except Exception as exc:
        logging.error("Telegram send failed: %s", exc)
        return False


# ============================================================
# STATE STORAGE
# GitHub Contents API persistence
# ============================================================

def default_state():
    return {
        "version": 1,
        "active_trades": {},
        "last_signal_at": {},
        "updated_at": now_text(),
    }


def github_file_url():
    if not GITHUB_REPOSITORY:
        return None

    return (
        "https://api.github.com/repos/"
        + GITHUB_REPOSITORY
        + "/contents/"
        + STATE_FILE
    )


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_state():
    url = github_file_url()

    if url and GITHUB_TOKEN:
        response = requests.get(
            url,
            headers=github_headers(),
            params={"ref": GITHUB_REF_NAME},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 404:
            logging.info("State file not found; starting fresh.")
            return default_state(), None

        response.raise_for_status()
        payload = response.json()

        content = payload.get("content", "")
        raw = base64.b64decode(
            content.replace("\n", "")
        ).decode("utf-8")

        state = json.loads(raw)

        if not isinstance(state, dict):
            raise RuntimeError("Invalid saved state.")

        state.setdefault("active_trades", {})
        state.setdefault("last_signal_at", {})

        logging.info("State loaded from GitHub.")
        return state, payload.get("sha")

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        state.setdefault("active_trades", {})
        state.setdefault("last_signal_at", {})

        logging.warning("State loaded locally only.")
        return state, None

    logging.warning(
        "GitHub persistence is not configured; "
        "state will be local only."
    )

    return default_state(), None


def save_state(state, existing_sha=None):
    state["updated_at"] = now_text()

    serialized = json.dumps(
        state,
        ensure_ascii=False,
        indent=2,
    )

    url = github_file_url()

    if url and GITHUB_TOKEN:
        body = {
            "message": "Update Eth Whale paper trading state",
            "content": base64.b64encode(
                serialized.encode("utf-8")
            ).decode("ascii"),
            "branch": GITHUB_REF_NAME,
        }

        if existing_sha:
            body["sha"] = existing_sha

        response = requests.put(
            url,
            headers=github_headers(),
            json=body,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        logging.info("State saved to GitHub.")
        return

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        file.write(serialized)

    logging.warning("State saved locally only.")


# ============================================================
# BITPIN MARKET DISCOVERY
# ============================================================

def get_usdt_markets():
    url = f"{BITPIN_BASE}/v1/mkt/markets/"
    markets_by_symbol = {}
    page = 1

    while url and page <= 100:
        params = {"page": page} if page == 1 else None

        data = get_json(url, params=params)
        rows = extract_list(data)

        if not rows:
            break

        for market in rows:
            if not isinstance(market, dict):
                continue

            symbol = str(
                market.get("symbol")
                or market.get("code")
                or market.get("name")
                or ""
            ).strip().upper()

            base = str(
                market.get("base_currency")
                or market.get("base")
                or ""
            ).strip().upper()

            quote = str(
                market.get("quote_currency")
                or market.get("quote")
                or ""
            ).strip().upper()

            if not symbol:
                continue

            is_usdt = (
                symbol.endswith("_USDT")
                or symbol.endswith("-USDT")
                or quote == "USDT"
            )

            if not is_usdt:
                continue

            symbol = symbol.replace("-", "_")

            markets_by_symbol[symbol] = {
                "symbol": symbol,
                "base": base,
                "quote": "USDT",
            }

        if isinstance(data, dict) and data.get("next"):
            url = urljoin(url, data["next"])
            page += 1
        else:
            break

    markets = list(markets_by_symbol.values())

    if MAX_MARKETS > 0:
        markets = markets[:MAX_MARKETS]

    return markets


# ============================================================
# RECENT TRADE DATA
# This strategy analyzes recent trades, not candles.
# ============================================================

def get_recent_trades(symbol):
    url = (
        f"{BITPIN_BASE}/api/v1/mth/"
        f"matches/{symbol}/"
    )

    data = get_json(url)
    rows = extract_list(data)
    trades = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        price = as_float(row.get("price"))

        if price is None:
            continue

        timestamp = (
            row.get("time")
            or row.get("timestamp")
            or row.get("created_at")
            or row.get("id")
        )

        trades.append({
            "price": price,
            "time": timestamp,
        })

    if len(trades) > 1:
        try:
            if all(item["time"] is not None for item in trades):
                def time_key(item):
                    value = item["time"]

                    try:
                        return (0, float(value))
                    except (TypeError, ValueError):
                        return (1, str(value))

                trades.sort(key=time_key)

        except Exception as exc:
            logging.debug("Trade sorting skipped: %s", exc)

    return trades[-TRADES_TO_ANALYZE:]


def get_current_price(symbol):
    trades = get_recent_trades(symbol)

    if not trades:
        return None

    return trades[-1]["price"]


# ============================================================
# SIGNAL ANALYSIS
# ============================================================

def analyze_market(market):
    symbol = market["symbol"]

    try:
        trades = get_recent_trades(symbol)

        if len(trades) < 10:
            return None

        prices = [item["price"] for item in trades]

        first_price = prices[0]
        last_price = prices[-1]

        if first_price <= 0 or last_price <= 0:
            return None

        change_pct = (
            (last_price - first_price) / first_price
        ) * 100.0

        if abs(change_pct) < MIN_CHANGE_PERCENT:
            return None

        if last_price > first_price:
            direction = "LONG"

            favorable = sum(
                1
                for previous, current in zip(
                    prices,
                    prices[1:],
                )
                if current > previous
            )

        elif last_price < first_price:
            direction = "SHORT"

            favorable = sum(
                1
                for previous, current in zip(
                    prices,
                    prices[1:],
                )
                if current < previous
            )

        else:
            return None

        steps = len(prices) - 1

        if steps <= 0:
            return None

        consistency = favorable / steps * 100.0

        if consistency < MIN_DIRECTIONAL_CONSISTENCY:
            return None

        movement_score = (
            min(abs(change_pct) / 0.50, 1.0) * 40.0
        )

        score = round(
            consistency * 0.60 + movement_score,
            1,
        )

        entry = last_price

        if direction == "LONG":
            stop = entry * (1 - STOP_PERCENT / 100)
            tp1 = entry * (1 + TP1_PERCENT / 100)
            tp2 = entry * (1 + TP2_PERCENT / 100)
            tp3 = entry * (1 + TP3_PERCENT / 100)

        else:
            stop = entry * (1 + STOP_PERCENT / 100)
            tp1 = entry * (1 - TP1_PERCENT / 100)
            tp2 = entry * (1 - TP2_PERCENT / 100)
            tp3 = entry * (1 - TP3_PERCENT / 100)

        return {
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "change_pct": change_pct,
            "consistency": consistency,
            "score": score,
            "trades_count": len(trades),
            "opened_at": now_ts(),
            "reached_targets": [],
        }

    except Exception as exc:
        logging.warning(
            "%s analysis failed: %s",
            symbol,
            exc,
        )
        return None


# ============================================================
# TELEGRAM MESSAGE FORMATTING
# ============================================================

def safe_html(value):
    text_value = str(value)
    return (
        text_value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def signal_message(signal, number):
    if signal["direction"] == "LONG":
        direction_text = "🟢 LONG | خرید آزمایشی"
    else:
        direction_text = "🔴 SHORT | فروش آزمایشی"

    tp1_pnl = POSITION_USDT * TP1_PERCENT / 100
    tp2_pnl = POSITION_USDT * TP2_PERCENT / 100
    tp3_pnl = POSITION_USDT * TP3_PERCENT / 100
    sl_pnl = -POSITION_USDT * STOP_PERCENT / 100

    symbol = safe_html(signal["symbol"])

    return (
        "🌊 <b>ETH WHALE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>سیگنال #{number}</b> | {direction_text}\n"
        f"💎 جفت‌ارز: <code>{symbol}</code>\n"
        f"⭐ امتیاز الگوریتم: <b>{signal['score']}/100</b>\n"
        f"📈 تغییر معاملات اخیر: "
        f"<b>{signal['change_pct']:+.3f}%</b>\n"
        f"🎯 هم‌جهتی حرکت‌ها: "
        f"<b>{signal['consistency']:.1f}%</b>\n"
        f"🔎 تعداد معاملات بررسی‌شده: "
        f"<b>{signal['trades_count']}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💰 <b>قیمت‌های فرضی</b>\n"
        f"🔹 ورود: "
        f"<code>{format_price(signal['entry'])}</code>\n"
        f"🛑 حد ضرر: "
        f"<code>{format_price(signal['stop'])}</code>\n"
        f"🎯 TP1: "
        f"<code>{format_price(signal['tp1'])}</code>\n"
        f"🎯 TP2: "
        f"<code>{format_price(signal['tp2'])}</code>\n"
        f"🏆 TP3: "
        f"<code>{format_price(signal['tp3'])}</code>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚙️ <b>مدیریت سرمایه</b>\n"
        f"💵 سرمایه: <b>{CAPITAL_USDT:.2f} USDT</b>\n"
        f"⚡ اهرم: <b>{LEVERAGE}x</b>\n"
        f"📦 ارزش اسمی موقعیت: "
        f"<b>{POSITION_USDT:.2f} USDT</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>سود و زیان ناخالص فرضی</b>\n"
        f"🟢 TP1: <b>+{tp1_pnl:.2f} USDT</b>\n"
        f"🟢 TP2: <b>+{tp2_pnl:.2f} USDT</b>\n"
        f"🟢 TP3: <b>+{tp3_pnl:.2f} USDT</b>\n"
        f"🔴 حد ضرر: <b>{sl_pnl:.2f} USDT</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧪 <b>PAPER TRADING ONLY</b>\n"
        "🚫 سفارش واقعی ثبت نمی‌شود.\n"
        "⚠️ تحلیل معاملات اخیر است و سود تضمین نمی‌شود.\n"
        f"🕒 {now_text()}"
    )


def target_message(trade, target_name, current_price):
    symbol = safe_html(trade["symbol"])

    return (
        "🌊 <b>ETH WHALE | هدف لمس شد</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💎 جفت‌ارز: <code>{symbol}</code>\n"
        f"📌 جهت: <b>{trade['direction']}</b>\n"
        f"🎯 هدف: <b>{target_name}</b>\n"
        f"💹 قیمت مشاهده‌شده: "
        f"<code>{format_price(current_price)}</code>\n"
        f"🔹 ورود: "
        f"<code>{format_price(trade['entry'])}</code>\n"
        "ℹ️ هشدار آزمایشی؛ سفارش واقعی اجرا نشده است."
    )


def closed_message(trade, reason, current_price, pnl):
    symbol = safe_html(trade["symbol"])
    icon = "🟢" if pnl >= 0 else "🔴"

    return (
        "🌊 <b>ETH WHALE | معامله آزمایشی بسته شد</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💎 جفت‌ارز: <code>{symbol}</code>\n"
        f"📌 جهت: <b>{trade['direction']}</b>\n"
        f"🏁 علت بسته‌شدن: <b>{reason}</b>\n"
        f"💹 قیمت مشاهده‌شده: "
        f"<code>{format_price(current_price)}</code>\n"
        f"{icon} سود/زیان ناخالص فرضی: "
        f"<b>{pnl:+.2f} USDT</b>\n"
        "⚠️ کارمزد، لغزش قیمت و فاندینگ محاسبه نشده‌اند.\n"
        "🧪 PAPER ONLY — سفارش واقعی ثبت نشده است."
    )


# ============================================================
# PAPER TRADE MONITOR
# TP1 and TP2 send alerts only.
# The simulated position closes at SL or TP3.
# ============================================================

def reached_target(direction, price, target):
    if direction == "LONG":
        return price >= target

    return price <= target


def crossed_stop(direction, price, stop):
    if direction == "LONG":
        return price <= stop

    return price >= stop


def monitor_active_trades(state):
    active = state["active_trades"]
    changed = False

    for symbol in list(active.keys()):
        trade = active[symbol]

        try:
            current = get_current_price(symbol)

            if current is None:
                logging.warning("No current price for %s", symbol)
                continue

            if crossed_stop(
                trade["direction"],
                current,
                trade["stop"],
            ):
                pnl = -POSITION_USDT * STOP_PERCENT / 100

                telegram_send(
                    closed_message(
                        trade,
                        "STOP LOSS",
                        current,
                        pnl,
                    )
                )

                del active[symbol]
                changed = True
                continue

            targets = [
                ("TP1", trade["tp1"]),
                ("TP2", trade["tp2"]),
                ("TP3", trade["tp3"]),
            ]

            reached = set(
                trade.get("reached_targets", [])
            )

            for name, target_price in targets:
                if name in reached:
                    continue

                if reached_target(
                    trade["direction"],
                    current,
                    target_price,
                ):
                    telegram_send(
                        target_message(
                            trade,
                            name,
                            current,
                        )
                    )

                    reached.add(name)

                    trade["reached_targets"] = [
                        item
                        for item in ("TP1", "TP2", "TP3")
                        if item in reached
                    ]

                    changed = True

                    if name == "TP3":
                        pnl = (
                            POSITION_USDT
                            * TP3_PERCENT
                            / 100
                        )

                        telegram_send(
                            closed_message(
                                trade,
                                "TP3",
                                current,
                                pnl,
                            )
                        )

                        del active[symbol]
                        break

        except Exception as exc:
            logging.warning(
                "Monitoring failed for %s: %s",
                symbol,
                exc,
            )

    return changed


# ============================================================
# COOLDOWN AND DUPLICATE PREVENTION
# ============================================================

def is_in_cooldown(state, symbol):
    last = state["last_signal_at"].get(symbol)

    if last is None:
        return False

    try:
        return (
            now_ts() - float(last)
            < SIGNAL_COOLDOWN_HOURS * 3600
        )

    except (TypeError, ValueError):
        return False


# ============================================================
# CREATE NEW SIGNALS
# ============================================================

def create_new_signals(state, markets):
    candidates = []

    logging.info(
        "Scanning %s USDT markets.",
        len(markets),
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(analyze_market, market): market
            for market in markets
        }

        for future in as_completed(futures):
            try:
                signal = future.result()

                if not signal:
                    continue

                symbol = signal["symbol"]

                if symbol in state["active_trades"]:
                    continue

                if is_in_cooldown(state, symbol):
                    continue

                candidates.append(signal)

            except Exception as exc:
                logging.warning(
                    "Market scan error: %s",
                    exc,
                )

    candidates.sort(
        key=lambda item: (
            item["score"],
            item["consistency"],
            abs(item["change_pct"]),
        ),
        reverse=True,
    )

    selected = candidates[:MAX_SIGNALS_PER_RUN]

    for index, signal in enumerate(selected, start=1):
        symbol = signal["symbol"]

        state["active_trades"][symbol] = signal
        state["last_signal_at"][symbol] = now_ts()

        sent = telegram_send(
            signal_message(signal, index)
        )

        if not sent:
            logging.error(
                "Could not send signal notification for %s.",
                symbol,
            )

    return len(selected)


# ============================================================
# MAIN
# ============================================================

def main():
    if PAPER_MODE is not True:
        raise RuntimeError(
            "Safety stop: PAPER_MODE must remain True."
        )

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN secret."
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_CHAT_ID secret."
        )

    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logging.warning(
            "GitHub state persistence is not configured. "
            "State may be lost on a fresh runner."
        )

    logging.info("Starting ETH WHALE Bitpin paper bot.")

    logging.info(
        "Capital=%.2f USDT | leverage=%sx | notional=%.2f USDT",
        CAPITAL_USDT,
        LEVERAGE,
        POSITION_USDT,
    )

    state, state_sha = load_state()

    markets = get_usdt_markets()

    if not markets:
        raise RuntimeError(
            "No USDT markets found. "
            "Check the Bitpin market API response."
        )

    logging.info(
        "USDT markets found: %s",
        len(markets),
    )

    monitor_active_trades(state)

    new_signals = create_new_signals(
        state,
        markets,
    )

    save_state(
        state,
        existing_sha=state_sha,
    )

    logging.info(
        "Finished. New signals=%s | active paper trades=%s | "
        "real orders=OFF.",
        new_signals,
        len(state["active_trades"]),
    )


if __name__ == "__main__":
    try:
        main()

    except Exception:
        logging.exception("Bot stopped due to an error.")
        raise
