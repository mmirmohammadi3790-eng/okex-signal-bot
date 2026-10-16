
import os
import sys
import time
import logging
import requests
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# ETH WHALE | BITPIN SMART MARKET WATCH
# PAPER TRADING ONLY - NO REAL ORDERS
# ============================================================

BOT_NAME = "🐋 ETH WHALE"
BASE_URL = "https://api.bitpin.ir"

CAPITAL_USDT = 48.0
LEVERAGE = 3
MARGIN_PER_TRADE = 16.0
POSITION_VALUE = MARGIN_PER_TRADE * LEVERAGE

MAX_MARKETS = 220
MAX_SIGNALS = 3
MIN_SCORE = 60
STRONG_SCORE = 75

TIMEFRAMES = ("15m", "1h")
CANDLE_LIMIT = 100
MIN_QUOTE_VOLUME = 10000.0

PAPER_MODE = True
REAL_ORDERS_ENABLED = False

# Timeout: 30 seconds
REQUEST_TIMEOUT = 30

# Retry temporary connection failures.
RETRY_TOTAL = 2
RETRY_BACKOFF = 1.0

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "ETH-WHALE-PaperMarketWatch/1.1",
    "Accept": "application/json",
})

retry_config = Retry(
    total=RETRY_TOTAL,
    connect=RETRY_TOTAL,
    read=RETRY_TOTAL,
    backoff_factor=RETRY_BACKOFF,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    raise_on_status=False,
)

adapter = HTTPAdapter(max_retries=retry_config)

SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning(
            "Telegram credentials missing; message not sent."
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    try:
        response = SESSION.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            logging.error("Telegram API rejected the message.")
            return False

        logging.info("Telegram message sent successfully.")
        return True

    except Exception as exc:
        logging.error("Telegram error: %s", exc)
        return False


# ============================================================
# HTTP / API HELPERS
# ============================================================

def api_get(path, params=None):
    url = BASE_URL.rstrip("/") + "/" + path.lstrip("/")

    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()
    return response.json()


def extract_list(data, keys=()):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value

        for key in ("results", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def first_value(obj, *keys):
    if not isinstance(obj, dict):
        return None

    for key in keys:
        value = obj.get(key)

        if value is not None and value != "":
            return value

    return None


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(value):
    if not value:
        return ""

    return (
        str(value)
        .upper()
        .replace("/", "_")
        .replace("-", "_")
    )
