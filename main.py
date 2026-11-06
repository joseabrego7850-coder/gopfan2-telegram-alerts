import os
import time
import json
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

WALLET = "0xf2f6af4f27ec2dcf4072095ab804016e14cd5817"
API = "https://data-api.polymarket.com/v2/activity"
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

POLL_SECONDS = 2
PAGE_SIZE = 1000
seen = set()
initialized = False


def get_activity(cursor=None):
    params = {"user": WALLET, "limit": PAGE_SIZE}
    if cursor:
        params["cursor"] = cursor

    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
    url,
    headers={
        "Accept": "application/json",
        "User-Agent": "gopfan2-public-monitor/1.0",
        "Origin": "https://polymarket.com",
        "Referer": "https://polymarket.com/"
    }
)

    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read())

    rows = result.get("data") or []
    pagination = result.get("pagination") or {}
    return rows, pagination.get("next_cursor")


def event_key(item):
    identity = item.get("id") or item.get("activity_id")
    if identity:
        return str(identity)

    tx = item.get("transaction_hash") or item.get("transactionHash") or ""
    sequence = item.get("sequence_id", "")
    if tx and sequence != "":
        return f"{tx}:{sequence}:{item.get('type', '')}"

    raw = json.dumps(item, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message[:3900]
    }).encode()

    req = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read())

    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message")


def describe(item):
    kind = str(item.get("type") or "UNKNOWN").upper()
    side = str(item.get("side") or "").upper()

    timestamp = item.get("timestamp")
    try:
        date = datetime.fromtimestamp(
            float(timestamp), timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OverflowError):
        date = "Timestamp unavailable"

    market = item.get("title") or item.get("market") or "Market unavailable"
    outcome = item.get("outcome") or "Unknown"
    price = item.get("price")
    shares = item.get("size")
    value = item.get("usdc_size")
    slug = item.get("slug")
    tx = item.get("transaction_hash") or item.get("transactionHash")

    lines = [
        "GOPFAN2 — PUBLIC ACTIVITY",
        f"Action: {kind}" + (f" / {side}" if side else ""),
        f"Market: {market}",
        f"Outcome: {outcome}",
        f"Time: {date}"
    ]

    if price is not None:
        lines.append(f"Price: {price}")
    if shares is not None:
        lines.append(f"Quantity: {shares}")
    if value is not None:
        lines.append(f"Reported USDC value: {value}")
    elif kind == "TRADE" and price is not None and shares is not None:
        try:
            lines.append(
                f"Approx. trade notional: {float(price) * float(shares):.4f} USDC"
            )
        except (ValueError, TypeError):
            pass

    if kind in ("REDEEM", "REDEMPTION"):
        lines.append("Note: redemption amount is not automatically profit.")

    if slug:
        lines.append(f"Market link: https://polymarket.com/event/{slug}")
    if tx:
        lines.append(f"Transaction: https://polygonscan.com/tx/{tx}")

    lines.append("Public observation only. No orders executed.")
    return "\n".join(lines)


def main():
    global initialized

    telegram("gopfan2 monitor started. Public data only. No trading.")
    print("Monitor started.")

    while True:
        try:
            cursor = None
            new_items = []

            while True:
                rows, next_cursor = get_activity(cursor)

                if not initialized:
                    for item in rows:
                        seen.add(event_key(item))
                    initialized = True
                    print(f"Initial baseline: {len(seen)} events")
                    break

                found_known = False

                for item in rows:
                    key = event_key(item)
                    if key in seen:
                        found_known = True
                    else:
                        seen.add(key)
                        new_items.append(item)

                if found_known or not next_cursor:
                    break

                cursor = next_cursor

            for item in reversed(new_items):
                telegram(describe(item))
                print("New activity alert sent.")

        except urllib.error.HTTPError as error:
            delay = error.headers.get("Retry-After", "10")
            try:
                delay = max(float(delay), POLL_SECONDS)
            except ValueError:
                delay = 10
            body = error.read().decode("utf-8", "replace")[:1000]
            trace_id = error.headers.get("x-trace-id") or error.headers.get("cf-ray") or "unavailable"
            print(f"API/HTTP error {error.code}; trace={trace_id}; body={body}; retrying in {delay}s")
            time.sleep(delay)

        except Exception as error:
            print("Monitoring error:", str(error))

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
