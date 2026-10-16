
import os
import json
import time
import base64
import requests
from datetime import datetime, timezone

# ============================================================
# BITPIN PAPER SIGNAL BOT V2
# PAPER ONLY - NO REAL EXCHANGE ORDERS
# ============================================================

MARKET_BASE = "https://api.bitpin.ir"
TRADE_BASE = "https://api.bitpin.market"
TIMEOUT = 15

CAPITAL_USDT = 48.0
LEVERAGE = 3
POSITION_USDT = CAPITAL_USDT * LEVERAGE

MAX_MARKETS = 12
MAX_ALERTS = 3
MIN_TRADES = 30
MIN_MOVE_PERCENT = 0.35
MIN_DIRECTIONAL_RATIO = 0.58

STOP_PERCENT = 0.80
TP_PERCENTAGES = [0.80, 1.60, 2.40]
COOLDOWN_HOURS = 6

STATE_FILE = "bot_state.json"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
GITHUB_BRANCH = os.getenv("GITHUB_REF_NAME", "main")

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-Paper-Signal-Bot/2.0"
})


def now():
    return int(time.time())


def number(value, default=0.0):
    try:
        if isinstance(value, dict):
            for key in ("price", "last", "value"):
                if key in value:
                    return float(value[key])
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_json(url, params=None):
    response = session.get(
        url, params=params, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("TELEGRAM CONFIGURATION MISSING")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = session.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        print("TELEGRAM: SENT")
        return True
    except requests.RequestException as error:
        print("TELEGRAM ERROR:", str(error)[:250])
        return False


def state_url():
    if not GITHUB_REPOSITORY or not GITHUB_TOKEN:
        return None

    return (
        "https://api.github.com/repos/"
        + GITHUB_REPOSITORY
        + "/contents/"
        + STATE_FILE
    )


def github_headers():
    return {
        "Authorization": "Bearer " + GITHUB_TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def empty_state():
    return {
        "last_alert": {},
        "active": [],
        "history": [],
    }


def load_state():
    url = state_url()

    if not url:
        print("STATE: no GitHub token; using temporary state")
        return empty_state(), None

    try:
        response = session.get(
            url,
            headers=github_headers(),
            params={"ref": GITHUB_BRANCH},
            timeout=TIMEOUT,
        )

        if response.status_code == 404:
            print("STATE: file not created yet")
            return empty_state(), None

        response.raise_for_status()
        item = response.json()

        raw = base64.b64decode(
            item["content"]
        ).decode("utf-8")

        state = json.loads(raw)
        state.setdefault("last_alert", {})
        state.setdefault("active", [])
        state.setdefault("history", [])

        print("STATE: loaded from GitHub")
        return state, item["sha"]

    except Exception as error:
        print("STATE LOAD ERROR:", str(error)[:250])
        raise RuntimeError(
            "Could not load saved state; stopping to avoid duplicates."
        )


def save_state(state, sha):
    url = state_url()

    if not url:
        print("STATE NOT SAVED: GitHub token is missing")
        return False

    content = json.dumps(
        state, ensure_ascii=False, indent=2
    )
    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii")

    payload = {
        "message": "Update Bitpin paper signal state",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }

    if sha:
        payload["sha"] = sha

    try:
        response = session.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        print("STATE: saved to GitHub")
        return True

    except Exception as error:
        print("STATE SAVE ERROR:", str(error)[:350])
        return False


def get_markets():
    data = get_json(
        MARKET_BASE + "/v1/mkt/markets/",
        {"page": 1},
    )

    if isinstance(data, dict):
        items = data.get("results", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []

    markets = []

    for item in items:
        symbol = str(item.get("code", "")).upper()

        if not symbol.endswith("_USDT"):
            continue
        if item.get("tradable") is False:
            continue
        if item.get("suspended") is True:
            continue

        markets.append({
            "symbol": symbol,
            "volume": number(item.get("volume_24h")),
            "market_price": number(item.get("price")),
        })

    markets.sort(
        key=lambda item: item["volume"],
        reverse=True,
    )

    return markets[:MAX_MARKETS]


def get_recent_trades(symbol):
    url = (
        TRADE_BASE
        + "/api/v1/mth/matches/"
        + symbol
        + "/"
    )

    data = get_json(url)

    if isinstance(data, dict):
        data = data.get(
            "results",
            data.get("data", []),
        )

    if not isinstance(data, list):
        return []

    trades = []

    for item in data:
        price = number(item.get("price"))
        stamp = number(item.get("time"), -1)

        if price > 0:
            trades.append({
                "price": price,
                "time": stamp,
            })

    if trades and all(t["time"] >= 0 for t in trades):
        trades.sort(key=lambda item: item["time"])

    return trades


def analyze_trades(trades):
    if len(trades) < MIN_TRADES:
        return None

    window = trades[-MIN_TRADES:]
    prices = [item["price"] for item in window]

    first_price = prices[0]
    last_price = prices[-1]

    if first_price <= 0 or last_price <= 0:
        return None

    move_pct = (
        (last_price - first_price) / first_price
    ) * 100

    changes = [
        prices[i] - prices[i - 1]
        for i in range(1, len(prices))
    ]

    nonzero = [change for change in changes if change != 0]

    if not nonzero:
        return None

    up_ratio = sum(change > 0 for change in nonzero) / len(nonzero)
    down_ratio = sum(change < 0 for change in nonzero) / len(nonzero)

    if (
        move_pct >= MIN_MOVE_PERCENT
        and up_ratio >= MIN_DIRECTIONAL_RATIO
    ):
        direction = "LONG"
        ratio = up_ratio

    elif (
        move_pct <= -MIN_MOVE_PERCENT
        and down_ratio >= MIN_DIRECTIONAL_RATIO
    ):
        direction = "SHORT"
        ratio = down_ratio

    else:
        return None

    return {
        "direction": direction,
        "move_pct": move_pct,
        "ratio": ratio,
        "trade_count": len(window),
        "last_trade_price": last_price,
    }


def make_signal(symbol, analysis, current_price):
    # Use the most recent observed trade as the entry reference.
    entry = analysis["last_trade_price"]
    direction = analysis["direction"]

    if direction == "LONG":
        stop = entry * (1 - STOP_PERCENT / 100)
        targets = [
            entry * (1 + pct / 100)
            for pct in TP_PERCENTAGES
        ]
    else:
        stop = entry * (1 + STOP_PERCENT / 100)
        targets = [
            entry * (1 - pct / 100)
            for pct in TP_PERCENTAGES
        ]

    return {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "current_price": current_price,
        "stop": stop,
        "targets": targets,
        "move_pct": analysis["move_pct"],
        "ratio": analysis["ratio"],
        "trade_count": analysis["trade_count"],
        "created_at": now(),
        "status": "OPEN",
        "highest_tp": 0,
    }


def fmt_price(price):
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:.6f}".rstrip("0").rstrip(".")
    return f"{price:.10f}".rstrip("0").rstrip(".")


def signal_message(signal):
    tp1, tp2, tp3 = signal["targets"]

    pnl1 = POSITION_USDT * TP_PERCENTAGES[0] / 100
    pnl2 = POSITION_USDT * TP_PERCENTAGES[1] / 100
    pnl3 = POSITION_USDT * TP_PERCENTAGES[2] / 100
    loss = POSITION_USDT * STOP_PERCENT / 100

    return (
        "BITPIN PAPER SIGNAL\n"
        "REAL ORDERS: OFF\n\n"
        f"Market: {signal['symbol']}\n"
        f"Direction: {signal['direction']}\n"
        "Signal: Recent-trade momentum (experimental)\n"
        f"Observed price: {fmt_price(signal['current_price'])}\n"
        f"Entry reference: {fmt_price(signal['entry'])}\n"
        f"Stop reference: {fmt_price(signal['stop'])}\n"
        f"TP1: {fmt_price(tp1)}\n"
        f"TP2: {fmt_price(tp2)}\n"
        f"TP3: {fmt_price(tp3)}\n\n"
        f"Capital: {CAPITAL_USDT:.2f} USDT\n"
        f"Simulated leverage: {LEVERAGE}x\n"
        f"Position notional: {POSITION_USDT:.2f} USDT\n"
        f"Gross TP1 estimate: +{pnl1:.3f} USDT\n"
        f"Gross TP2 estimate: +{pnl2:.3f} USDT\n"
        f"Gross TP3 estimate: +{pnl3:.3f} USDT\n"
        f"Gross stop estimate: -{loss:.3f} USDT\n\n"
        f"Recent price change: {signal['move_pct']:.3f}%\n"
        f"Directional consistency: {signal['ratio']*100:.1f}%\n"
        f"Trades analyzed: {signal['trade_count']}\n\n"
        "Trade-flow only; no candle confirmation. "
        "P/L excludes fees, slippage and funding. "
        "No exchange orders were placed."
    )


def update_results(state, current_prices):
    remaining = []

    for signal in state["active"]:
        symbol = signal["symbol"]
        price = current_prices.get(symbol, 0)

        if price <= 0:
            remaining.append(signal)
            continue

        direction = signal["direction"]
        stop = signal["stop"]
        targets = signal["targets"]

        # Conservative rule: stop takes priority if both
        # stop and target levels are crossed between scans.
        stop_hit = (
            price <= stop if direction == "LONG"
            else price >= stop
        )

        if stop_hit:
            signal["status"] = "STOP_OBSERVED"
            signal["exit_price"] = price
            signal["closed_at"] = now()
            state["history"].append(signal)

            print(
                "RESULT:", symbol,
                "STOP OBSERVED at", fmt_price(price)
            )

            send_telegram(
                "PAPER RESULT - SIMULATED\n"
                f"Market: {symbol}\n"
                f"Direction: {direction}\n"
                "Stop level crossed by an observed trade price.\n"
                f"Observed price: {fmt_price(price)}\n"
                "No real order was executed."
            )
            continue

        reached = 0

        for index, target in enumerate(targets, start=1):
            target_hit = (
                price >= target if direction == "LONG"
                else price <= target
            )
            if target_hit:
                reached = index

        previous = signal.get("highest_tp", 0)

        if reached > previous:
            signal["highest_tp"] = reached

            print(
                "RESULT:", symbol,
                f"TP{reached} OBSERVED at",
                fmt_price(price),
            )

            send_telegram(
                "PAPER RESULT UPDATE - SIMULATED\n"
                f"Market: {symbol}\n"
                f"Direction: {direction}\n"
                f"TP{reached} level crossed.\n"
                f"Observed price: {fmt_price(price)}\n"
                "No real order was executed."
            )

        if reached >= 3:
            signal["status"] = "TP3_OBSERVED"
            signal["exit_price"] = price
            signal["closed_at"] = now()
            state["history"].append(signal)
            continue

        remaining.append(signal)

    state["active"] = remaining
    state["history"] = state["history"][-500:]


def main():
    print("=" * 55)
    print("BITPIN PAPER SIGNAL BOT V2")
    print("UTC:", datetime.now(timezone.utc).isoformat())
    print("REAL ORDERS: OFF")
    print("CAPITAL:", CAPITAL_USDT, "USDT")
    print("LEVERAGE:", LEVERAGE, "x")
    print("=" * 55)

    state, sha = load_state()

    try:
        markets = get_markets()
    except Exception as error:
        print("MARKET FETCH ERROR:", str(error)[:300])
        return

    print("MARKETS SELECTED:", len(markets))

    current_prices = {}
    candidates = []

    for market in markets:
        symbol = market["symbol"]

        try:
            trades = get_recent_trades(symbol)

            # Recent trade is the primary observed price.
            # Fall back to market-list price if no trades exist.
            last_trade_price = (
                trades[-1]["price"] if trades else 0
            )
            current_price = (
                last_trade_price or market["market_price"]
            )

            if current_price > 0:
                current_prices[symbol] = current_price

            analysis = analyze_trades(trades)

            print(
                f"{symbol}: price="
                f"{fmt_price(current_price) if current_price else 'N/A'}; "
                f"trades={len(trades)}; "
                f"{analysis['direction'] if analysis else 'WAIT'}"
            )

            candidates.append(
                (symbol, analysis, current_price)
            )

        except Exception as error:
            print(
                symbol,
                "FETCH ERROR:",
                str(error)[:200],
            )

        time.sleep(0.25)

    # Evaluate old signals using prices observed in this scan.
    update_results(state, current_prices)

    active_symbols = {
        item["symbol"] for item in state["active"]
    }
    alerts = 0

    for symbol, analysis, current_price in candidates:
        if not analysis or current_price <= 0:
            continue

        # Do not open another paper signal for a market
        # while its previous signal remains active.
        if symbol in active_symbols:
            print(symbol, "SKIP: signal already active")
            continue

        key = symbol + ":" + analysis["direction"]
        last_alert = int(state["last_alert"].get(key, 0))

        if now() - last_alert < COOLDOWN_HOURS * 3600:
            print(symbol, "SKIP: cooldown")
            continue

        signal = make_signal(
            symbol, analysis, current_price
        )

        # Persist signal and cooldown before sending the alert.
        state["active"].append(signal)
        state["last_alert"][key] = now()
        active_symbols.add(symbol)

        message = signal_message(signal)
        print("\n" + message + "\n")

        send_telegram(message)
        alerts += 1

        if alerts >= MAX_ALERTS:
            break

    saved = save_state(state, sha)

    print("=" * 55)
    print("MARKETS CHECKED:", len(candidates))
    print("NEW ALERTS:", alerts)
    print("ACTIVE SIGNALS:", len(state["active"]))
    print("RECORDED RESULTS:", len(state["history"]))
    print("STATE SAVED:", saved)
    print("REAL ORDERS: OFF")
    print("DONE")


if __name__ == "__main__":
    main()
