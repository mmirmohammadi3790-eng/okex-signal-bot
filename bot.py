import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# =========================================================
# OK-EX IRAN — PAPER FUTURES SIGNAL BOT
# =========================================================

BASE_URL = "https://sapi.ok-ex.io"

# سرمایه و مدیریت معامله
CAPITAL = 100.0
MARGIN = 20.0
LEVERAGE = 5
POSITION_VALUE = MARGIN * LEVERAGE

# تنظیمات
TIMEFRAME = "1h"
MAX_COINS = 10
MIN_SCORE = 75

# Telegram — از GitHub Secrets خوانده می‌شود
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials are missing.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        r = requests.post(url, data=data, timeout=20)
        print("Telegram:", r.status_code)
        return r.ok
    except Exception as e:
        print("Telegram error:", e)
        return False


# =========================================================
# GET TICKERS
# =========================================================

def get_tickers():
    url = f"{BASE_URL}/api/v1/spot/public/tickers"

    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()

        rows = data.get("res", data)

        if isinstance(rows, dict):
            rows = rows.get("data", rows.get("list", []))

        if not isinstance(rows, list):
            return []

        result = []

        for x in rows:
            try:
                symbol = str(
                    x.get("symbol")
                    or x.get("s")
                    or ""
                ).upper()

                if not symbol.endswith("-USDT"):
                    continue

                price = float(
                    x.get("last")
                    or x.get("lastPrice")
                    or x.get("close")
                    or 0
                )

                volume = float(
                    x.get("quoteVolume")
                    or x.get("turnover")
                    or x.get("amount")
                    or x.get("volume")
                    or 0
                )

                if price <= 0:
                    continue

                result.append({
                    "symbol": symbol,
                    "price": price,
                    "volume": volume
                })

            except Exception:
                continue

        result.sort(
            key=lambda z: z["volume"],
            reverse=True
        )

        return result[:MAX_COINS]

    except Exception as e:
       
