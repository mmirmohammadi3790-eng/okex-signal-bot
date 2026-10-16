
def get_candles(symbol, timeframe):
    """
    Diagnostic candle fetcher.
    Logs HTTP status and response body.
    Never creates synthetic candles.
    """

    api_symbol = normalize_symbol(symbol)
    interval = {
        "15m": "15m",
        "1h": "1h",
    }.get(timeframe, timeframe)

    if not api_symbol:
        log.error("Invalid candle symbol: %s", symbol)
        return []

    candidates = [
        (
            f"{BASE_URL}/api/v1/mkt/ohlcv/{api_symbol}/",
            {"interval": interval, "limit": CANDLE_LIMIT},
        ),
        (
            f"{BASE_URL}/api/v1/mkt/ohlcv/",
            {"symbol": api_symbol, "interval": interval,
             "limit": CANDLE_LIMIT},
        ),
        (
            f"{BASE_URL}/api/v1/mkt/candles/{api_symbol}/",
            {"interval": interval, "limit": CANDLE_LIMIT},
        ),
        (
            f"{BASE_URL}/api/v1/mkt/candles/",
            {"symbol": api_symbol, "interval": interval,
             "limit": CANDLE_LIMIT},
        ),
    ]

    for attempt, (url, params) in enumerate(candidates, start=1):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=8,
            )

            log.info(
                "CANDLE DEBUG | symbol=%s timeframe=%s "
                "attempt=%d status=%d url=%s",
                api_symbol,
                timeframe,
                attempt,
                response.status_code,
                response.url,
            )

            if response.status_code != 200:
                log.warning(
                    "CANDLE HTTP ERROR | status=%d body=%s",
                    response.status_code,
                    response.text[:350].replace("\n", " "),
                )
                continue

            try:
                payload = response.json()
            except ValueError:
                log.warning(
                    "CANDLE INVALID JSON | body=%s",
                    response.text[:350].replace("\n", " "),
                )
                continue

            candles = normalize_candles(payload)

            if len(candles) >= MIN_CANDLES:
                log.info(
                    "CANDLE SUCCESS | %s %s | count=%d",
                    api_symbol,
                    timeframe,
                    len(candles),
                )
                return candles[-CANDLE_LIMIT:]

            if isinstance(payload, dict):
                log.warning(
                    "CANDLE DATA SHAPE | keys=%s | "
                    "parsed=%d | body=%s",
                    list(payload.keys())[:20],
                    len(candles),
                    str(payload)[:350],
                )
            else:
                log.warning(
                    "CANDLE DATA SHAPE | type=%s | "
                    "parsed=%d | sample=%s",
                    type(payload).__name__,
                    len(candles),
                    str(payload)[:350],
                )

        except requests.RequestException as exc:
            log.warning(
                "CANDLE REQUEST ERROR | %s %s | %s",
                api_symbol,
                timeframe,
                str(exc)[:250],
            )

        time.sleep(0.1)

    log.error(
        "CANDLE FAILED | symbol=%s timeframe=%s",
        api_symbol,
        timeframe,
    )
    return []
