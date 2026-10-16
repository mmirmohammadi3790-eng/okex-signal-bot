# ============================================================
# PART 3 - CANDLE DATA VALIDATION
# ============================================================

def extract_candle_rows(data):
    """
    Extract candle rows from common API response formats.
    This function does not assume a specific Bitpin endpoint.
    """
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    # Common response keys
    for key in (
        "results",
        "data",
        "candles",
        "klines",
        "history",
        "result",
        "items",
    ):
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            for nested_key in (
                "results",
                "data",
                "candles",
                "klines",
                "history",
                "items",
            ):
                nested = value.get(nested_key)

                if isinstance(nested, list):
                    return nested

    return []


def parse_candle(row):
    """
    Convert one candle into a standard dictionary:
    open, high, low, close, volume.
    """
    if isinstance(row, dict):
        aliases = {
            "open": ("open", "o"),
            "high": ("high", "h"),
            "low": ("low", "l"),
            "close": ("close", "c", "price"),
            "volume": ("volume", "v", "base_volume"),
        }

        result = {}

        for target, keys in aliases.items():
            value = None

            for key in keys:
                if row.get(key) is not None:
                    value = row[key]
                    break

            try:
                result[target] = float(value)
            except (TypeError, ValueError):
                return None

        result["timestamp"] = (
            row.get("timestamp")
            or row.get("time")
            or row.get("startTime")
            or row.get("t")
        )

    elif isinstance(row, (list, tuple)) and len(row) >= 5:
        # Common OHLCV layout:
        # [timestamp, open, high, low, close, volume]
        try:
            result = {
                "timestamp": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 else 0.0,
            }
        except (TypeError, ValueError):
            return None

    else:
        return None

    if any(
        result[key] <= 0
        for key in ("open", "high", "low", "close")
    ):
        return None

    if result["high"] < result["low"]:
        return None

    if result["volume"] < 0:
        return None

    return result


def validate_candles(data, minimum=60):
    """
    Return normalized candles only if enough valid data exists.
    """
    rows = extract_candle_rows(data)
    candles = []

    for row in rows:
        candle = parse_candle(row)

        if candle is not None:
            candles.append(candle)

    # Keep original chronological order when possible.
    # Most APIs return oldest first, but we avoid guessing
    # based on timestamps that may have different formats.
    if len(candles) < minimum:
        logger.warning(
            "Not enough valid candles: received=%s required=%s",
            len(candles),
            minimum,
        )
        return []

    logger.info(
        "Valid candle data: %s candles",
        len(candles),
    )

    return candles


# End of Part 3
