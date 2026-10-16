
import os
import json
import time
import logging
from datetime import datetime, timezone

import requests
import pandas as pd

# ============================================================
# ETH WHALE V5.3
# Kraken public market data | Paper trading only
# NO REAL ORDERS | NO PRIVATE EXCHANGE API
# ============================================================

BOT_NAME = "🐋 ETH WHALE V5.3"
BASE_URL = "https://api.kraken.com/0/public"
HISTORY_FILE = "paper_history.json"

CAPITAL = 48.0
LEVERAGE = 3.0
MARGIN_PER_TRADE = 16.0
NOTIONAL_PER_TRADE = MARGIN_PER_TRADE * LEVERAGE

MAX_SIGNALS = 3
MAX_OPEN_TRADES = 3
MIN_TREND_STRENGTH = 55
MIN_SIGNAL_SCORE = 60

ATR_MULTIPLIER = 1.3
TARGET_R = 1.0
BACKTEST_HORIZON = 12
ROUND_TRIP_COST_PCT = 0.20
SLIPPAGE_PCT = 0.05
MIN_BACKTEST_TRADES = 20

MARKETS = [
    ("BTC", "XBTUSD"),
    ("ETH", "ETHUSD"),
    ("SOL", "SOLUSD"),
    ("XRP", "XRPUSD"),
    ("DOGE", "XDGUSD"),
    ("LINK", "LINKUSD"),
    ("ADA", "ADAUSD"),
    ("AVAX", "AVAXUSD"),
    ("LTC", "LTCUSD"),
    ("BCH", "BCHUSD"),
]

TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ETH-WHALE-PaperBot/5.3"})


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def telegram_send(message):
    token = (
        os.getenv("TELEGRAM_BOT_TOKEN")
        or os.getenv("TELEGRAM_TOKEN")
    )
    chat_id = (
        os.getenv("TELEGRAM_CHAT_ID")
        or os.getenv("CHAT_ID")
    )

    if not token or not chat_id:
        logging.warning("Telegram credentials are missing.")
        print(message)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        response = SESSION.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            logging.error("Telegram API returned ok=false.")
            return False

        return True

    except Exception as exc:
        logging.error("Telegram send failed: %s", exc)
        print(message)
        return False


def fetch_ohlc(pair, interval, retries=3):
    """Fetch public OHLC data. Kraken normally limits recent history."""
    last_error = "unknown error"

    for attempt in range(retries):
        try:
            response = SESSION.get(
                f"{BASE_URL}/OHLC",
                params={"pair": pair, "interval": interval},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()

            errors = payload.get("error", [])
            if errors:
                raise RuntimeError("; ".join(errors))

            result = payload.get("result", {})
            keys = [key for key in result.keys() if key != "last"]

            if not keys:
                raise RuntimeError("No OHLC data returned")

            rows = result[keys[0]]
            if not rows or len(rows) < 80:
                raise RuntimeError(
                    f"Insufficient candles: {len(rows) if rows else 0}"
                )

            df = pd.DataFrame(
                rows,
                columns=[
                    "time", "open", "high", "low", "close",
                    "vwap", "volume", "count"
                ],
            )

            for col in [
                "time", "open", "high", "low",
                "close", "volume", "count"
            ]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.dropna().drop_duplicates("time")
            df = df.sort_values("time").reset_index(drop=True)

            # The final OHLC candle can still be forming.
            # Exclude it to avoid using incomplete candle data.
            if len(df) > 2:
                df = df.iloc[:-1].reset_index(drop=True)

            if len(df) < 80:
                raise RuntimeError("Not enough closed candles")

            return df

        except Exception as exc:
            last_error = str(exc)
            logging.warning(
                "OHLC %s/%s attempt %s failed: %s",
                pair, interval, attempt + 1, exc
            )
            time.sleep(1.2 * (attempt + 1))

    raise RuntimeError(last_error)


def add_indicators(df):
    df = df.copy()

    df["ema20"] = df["close"].ewm(
        span=20, adjust=False
    ).mean()
    df["ema50"] = df["close"].ewm(
        span=50, adjust=False
    ).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50)

    previous_close = df["close"].shift(1)

    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - previous_close).abs()
    tr3 = (df["low"] - previous_close).abs()

    df["tr"] = pd.concat(
        [tr1, tr2, tr3], axis=1
    ).max(axis=1)

    df["atr"] = df["tr"].ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()

    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = (
        df["volume"] / df["vol_ma20"].replace(0, float("nan"))
    ).fillna(1.0)

    return df


def trend_direction(row):
    if row["ema20"] > row["ema50"]:
        return "LONG"
    if row["ema20"] < row["ema50"]:
        return "SHORT"
    return "WAIT"


def detect_breakout_retest(df, lookback=20):
    """
    Detect a prior breakout followed by a retest.
    Levels are calculated only from candles before the breakout.
    """
    if len(df) < lookback + 10:
        return None

    current = df.iloc[-1]
    recent = df.iloc[-7:-1]

    # Search for a breakout 1-6 closed candles before the current candle.
    for j in range(len(df) - 2, max(lookback, len(df) - 8), -1):
        prior = df.iloc[j - lookback:j]
        breakout = df.iloc[j]

        resistance = float(prior["high"].max())
        support = float(prior["low"].min())
        atr = float(breakout["atr"])

        if not pd.notna(atr) or atr <= 0:
            continue

        # A bullish breakout must close above the prior resistance.
        if breakout["close"] > resistance:
            # Current candle retests the old level and closes back above it.
            tolerance = max(atr * 0.30, breakout["close"] * 0.0005)
            retest = (
                current["low"] <= resistance + tolerance
                and current["close"] > resistance
            )
            if retest:
                return {
                    "side": "LONG",
                    "level": resistance,
                    "atr": float(current["atr"]),
                }

        # A bearish breakout must close below the prior support.
        if breakout["close"] < support:
            tolerance = max(atr * 0.30, breakout["close"] * 0.0005)
            retest = (
                current["high"] >= support - tolerance
                and current["close"] < support
            )
            if retest:
                return {
                    "side": "SHORT",
                    "level": support,
                    "atr": float(current["atr"]),
                }

    return None


def analyze_market(symbol, pair, frames):
    df15 = add_indicators(frames["15m"])
    df1h = add_indicators(frames["1h"])
    df4h = add_indicators(frames["4h"])

    r15 = df15.iloc[-1]
    r1h = df1h.iloc[-1]
    r4h = df4h.iloc[-1]

    trend15 = trend_direction(r15)
    trend1h = trend_direction(r1h)
    trend4h = trend_direction(r4h)

    breakout = detect_breakout_retest(df15)
    if breakout is None:
        return None, "شکست و پولبک معتبر پیدا نشد"

    side = breakout["side"]

    if trend1h != side:
        return None, "عدم تأیید روند یک‌ساعته"

    if trend4h not in (side, "WAIT"):
        return None, "تعارض روند چهار‌ساعته"

    price = float(r15["close"])
    atr = float(r15["atr"])
    rsi = float(r15["rsi"])
    volume_ratio = float(r15["vol_ratio"])

    if price <= 0 or atr <= 0:
        return None, "داده اندیکاتور نامعتبر"

    # Balanced scoring; this is a technical score, not win probability.
    score = 0
    score += 25 if trend1h == side else 0
    score += 20 if trend15 == side else 0
    score += 10 if trend4h == side else 0

    if side == "LONG":
        score += 15 if 50 <= rsi <= 70 else 0
        score += 10 if rsi < 78 else 0
    else:
        score += 15 if 30 <= rsi <= 50 else 0
        score += 10 if rsi > 22 else 0

    score += 10 if volume_ratio >= 1.10 else 0
    score += 10 if abs(price - breakout["level"]) <= atr * 0.60 else 0

    trend_strength = min(
        100,
        (25 if trend1h == side else 0)
        + (25 if trend15 == side else 0)
        + (20 if trend4h == side else 0)
        + (15 if abs(float(r1h["ema20"] - r1h["ema50"])) / price > 0.001 else 0)
        + (15 if volume_ratio >= 1.10 else 0),
    )

    if trend_strength < MIN_TREND_STRENGTH:
        return None, f"قدرت روند {trend_strength}/100"

    if score < MIN_SIGNAL_SCORE:
        return None, f"امتیاز سیگنال {score}/100"

    # Avoid chasing a move if price is too far from the retest level.
    distance_pct = abs(price - breakout["level"]) / price * 100
    if distance_pct > 0.45:
        return None, "قیمت بیش از حد از سطح پولبک فاصله دارد"

    stop_distance = atr * ATR_MULTIPLIER
    if stop_distance <= 0:
        return None, "فاصله حد ضرر نامعتبر"

    if side == "LONG":
        entry = price
        stop = entry - stop_distance
        target = entry + stop_distance * TARGET_R
    else:
        entry = price
        stop = entry + stop_distance
        target = entry - stop_distance * TARGET_R

    return {
        "symbol": symbol,
        "pair": pair,
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "score": int(score),
        "trend_strength": int(trend_strength),
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "atr": atr,
        "level": float(breakout["level"]),
        "signal_time": int(r15["time"]),
        "time": utc_now(),
        "status": "OPEN",
        "margin": MARGIN_PER_TRADE,
        "notional": NOTIONAL_PER_TRADE,
    }, None


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"trades": []}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"trades": []}
        if not isinstance(data.get("trades"), list):
            data["trades"] = []

        return data

    except Exception as exc:
        logging.warning("Could not read history: %s", exc)
        return {"trades": []}


def save_history(history):
    temp_file = HISTORY_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    os.replace(temp_file, HISTORY_FILE)


def signal_id(signal):
    return f'{signal["pair"]}-{signal["side"]}-{signal["signal_time"]}'


def add_paper_trade(history, signal):
    sid = signal_id(signal)

    if any(t.get("id") == sid for t in history["trades"]):
        return False

    open_trades = [
        t for t in history["trades"]
        if t.get("status") == "OPEN"
    ]

    if len(open_trades) >= MAX_OPEN_TRADES:
        return False

    if any(t.get("pair") == signal["pair"] for t in open_trades):
        return False

    trade = dict(signal)
    trade["id"] = sid
    trade["opened_at"] = utc_now()
    trade["closed_at"] = None
    trade["exit_price"] = None
    trade["pnl_usdt"] = None
    trade["exit_reason"] = None

    history["trades"].append(trade)
    return True


def update_open_trades(history, latest_frames):
    """
    Paper-only exit monitoring.
    If both stop and target fall inside the same candle, assume the stop
    was hit first (conservative handling).
    """
    changed = False

    for trade in history["trades"]:
        if trade.get("status") != "OPEN":
            continue

        symbol = trade.get("symbol")
        pair = trade.get("pair")

        if symbol not in latest_frames:
            continue

        df = latest_frames[symbol].get("15m")
        if df is None or df.empty:
            continue

        # Only candles later than the signal candle are eligible.
        candles = df[df["time"] > float(trade["signal_time"])]
        if candles.empty:
            continue

        side = trade["side"]
        entry = float(trade["entry"])
        stop = float(trade["stop"])
        target = float(trade["target"])
        notional = float(trade["notional"])
        qty = notional / entry

        exit_price = None
        exit_reason = None

        for _, candle in candles.iterrows():
            high = float(candle["high"])
            low = float(candle["low"])

            if side == "LONG":
                stop_hit = low <= stop
                target_hit = high >= target

                if stop_hit:
                    exit_price = stop
                    exit_reason = "SL"
                    break
                if target_hit:
                    exit_price = target
                    exit_reason = "TP1"
                    break

            else:
                stop_hit = high >= stop
                target_hit = low <= target

                if stop_hit:
                    exit_price = stop
                    exit_reason = "SL"
                    break
                if target_hit:
                    exit_price = target
                    exit_reason = "TP1"
                    break

        if exit_price is None:
            continue

        gross = (
            (exit_price - entry) * qty
            if side == "LONG"
            else (entry - exit_price) * qty
        )

        # Approximate round-trip fee plus slippage assumption.
        cost = notional * (
            ROUND_TRIP_COST_PCT + SLIPPAGE_PCT
        ) / 100.0

        net = gross - cost

        trade["status"] = "CLOSED"
        trade["closed_at"] = utc_now()
        trade["exit_price"] = exit_price
        trade["exit_reason"] = exit_reason
        trade["pnl_usdt"] = round(net, 4)
        changed = True

        telegram_send(
            f"{BOT_NAME}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📕 بسته‌شدن معامله آزمایشی\n"
            f"بازار: {symbol}\n"
            f"جهت: {side}\n"
            f"علت خروج: {exit_reason}\n"
            f"ورود: {entry:.8g}\n"
            f"خروج: {exit_price:.8g}\n"
            f"سود/زیان خالص فرضی: {net:+.4f} USDT\n"
            "🧪 Paper trading — سفارش واقعی ثبت نشده است."
        )

    return changed


def backtest_one_hour(df_raw):
    """
    Exploratory out-of-sample test:
    - chronological 70/30 split
    - signals use data available up to each signal candle
    - entry at the next candle open
    - stop-first if stop and target are both touched
    - estimated fees and slippage deducted

    This is a simplified test, not proof of future profitability.
    """
    if len(df_raw) < 220:
        return {
            "trades": 0, "wins": 0, "net": 0.0,
            "pf": None, "expectancy": None
        }

    df = add_indicators(df_raw).reset_index(drop=True)
    split = int(len(df) * 0.70)
    start = max(split, 100)
    results = []

    # Keep the test set separate from the earlier chronological segment.
    for i in range(start, len(df) - BACKTEST_HORIZON - 1):
        history = df.iloc[:i + 1].copy()
        sig = detect_breakout_retest(history)

        if sig is None:
            continue

        current = df.iloc[i]
        entry_candle = df.iloc[i + 1]
        entry = float(entry_candle["open"])
        atr = float(current["atr"])

        if entry <= 0 or atr <= 0:
            continue

        side = sig["side"]
        distance = atr * ATR_MULTIPLIER

        if side == "LONG":
            stop = entry - distance
            target = entry + distance * TARGET_R
        else:
            stop = entry + distance
            target = entry - distance * TARGET_R

        exit_price = None

        future = df.iloc[
            i + 1:i + 1 + BACKTEST_HORIZON
        ]

        for _, candle in future.iterrows():
            high = float(candle["high"])
            low = float(candle["low"])

            if side == "LONG":
                if low <= stop:
                    exit_price = stop
                    break
                if high >= target:
                    exit_price = target
                    break
            else:
                if high >= stop:
                    exit_price = stop
                    break
                if low <= target:
                    exit_price = target
                    break

        if exit_price is None:
            # Conservative time exit at the last candle close.
            exit_price = float(future.iloc[-1]["close"])

        qty = NOTIONAL_PER_TRADE / entry
        gross = (
            (exit_price - entry) * qty
            if side == "LONG"
            else (entry - exit_price) * qty
        )

        # Approximate round-trip cost; not a verified exchange fee quote.
        cost = NOTIONAL_PER_TRADE * (
            ROUND_TRIP_COST_PCT + SLIPPAGE_PCT
        ) / 100.0

        net = gross - cost
        results.append(net)

    if not results:
        return {
            "trades": 0, "wins": 0, "net": 0.0,
            "pf": None, "expectancy": None
        }

    wins = sum(1 for x in results if x > 0)
    gross_profit = sum(x for x in results if x > 0)
    gross_loss = abs(sum(x for x in results if x < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else None

    return {
        "trades": len(results),
        "wins": wins,
        "net": sum(results),
        "pf": pf,
        "expectancy": sum(results) / len(results),
    }


def build_report(candidates, rejects, errors, backtest, history):
    closed = [
        t for t in history["trades"]
        if t.get("status") == "CLOSED"
        and isinstance(t.get("pnl_usdt"), (int, float))
    ]
    opened = [
        t for t in history["trades"]
        if t.get("status") == "OPEN"
    ]

    actual_count = len(closed)
    actual_wins = sum(1 for t in closed if t["pnl_usdt"] > 0)
    actual_net = sum(t["pnl_usdt"] for t in closed)

    if actual_count:
        actual_wr = actual_wins / actual_count * 100
        actual_wr_text = f"{actual_wr:.1f}%"
    else:
        actual_wr_text = "هنوز داده کافی نیست (۰ معامله بسته‌شده)"

    lines = [
        BOT_NAME,
        "━━━━━━━━━━━━━━━━━━",
        "📊 گزارش بازار | PAPER ONLY",
        f"🕒 {utc_now()}",
        "🚫 سفارش واقعی: خاموش",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if candidates:
        lines.append(f"✅ سیگنال‌های واجد شرایط: {len(candidates)}")
        for s in candidates:
            lines.extend([
                "──────────────",
                f"{s['symbol']} | {s['side']}",
                f"ورود فرضی: {s['entry']:.8g}",
                f"حد ضرر: {s['stop']:.8g}",
                f"هدف TP1: {s['target']:.8g}",
                f"امتیاز سیگنال: {s['score']}/100",
                f"قدرت روند: {s['trend_strength']}/100",
                f"RSI 15m: {s['rsi']:.1f}",
                f"نسبت حجم: {s['volume_ratio']:.2f}x",
                "⚠️ امتیاز فنی، احتمال برد نیست.",
            ])
    else:
        lines.append("⚪ WAIT — سیگنال واجد شرایط پیدا نشد.")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        f"بازارهای بررسی‌شده: {len(MARKETS)}",
        f"خطاهای دریافت/تحلیل: {errors}",
    ])

    if rejects:
        lines.append("دلایل پرتکرار رد:")
        for reason, count in sorted(
            rejects.items(), key=lambda x: x[1], reverse=True
        )[:5]:
            lines.append(f"• {reason}: {count}")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        "🧪 بک‌تست اکتشافی ۱ساعته (بخش ارزیابی جدا):",
        f"معاملات: {backtest['trades']}",
    ])

    if backtest["trades"] > 0:
        wr = backtest["wins"] / backtest["trades"] * 100
        lines.append(f"نرخ برد بک‌تست: {wr:.1f}%")
        lines.append(f"سود/زیان خالص فرضی: {backtest['net']:+.4f} USDT")

        if backtest["expectancy"] is not None:
            lines.append(
                f"میانگین سود/زیان هر معامله: "
                f"{backtest['expectancy']:+.4f} USDT"
            )

        if backtest["pf"] is not None:
            lines.append(f"Profit Factor: {backtest['pf']:.2f}")
        else:
            lines.append("Profit Factor: قابل محاسبه نیست")
    else:
        lines.append("داده کافی برای بک‌تست وجود ندارد.")

    lines.extend([
        "⚠️ بک‌تست ساده است و سود آینده را تضمین نمی‌کند.",
        "━━━━━━━━━━━━━━━━━━",
        f"معاملات کاغذی بسته‌شده: {actual_count}",
        f"نرخ برد معاملات کاغذی: {actual_wr_text}",
        f"سود/زیان خالص ثبت‌شده: {actual_net:+.4f} USDT",
        f"معاملات باز آزمایشی: {len(opened)}",
        f"سرمایه پایه آزمایشی: {CAPITAL:.2f} USDT",
        f"مارجین فرضی هر معامله: {MARGIN_PER_TRADE:.2f} USDT",
        f"اهرم محاسباتی: {LEVERAGE:.1f}x",
        f"ارزش اسمی هر موقعیت: {NOTIONAL_PER_TRADE:.2f} USDT",
        f"هزینه فرضی رفت‌وبرگشت: {ROUND_TRIP_COST_PCT:.2f}%",
        f"لغزش فرضی: {SLIPPAGE_PCT:.2f}%",
        "🧪 همه معاملات فقط شبیه‌سازی هستند.",
    ])

    return "\n".join(lines)


def main():
    logging.info("Starting %s", BOT_NAME)

    frames_by_symbol = {}
    rejects = {}
    candidates = []
    errors = 0
    backtest_results = []

    for symbol, pair in MARKETS:
        try:
            frames = {}
            for name, interval in TIMEFRAMES.items():
                frames[name] = fetch_ohlc(pair, interval)
                time.sleep(0.25)

            frames_by_symbol[symbol] = frames

            signal, reason = analyze_market(symbol, pair, frames)

            if signal:
                candidates.append(signal)
            elif reason:
                rejects[reason] = rejects.get(reason, 0) + 1

            # One exploratory test per market; hourly candles only.
            try:
                test = backtest_one_hour(frames["1h"])
                if test["trades"] > 0:
                    backtest_results.append(test)
            except Exception as exc:
                logging.warning("Backtest failed for %s: %s", symbol, exc)

        except Exception as exc:
            errors += 1
            logging.error("Market %s failed: %s", symbol, exc)
            rejects["خطای دریافت/تحلیل"] = (
                rejects.get("خطای دریافت/تحلیل", 0) + 1
            )

    history = load_history()

    # Update existing paper trades using the newly fetched 15m candles.
    update_open_trades(history, frames_by_symbol)

    # Keep the highest-scoring signals only; do not force weak signals.
    candidates.sort(
        key=lambda s: (s["score"], s["trend_strength"]),
        reverse=True
    )

    added = 0
    for signal in candidates:
        if added >= MAX_SIGNALS:
            break
        if add_paper_trade(history, signal):
            added += 1

    save_history(history)

    # Pool test outcomes approximately by weighting each market's expectancy.
    # The displayed PF is computed from pooled gross approximations only when
    # data are available; this is still a limited recent-history test.
    total_test_trades = sum(x["trades"] for x in backtest_results)
    total_test_wins = sum(x["wins"] for x in backtest_results)
    total_test_net = sum(x["net"] for x in backtest_results)

    # Approximate pooled PF using each market's net result is not valid.
    # Do not present a fabricated aggregate PF.
    backtest = {
        "trades": total_test_trades,
        "wins": total_test_wins,
        "net": total_test_net,
        "pf": None,
        "expectancy": (
            total_test_net / total_test_trades
            if total_test_trades else None
        ),
    }

    report = build_report(
        candidates, rejects, errors, backtest, history
    )

    print(report)
    telegram_send(report)


if __name__ == "__main__":
    main()
