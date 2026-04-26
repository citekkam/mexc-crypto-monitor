"""
MEXC New Listings Scraper - v7
Browser intercepts new_coin_calendar API, parses all known field names.
"""

import os
import requests
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

MEXC_URL = "https://www.mexc.com/newlisting"
TARGET_API = "new_coin_calendar"
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def fetch_listings() -> list[dict]:
    result = {"data": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        page = context.new_page()

        def on_response(response):
            if TARGET_API in response.url and result["data"] is None:
                try:
                    result["data"] = response.json()
                    print(f"[+] Captured: {response.url}")
                except Exception as e:
                    print(f"[!] Parse error: {e}")

        page.on("response", on_response)

        print(f"[*] Loading {MEXC_URL}...")
        try:
            page.goto(MEXC_URL, wait_until="domcontentloaded", timeout=45_000)
        except Exception as e:
            print(f"[!] goto: {e}")

        for i in range(20):
            if result["data"] is not None:
                print(f"[+] Got data after {i}s")
                break
            page.wait_for_timeout(1_000)
        else:
            print("[!] Timeout - new_coin_calendar never fired")

        browser.close()

    if not result["data"]:
        return []

    return parse_listings(result["data"])


def parse_listings(data: dict) -> list[dict]:
    now = datetime.now(tz=timezone.utc)
    listings = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            symbol = ""
            for k in ["symbol", "vcoinName", "coinName", "name", "currency", "baseAsset", "coin"]:
                v = node.get(k, "")
                if v and isinstance(v, str) and 1 < len(v) < 20:
                    symbol = v.upper().replace("USDT", "").replace("/", "").strip()
                    break

            listing_time = None
            for k in ["firstOpenTime", "openTime", "listingTime", "releaseTime",
                       "startTime", "tradingTime", "launchTime", "time", "onlineTime",
                       "tradeStartTime", "saleStartTime", "appointmentStartTime"]:
                v = node.get(k)
                if not v:
                    continue
                try:
                    ts = int(v)
                    if ts > 1_000_000_000:
                        listing_time = datetime.fromtimestamp(
                            ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
                        break
                except Exception:
                    pass

            if symbol and listing_time and listing_time > now:
                listings.append({
                    "symbol": symbol,
                    "listing_time": listing_time,
                    "listing_time_str": listing_time.strftime("%Y-%m-%d %H:%M UTC"),
                })

            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(data)
    return listings


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }, timeout=15)
    r.raise_for_status()


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
    print("MEXC New Listings Scraper v7")
    print("=" * 50)

    listings = fetch_listings()

    seen, unique = set(), []
    for item in listings:
        k = f"{item['symbol']}_{item['listing_time_str']}"
        if k not in seen:
            seen.add(k)
            unique.append(item)

    print(f"\n[+] Found {len(unique)} upcoming listings:")
    for item in unique:
        print(f"    • {item['symbol']} – {item['listing_time_str']}")

    send_telegram(format_message(unique))
    print("✅ Done!")


if __name__ == "__main__":
    main()
