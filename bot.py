
# ============================================================
# ETH WHALE - BITPIN SMART MARKET WATCH
# PAPER TRADING ONLY - NO REAL ORDERS
# ============================================================

import os
import time
import logging
from datetime import datetime, timezone

import requests

# -------------------- CONFIGURATION -------------------------

BOT_NAME = "ETH WHALE"

BITPIN_BASE = "https://api.bitpin.ir"
TELEGRAM_API = "https://api.telegram.org"

# Paper trading configuration
PAPER_MODE = True
REAL_ORDERS_ENABLED = False

PAPER_CAPITAL = 48.0
LEVERAGE = 3
POSITION_MARGIN = PAPER_CAPITAL
POSITION_VALUE = POSITION_MARGIN * LEVERAGE

# Balanced signal filtering
MIN_SIGNAL_SCORE = 60
STRONG_SIGNAL_SCORE = 75

# Technical analysis
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14

TIMEFRAME_FAST = "15m"
TIMEFRAME_SLOW = "1h"

# Risk management
STOP_LOSS_ATR_MULTIPLIER = 1.5
TAKE_PROFIT_R_MULTIPLIERS = [1.0, 2.0, 3.0]

# Market scanning
MAX_MARKETS = 100
MAX_SIGNALS_PER_SCAN = 5
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 0.15

# Telegram credentials are configured in GitHub Secrets
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# -------------------- LOGGING --------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("ETH_WHALE")

# -------------------- HTTP SESSION ----------------------------

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "ETH-WHALE-PaperSignalBot/1.0",
    "Accept": "application/json",
})

# -------------------- SAFETY CHECK ----------------------------

if REAL_ORDERS_ENABLED:
    raise RuntimeError(
        "Safety stop: this bot must never place real orders."
    )

if not PAPER_MODE:
    raise RuntimeError(
        "Safety stop: paper trading mode must remain enabled."
    )


def now_utc():
    """Return current UTC time."""
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def log_status(message):
    """Write a status message to the log."""
    logger.info(message)


def get_json(url, params=None):
    """Perform a read-only HTTP GET request."""
    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def telegram_send(text):
    """Send a Telegram message if credentials are configured."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning(
            "Telegram credentials missing; message not sent."
        )
        return False

    url = (
        f"{TELEGRAM_API}/bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):
            logger.error("Telegram API returned an error.")
            return False

        return True

    except requests.RequestException as exc:
        logger.error("Telegram connection failed: %s", exc)
        return False


def format_price(value):
    """Format a price without unnecessary trailing zeros."""
    try:
        return f"{float(value):,.8f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


# End of Part 1
# Parts 2-5 will be added below this line.
