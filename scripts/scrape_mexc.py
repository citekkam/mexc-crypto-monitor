"""
MEXC New Listings Scraper - v8
- Intercepts new_coin_calendar via browser session
- Saves upcoming listings to data/pending_listings.json (committed to repo)
- Sends Telegram summary
"""

import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

MEXC_URL = "https://www.mexc.com/newlisting"
TARGET_API = "new_coin_calendar"
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
LISTINGS_FILE = Path("data/pending_listings.json")


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
                    "listing_time_ts": int(listing_time.timestamp()),
                    "listing_time_str": listing_time.strftime("%Y-%m-%d %H:%M UTC"),
                    "monitored": False,
                })

            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(data)

    # Deduplicate
    seen, unique = set(), []
    for item in listings:
        if item["symbol"] not in seen:
            seen.add(item["symbol"])
            unique.append(item)

    return unique


def save_listings(listings: list[dict]):
    """Merge new listings with existing ones in data/pending_listings.json."""
    LISTINGS_FILE.parent.mkdir(exist_ok=True)
    existing = []
    if LISTINGS_FILE.exists():
        try:
            existing = json.loads(LISTINGS_FILE.read_text())
        except Exception:
            pass

    existing_symbols = {e["symbol"] for e in existing}
    added = 0
    for item in listings:
        if item["symbol"] not in existing_symbols:
            existing.append(item)
            existing_symbols.add(item["symbol"])
            added += 1

    LISTINGS_FILE.write_text(json.dumps(existing, indent=2))
    print(f"[+] Saved {len(existing)} total listings ({added} new) to {LISTINGS_FILE}")
    return added


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
    now = datetime.now(tz=timezone.utc)
    listings_sorted = sorted(listings, key=lambda x: x["listing_time_ts"])
    lines = [
        "🪙 <b>MEXC New Listings</b>",
        f"📅 Scan: {now_str}",
        f"✅ Found: <b>{len(listings)} coins</b>",
        "", "━━━━━━━━━━━━━━━━━━━━",
    ]
    for i, item in enumerate(listings_sorted, 1):
        lt = datetime.fromtimestamp(item["listing_time_ts"], tz=timezone.utc)
        delta = lt - now
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
    print("MEXC New Listings Scraper v8")
    print("=" * 50)

    listings = fetch_listings()
    print(f"\n[+] Found {len(listings)} upcoming listings:")
    for item in listings:
        print(f"    • {item['symbol']} – {item['listing_time_str']}")

    save_listings(listings)
    send_telegram(format_message(listings))
    print("✅ Done!")


if __name__ == "__main__":
    main()
