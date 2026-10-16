
def get_bitpin_tickers():
    endpoints = [
        "https://api.bitpin.org/v1/mkt/tickers/",
        "https://api.bitpin.ir/v1/mkt/tickers/",
        "https://api.bitpin.org/api/v1/mkt/tickers/",
        "https://api.bitpin.ir/api/v1/mkt/tickers/",
    ]

    errors = []

    for url in endpoints:
        try:
            data = get_json(url)

            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get(
                    "tickers",
                    data.get("results", data.get("data", []))
                )

                if isinstance(rows, dict):
                    rows = list(rows.values())

            else:
                rows = []

            result = {}

            for row in rows:
                if not isinstance(row, dict):
                    continue

                symbol = str(
                    row.get("symbol")
                    or row.get("code")
                    or ""
                ).upper().replace("-", "_")

                price = (
                    row.get("last")
                    or row.get("last_price")
                    or row.get("price")
                    or row.get("close")
                )

                try:
                    price = float(price)

                    if symbol and price > 0:
                        result[symbol] = {
                            "price": price,
                            "volume": safe_float(
                                row.get("quote_volume")
                                or row.get("volume")
                                or row.get("value")
                            ),
                        }
                except (TypeError, ValueError):
                    continue

            if result:
                print(
                    "Bitpin ticker API connected:",
                    url,
                    "| tickers:",
                    len(result)
                )
                return result

            errors.append(url + " -> no usable ticker data")

        except Exception as exc:
            errors.append(url + " -> " + str(exc)[:180])

    raise RuntimeError(
        "All Bitpin ticker endpoints failed:\n"
        + "\n".join(errors)
    )
