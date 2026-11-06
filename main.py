import os
import time
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

WALLET = "0xf2f6af4f27ec2dcf4072095ab804016e14cd5817"
API = "https://data-api.polymarket.com/v2/activity"
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
POLL_SECONDS = 2

seen = set()
initialized = False


def get_activity():
    params = urllib.parse.urlencode({
        "user": WALLET,
        "limit": 100
    })
    req = urllib.request.Request(
        API + "?" + params,
        headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.loads(response.read())

    rows = result.get("data", [])
    if isinstance(rows, dict):
        rows = rows.get("items", [])
    return rows if isinstance(rows, list) else []


def field(item, *names, default=""):
    for name in names:
        value = item.get(name)
        if value is not None:
            return value
    return default


def event_key(item):
    identity = field(item, "id", "activity_id")
    if identity:
        return str(identity)

    parts = [
        field(item, "transaction_hash", "transactionHash", "tx_hash"),
        field(item, "timestamp", "block_timestamp"),
        field(item, "type", "activity_type"),
        field(item, "asset", "token_id"),
        field(item, "side"),
        field(item, "price"),
        field(item, "size", "shares")
    ]
    return "|".join(map(str, parts))


def telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.loads(response.read())

    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message")


def describe(item):
    kind = str(field(item, "type", "activity_type",
                     default="UNKNOWN")).upper()
    side = str(field(item, "side", default="")).upper()

    timestamp = field(item, "timestamp", "block_timestamp")
    try:
        date = datetime.fromtimestamp(
            float(timestamp), timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OverflowError):
        date = "Timestamp unavailable"

    market = field(
        item, "title", "market", "market_title",
        default="Market unavailable"
    )
    outcome = field(item, "outcome", default="Unknown")
    price = field(item, "price", default=None)
    shares = field(item, "size", "shares", default=None)

    lines = [
        "GOPFAN2 PUBLIC ACTIVITY",
        f"Action: {kind} {side}".strip(),
        f"Market: {market}",
        f"Outcome: {outcome}",
        f"Time: {date}"
    ]

    if price is not None:
        lines.append(f"Price: {price}")

    if shares is not None:
        lines.append(f"Shares/quantity: {shares}")

    notional = field(item, "usdc_size", "usdcSize", default=None)

    if notional is not None:
        lines.append(f"Reported USDC value: {notional}")
    elif kind == "TRADE" and price is not None and shares is not None:
        try:
            lines.append(
                f"Approximate trade notional: "
                f"{float(price) * float(shares):.4f} USDC"
            )
        except (ValueError, TypeError):
            pass

    if kind in ("REDEEM", "REDEMPTION"):
        lines.append("Redemption is NOT automatically profit.")

    tx = field(
        item, "transaction_hash", "transactionHash", "tx_hash"
    )
    if tx:
        lines.append(f"Transaction: {tx}")

    lines.append(
        "Public observation only. Possible signal, not a trade recommendation."
    )
    lines.append("No orders executed.")

    return "\n".join(lines)


def main():
    global initialized

    telegram("gopfan2 monitor started. Public data only; no trading.")

    while True:
        try:
            rows = get_activity()

            if not initialized:
                for item in rows:
                    seen.add(event_key(item))
                initialized = True
                print(f"Initial baseline: {len(seen)} events")
            else:
                new_items = []
                for item in rows:
                    key = event_key(item)
                    if key not in seen:
                        seen.add(key)
                        new_items.append(item)

                for item in reversed(new_items):
                    telegram(describe(item))
                    print("New activity alert sent")

                if len(seen) > 10000:
                    seen.clear()
                    for item in rows:
                        seen.add(event_key(item))

        except Exception as error:
            print("Monitoring error:", str(error))

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
