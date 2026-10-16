
import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# BITPIN PAPER SIGNAL BOT
# Trade-flow monitoring only; not candle-based.
# REAL ORDERS: DISABLED
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
TP1_PERCENT = 0.80
TP2_PERCENT = 1.60
TP3_PERCENT = 2.40

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

session = requests.Session()
session.headers.update({
    "User-Agent": "Bitpin-Paper-Signal-Bot/1.0"
})


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_json(url, params=None):
    response = session.get(
        url, params=params, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def get_markets():
    url = MARKET_BASE + "/v1/mkt/markets/"
    data = get_json(url, {"page": 1})

    if isinstance(data, dict):
        markets = data.get("results", [])
    elif isinstance(data, list):
        markets = data
    else:
        markets = []

    selected = []

    for market in markets:
        code = str(market.get("code", "")).upper()

        if not code.endswith("_USDT"):
            continue
        if market.get("tradable") is False:
            continue
        if market.get("suspended") is True:
            continue

        volume = number(market.get("volume_24h"))

        selected.append({
            "code": code,
            "volume": volume,
            "name": market.get("title", code),
            "id": market.get("id"),
        })

    selected.sort(
        key=lambda item: item["volume"],
        reverse=True
    )
    return selected[:MAX_MARKETS]


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
            data.get("data", [])
        )

    if not isinstance(data, list):
        return []

    trades = []

    for item in data:
        price = number(item.get("price"))
        timestamp = number(item.get("time"), -1)

        if price > 0:
            trades.append({
                "price": price,
                "time": timestamp,
            })

    if all(t["time"] >= 0 for t in trades):
        trades.sort(key=lambda t: t["time"])

    return trades


def analyze_trades(trades):
    if len(trades) < MIN_TRADES:
        return None

    # Use the most recent 30 trades.
    window = trades[-MIN_TRADES:]
    prices = [t["price"] for t in window]

    first_price = prices[0]
    last_price = prices[-1]

    if first_price <= 0 or last_price <= 0:
        return None

    move_pct = (
        (last_price - first_price)
        / first_price
    ) * 100

    changes = [
        prices[i] - prices[i - 1]
        for i in range(1, len(prices))
    ]
    nonzero = [x for x in changes if x != 0]

    if not nonzero:
        return None

    up_ratio = sum(x > 0 for x in nonzero) / len(nonzero)
    down_ratio = sum(x < 0 for x in nonzero) / len(nonzero)

    if (
        move_pct >= MIN_MOVE_PERCENT
        and up_ratio >= MIN_DIRECTIONAL_RATIO
    ):
        direction = "LONG"
        directional_ratio = up_ratio

    elif (
        move_pct <= -MIN_MOVE_PERCENT
        and down_ratio >= MIN_DIRECTIONAL_RATIO
    ):
        direction = "SHORT"
        directional_ratio = down_ratio

    else:
        return None

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
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "move_pct": move_pct,
        "directional_ratio": directional_ratio,
        "trade_count": len(window),
    }


def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:.5f}"
    return f"{price:.8f}".rstrip("0").rstrip(".")


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("TELEGRAM NOT CONFIGURED; alert printed only.")
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
        print("TELEGRAM HTTP:", response.status_code)
        response.raise_for_status()
        return True

    except requests.RequestException as error:
        print("TELEGRAM ERROR:", str(error)[:300])
        return False


def make_message(symbol, signal):
    direction = signal["direction"]

    # Gross estimates based on full simulated position notional.
    # Fees, slippage and funding are excluded.
    pnl1 = POSITION_USDT * TP1_PERCENT / 100
    pnl2 = POSITION_USDT * TP2_PERCENT / 100
    pnl3 = POSITION_USDT * TP3_PERCENT / 100
    pnl_stop = POSITION_USDT * STOP_PERCENT / 100

    return (
        "BITPIN PAPER SIGNAL\n"
        "Mode: PAPER ONLY - NO REAL ORDERS\n\n"
        f"Market: {symbol}\n"
        f"Direction: {direction}\n"
        "Signal type: Recent-trade momentum (experimental)\n"
        f"Entry reference: {format_price(signal['entry'])}\n"
        f"Stop reference: {format_price(signal['stop'])}\n"
        f"TP1: {format_price(signal['tp1'])}\n"
        f"TP2: {format_price(signal['tp2'])}\n"
        f"TP3: {format_price(signal['tp3'])}\n\n"
        f"Simulated capital: {CAPITAL_USDT:.2f} USDT\n"
        f"Simulated leverage: {LEVERAGE}x\n"
        f"Position notional: {POSITION_USDT:.2f} USDT\n"
        f"Approx. gross TP1: +{pnl1:.3f} USDT\n"
        f"Approx. gross TP2: +{pnl2:.3f} USDT\n"
        f"Approx. gross TP3: +{pnl3:.3f} USDT\n"
        f"Approx. gross stop loss: -{pnl_stop:.3f} USDT\n\n"
        f"Recent price change: {signal['move_pct']:.3f}%\n"
        f"Directional consistency: "
        f"{signal['directional_ratio'] * 100:.1f}%\n"
        f"Trades analyzed: {signal['trade_count']}\n\n"
        "IMPORTANT: This is not candle-based confirmation. "
        "Trade-flow signals can be noisy. "
        "Gross P/L excludes fees, slippage and funding."
    )


def main():
    print("=" * 55)
    print("BITPIN PAPER SIGNAL BOT")
    print("UTC:", datetime.now(timezone.utc).isoformat())
    print("REAL ORDERS: OFF")
    print("CAPITAL:", CAPITAL_USDT, "USDT")
    print("LEVERAGE:", LEVERAGE, "x")
    print("=" * 55)

    try:
        markets = get_markets()
    except Exception as error:
        print("MARKET FETCH FAILED:", repr(error)[:500])
        return

    print("USDT MARKETS SELECTED:", len(markets))

    if not markets:
        print("No eligible USDT markets found.")
        return

    alerts_sent = 0
    checked = 0

    for market in markets:
        symbol = market["code"]
        checked += 1

        try:
            trades = get_recent_trades(symbol)
            signal = analyze_trades(trades)

            print(
                f"{symbol}: trades={len(trades)}",
                "SIGNAL=" + signal["direction"]
                if signal else "WAIT"
            )

            if signal and alerts_sent < MAX_ALERTS:
                message = make_message(symbol, signal)
                print("\n" + message + "\n")
                send_telegram(message)
                alerts_sent += 1

        except Exception as error:
            print(
                symbol,
                "FETCH/ANALYSIS ERROR:",
                str(error)[:250]
            )

        # Keep requests spaced to reduce server load.
        time.sleep(0.25)

    print("=" * 55)
    print("MARKETS CHECKED:", checked)
    print("ALERTS GENERATED:", alerts_sent)
    print("MODE: PAPER ONLY")
    print("NO ORDERS WERE PLACED.")


if __name__ == "__main__":
    main()
