
# ============================================================
# PART 2 - BITPIN MARKETS AND TICKERS
# ============================================================

def unwrap_data(data):
    """Extract list-like data from common API response formats."""
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("results", "data", "tickers", "markets",
                    "pairs", "list", "result"):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in ("results", "data", "list"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return nested

        # Some ticker endpoints return a dictionary keyed by symbol.
        if data and all(isinstance(v, dict) for v in data.values()):
            return [
                dict(value, symbol=value.get("symbol", key))
                for key, value in data.items()
            ]

    return []


def get_markets():
    """Get available markets using a public endpoint."""
    endpoints = [
        "/api/v1/mkt/markets/",
        "/api/v1/market/markets/",
    ]

    for path in endpoints:
        try:
            data = get_json(BITPIN_BASE + path)
            items = unwrap_data(data)

            if items:
                logger.info(
                    "Markets endpoint worked: %s (%s items)",
                    path, len(items)
                )
                return items

            logger.warning(
                "Markets endpoint returned no usable items: %s",
                path
            )

        except Exception as exc:
            logger.warning(
                "Markets endpoint failed: %s | %s",
                path, type(exc).__name__
            )

    logger.error(
        "Could not identify a working markets endpoint."
    )
    return []


def normalize_symbol(value):
    """Normalize common market symbol representations."""
    if not value:
        return ""

    symbol = str(value).upper().strip()
    symbol = symbol.replace("/", "_").replace("-", "_")

    return symbol


def is_usdt_market(symbol):
    """Accept common USDT quote-symbol formats."""
    symbol = normalize_symbol(symbol)

    return (
        symbol.endswith("_USDT")
        or symbol.endswith("USDT")
    )


def get_market_symbol(item):
    """Read a symbol from a market object."""
    if isinstance(item, str):
        return normalize_symbol(item)

    if not isinstance(item, dict):
        return ""

    market = (
        item.get("symbol")
        or item.get("code")
        or item.get("name")
        or item.get("market")
        or item.get("pair")
        or ""
    )

    return normalize_symbol(market)


def get_tickers():
    """Retrieve public ticker data."""
    endpoints = [
        "/api/v1/mkt/tickers/",
        "/api/v1/mkt/ticker/",
    ]

    for path in endpoints:
        try:
            data = get_json(BITPIN_BASE + path)
            items = unwrap_data(data)

            if items:
                logger.info(
                    "Ticker endpoint worked: %s (%s items)",
                    path, len(items)
                )
                return items

            logger.warning(
                "Ticker response had no recognized data: %s",
                path
            )

        except Exception as exc:
            logger.warning(
                "Ticker endpoint failed: %s | %s",
                path, type(exc).__name__
            )

    logger.error("Could not retrieve ticker data.")
    return []


def get_ticker_price(item):
    """Read a last-traded price from common ticker fields."""
    if not isinstance(item, dict):
        return 0.0

    for key in (
        "price", "last", "last_price", "lastPrice",
        "close", "last_traded_price"
    ):
        value = item.get(key)

        try:
            price = float(value)
            if price > 0:
                return price
        except (TypeError, ValueError):
            continue

    return 0.0


def build_valid_market_list(markets, tickers):
    """Keep markets with a matching ticker and valid price."""
    ticker_map = {}

    for item in tickers:
        if not isinstance(item, dict):
            continue

        symbol = get_market_symbol(item)

        if symbol:
            ticker_map[symbol] = item

    valid = []
    seen = set()

    for market in markets:
        symbol = get_market_symbol(market)

        if not symbol or not is_usdt_market(symbol):
            continue

        if symbol in seen:
            continue

        ticker = ticker_map.get(symbol)

        if ticker is None:
            # Try matching alternate separators and formatting.
            ticker = ticker_map.get(symbol.replace("_", ""))

        if ticker is None:
            continue

        price = get_ticker_price(ticker)

        if price <= 0:
            continue

        valid.append({
            "symbol": symbol,
            "price": price,
            "ticker": ticker,
        })

        seen.add(symbol)

    logger.info("Valid USDT markets with prices: %s", len(valid))

    return valid


# End of Part 2
