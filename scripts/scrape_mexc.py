"""
MEXC New Listings Scraper - Final v4
Uses MEXC's own internal API: /api/operation/new_coin_calendar
No browser needed - fast, reliable, ~2s to run.
"""

import os
import time
import requests
from datetime import datetime, timezone

MEXC_URL = "https://www.mexc.com/newlisting"
CALENDAR_API = "https://www.mexc.com/api/operation/new_coin_calendar"
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.mexc.com/newlisting",
    "Origin": "https://www.mexc.com",
}


def fetch_listings() -> list[dict]:
    ts = int(time.time() * 1000)
    url = f"{CALENDAR_API}?timestamp={ts}"
    print(f"[*] Fetching: {url}")

    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    print(f"[*] Response code: {data.get('code')} | keys: {list(data.keys())}")

    raw = data.get("data", [])
    if not raw:
        print("[!] Empty data array in response")
        return []

    now = datetime.now(tz=timezone.utc)
    listings = []

    for item in raw:
        symbol = (
            item.get("symbol") or item.get("vcoinName") or
            item.get("coinName") or item.get("name") or ""
        ).upper().replace("USDT", "").strip()

        # Try all known time fields (ms timestamp)
        raw_time = (
            item.get("firstOpenTime") or item.get("openTime") or
            item.get("listingTime") or item.get("releaseTime") or
            item.get("startTime") or item.get("tradingTime") or
            item.get("time")
        )

        if not symbol or not raw_time:
            continue

        try:
            ts_val = int(raw_time)
            # MEXC returns ms timestamps
            listing_time = datetime.fromtimestamp(
                ts_val / 1000 if ts_val > 1e10 else ts_val,
                tz=timezone.utc
            )
        except Exception:
            continue

        if listing_time > now:
            listings.append({
                "symbol": symbol,
                "listing_time": listing_time,
                "listing_time_str": listing_time.strftime("%Y-%m-%d %H:%M UTC"),
                "raw": item,
            })

    return listings


def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)
    r.raise_for_status()
    return True


def format_message(listings: list[dict]) -> str:
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not listings:
        return (
            f"🪙 <b>MEXC New Listings</b>\n\n"
            f"📅 Scan: {now_str}\n"
            f"📭 No upcoming listings found.\n\n"
            f'🔗 <a href="{MEXC_URL}">Check manually</a>'
        )

    listings.sort(key=lambda x: x["listing_time"])
    now = datetime.now(tz=timezone.utc)

    lines = [
        "🪙 <b>MEXC New Listings</b>",
        f"📅 Scan: {now_str}",
        f"✅ Found: <b>{len(listings)} coins</b>",
        "", "━━━━━━━━━━━━━━━━━━━━",
    ]

    for i, item in enumerate(listings, 1):
        delta = item["listing_time"] - now
        d, rem = delta.days, delta.seconds
        h, m = rem // 3600, (rem % 3600) // 60
        countdown = (
            f"{d}d {h}h {m}m" if d > 0
            else f"{h}h {m}m" if h > 0
            else f"{m}m"
        )
        lines.append(
            f"\n{i}. <b>{item['symbol']}</b>\n"
            f"   🕐 {item['listing_time_str']}\n"
            f"   ⏳ In: {countdown}"
        )

    lines += ["\n━━━━━━━━━━━━━━━━━━━━", f'🔗 <a href="{MEXC_URL}">MEXC New Listing</a>']
    return "\n".join(lines)


def main():
    print("=" * 50)
    print("MEXC New Listings Scraper v4 (API direct)")
    print("=" * 50)

    listings = fetch_listings()

    print(f"\n[+] Found {len(listings)} upcoming listings:")
    for item in listings:
        print(f"    • {item['symbol']} – {item['listing_time_str']}")

    message = format_message(listings)
    print(f"\n[*] Sending Telegram...\n{message}\n")
    send_telegram(message)
    print("✅ Done!")


if __name__ == "__main__":
    main()
