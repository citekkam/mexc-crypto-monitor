"""
MEXC New Listings Scraper - v5
Strategy: launch browser, intercept new_coin_calendar API response, exit immediately.
No DOM scraping, no waiting for full page load - done in ~15s.
"""

import os
import time
import requests
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

MEXC_URL = "https://www.mexc.com/newlisting"
TARGET_API = "new_coin_calendar"
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def fetch_listings() -> list[dict]:
    result = {"data": None}  # shared state for the response handler

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        page = context.new_page()

        # Intercept the exact API call we need
        def on_response(response):
            if TARGET_API in response.url and result["data"] is None:
                try:
                    body = response.json()
                    print(f"[+] Captured: {response.url[:100]}")
                    result["data"] = body
                except Exception as e:
                    print(f"[!] Failed to parse response: {e}")

        page.on("response", on_response)

        print(f"[*] Loading {MEXC_URL} ...")
        try:
            page.goto(MEXC_URL, wait_until="domcontentloaded", timeout=45_000)
        except Exception as e:
            print(f"[!] goto error (continuing): {e}")

        # Wait up to 20s for our specific API call to fire
        print("[*] Waiting for new_coin_calendar API call...")
        for i in range(20):
            if result["data"] is not None:
                print(f"[+] Got data after {i}s")
                break
            page.wait_for_timeout(1_000)
        else:
            print("[!] Timed out waiting for new_coin_calendar")

        browser.close()

    if not result["data"]:
        return []

    return parse_calendar_data(result["data"])


def parse_calendar_data(data: dict) -> list[dict]:
    print(f"[*] Parsing response, top-level keys: {list(data.keys())}")
    raw = data.get("data", [])

    if isinstance(raw, dict):
        # Sometimes data is nested: {"list": [...], ...}
        raw = raw.get("list") or raw.get("items") or raw.get("data") or []

    if not raw:
        print(f"[!] No items in data. Full response: {str(data)[:500]}")
        return []

    print(f"[*] Found {len(raw)} raw items, first item keys: {list(raw[0].keys()) if raw else 'N/A'}")

    now = datetime.now(tz=timezone.utc)
    listings = []

    for item in raw:
        # Print first item fully for debugging
        if len(listings) == 0 and item == raw[0]:
            print(f"[DEBUG] First item: {item}")

        # Extract symbol
        symbol = ""
        for key in ["symbol", "vcoinName", "coinName", "name", "currency", "baseAsset"]:
            val = item.get(key, "")
            if val and isinstance(val, str) and 1 < len(val) < 20:
                symbol = val.upper().replace("USDT", "").replace("/", "").strip()
                break

        # Extract listing time
        listing_time = None
        for key in [
            "firstOpenTime", "openTime", "listingTime", "releaseTime",
            "startTime", "tradingTime", "launchTime", "time", "onlineTime",
        ]:
            val = item.get(key)
            if not val:
                continue
            try:
                ts = int(val)
                listing_time = datetime.fromtimestamp(
                    ts / 1000 if ts > 1e10 else ts, tz=timezone.utc
                )
                break
            except Exception:
                pass

        if symbol and listing_time and listing_time > now:
            listings.append({
                "symbol": symbol,
                "listing_time": listing_time,
                "listing_time_str": listing_time.strftime("%Y-%m-%d %H:%M UTC"),
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
        ct = f"{d}d {h}h {m}m" if d > 0 else f"{h}h {m}m" if h > 0 else f"{m}m"
        lines.append(
            f"\n{i}. <b>{item['symbol']}</b>\n"
            f"   🕐 {item['listing_time_str']}\n"
            f"   ⏳ In: {ct}"
        )
    lines += ["\n━━━━━━━━━━━━━━━━━━━━", f'🔗 <a href="{MEXC_URL}">MEXC New Listing</a>']
    return "\n".join(lines)


def main():
    print("=" * 50)
    print("MEXC New Listings Scraper v5")
    print("=" * 50)

    listings = fetch_listings()

    # Deduplicate
    seen, unique = set(), []
    for item in listings:
        k = f"{item['symbol']}_{item['listing_time_str']}"
        if k not in seen:
            seen.add(k)
            unique.append(item)

    print(f"\n[+] Found {len(unique)} upcoming listings:")
    for item in unique:
        print(f"    • {item['symbol']} – {item['listing_time_str']}")

    message = format_message(unique)
    print(f"\n[*] Sending Telegram...\n{message}\n")
    send_telegram(message)
    print("✅ Done!")


if __name__ == "__main__":
    main()
