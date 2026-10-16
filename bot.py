
# ============================================================
# 🐋 ETH WHALE — BITPIN SMART MARKET WATCH
# PAPER TRADING ONLY — NO REAL ORDERS
# PART 1/5: CONFIGURATION & CONNECTIONS
# ============================================================

import os
import time
import logging
from datetime import datetime, timezone

import requests

# -------------------- API SETTINGS --------------------------

BITPIN_BASE = "https://api.bitpin.org"
BINANCE_BASE = "https://api.binance.com"

# -------------------- TELEGRAM SETTINGS ---------------------

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

# -------------------- PAPER TRADING -------------------------

PAPER_MODE = True
REAL_ORDERS_ENABLED = False

CAPITAL_USDT = 48.0
LEVERAGE = 3
POSITION_VALUE_USDT = CAPITAL_USDT * LEVERAGE

# -------------------- MARKET SETTINGS -----------------------

MAX_MARKETS = 15
CANDLE_LIMIT = 100

TIMEFRAMES = {
    "15m": "15m",
    "1h": "1h",
}

EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14

MIN_SIGNAL_SCORE = 60
STRONG_SIGNAL_SCORE = 75

MIN_VOLUME_RATIO = 1.05

# -------------------- RISK SETTINGS -------------------------

STOP_LOSS_PERCENT = 1.5
TP1_PERCENT = 1.5
TP2_PERCENT = 3.0
TP3_PERCENT = 4.5

# -------------------- REQUEST SETTINGS ----------------------

REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.15

# -------------------- LOGGING -------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("ETH_WHALE")

# -------------------- HTTP SESSION --------------------------

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "ETH-WHALE-Paper-Bot/1.0",
    "Accept": "application/json",
})

# -------------------- SAFETY CHECK --------------------------

if REAL_ORDERS_ENABLED:
    raise RuntimeError(
        "Safety error: real trading must remain disabled."
    )

if not PAPER_MODE:
    raise RuntimeError(
        "Safety error: PAPER_MODE must remain True."
    )


def utc_now():
    """Return current UTC time as a readable string."""
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def http_get_json(url, params=None):
    """GET JSON safely; raise an error on HTTP/API failures."""
    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()
    return response.json()


def format_price(value):
    """Format a price without unnecessary trailing zeros."""
    try:
        return f"{float(value):,.8f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "N/A"


def format_usdt(value):
    """Format a USDT amount."""
    return f"{float(value):,.2f} USDT"
