import requests
import json
import os
from datetime import datetime

BASE = "https://sapi.ok-ex.io"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

def telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": msg
            },
            timeout=20
        )

        print("Telegram:", r.status_code)
        print(r.text[:500])

    except Exception as e:
        print("Telegram error:", repr(e))


def test_candles(symbol):

    url = BASE + "/api/v1/spot/public/candles"

    params = {
        "symbol": symbol,
        "interval": "1h",
        "limit": 10
    }

    print("\n" + "=" * 80)
    print("CANDLE TEST")
    print("=" * 80)

    print("URL:")
    print(url)

    print("\nPARAMS:")
    print(params)

    try:

        r = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=30
        )

        print("\nHTTP STATUS:")
        print(r.status_code)

        print("\nFINAL URL:")
        print(r.url)

        print("\nCONTENT TYPE:")
        print(r.headers.get("content-type"))

        print("\nRAW RESPONSE:")
        print(r.text[:5000])

        print("\n" + "=" * 80)

        try:

            data = r.json()

            print("JSON TYPE:")
            print(type(data))

            print("\nJSON STRUCTURE:")

            if isinstance(data, dict):

                print(
                    "DICT KEYS:",
                    list(data.keys())
                )

                for key, value in data.items():

                    print(
                        "\nKEY:",
                        key
                    )

                    print(
                        "TYPE:",
                        type(value)
                    )

                    if isinstance(
                        value,
                        list
                    ):

                        print(
                            "LIST LENGTH:",
                            len(value)
                        )

                        if value:

                            print(
                                "FIRST ROW:"
                            )

                            print(
                                json.dumps(
                                    value[0],
                                    ensure_ascii=False,
                                    indent=2
                                )
                            )

                    elif isinstance(
                        value,
                        dict
                    ):

                        print(
                            "DICT KEYS:",
                            list(value.keys())
                        )

                        print(
                            "VALUE SAMPLE:",
                            str(value)[:2000]
                        )

            elif isinstance(data, list):

                print(
                    "LIST LENGTH:",
                    len(data)
                )

                if data:

                    print(
                        "FIRST ROW:"
                    )

                    print(
                        json.dumps(
                            data[0],
                            ensure_ascii=False,
                            indent=2
                        )
                    )

            message = (
                "🧪 OK-EX CANDLE TEST\n\n"
                f"🪙 Symbol: {symbol}\n"
                f"📡 HTTP: {r.status_code}\n\n"
                "Raw response received.\n"
                "Check GitHub Actions log for exact candle structure."
            )

            telegram(message)

        except Exception as e:

            print(
                "\nJSON PARSE ERROR:",
                repr(e)
            )

    except Exception as e:

        print(
            "\nREQUEST ERROR:",
            repr(e)
        )


print("=" * 80)
print("OK-EX CANDLE DIAGNOSTIC")
print("=" * 80)

print(
    "TIME:",
    datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
)

test_candles("SOL-USDT")

print("\nTEST FINISHED")
