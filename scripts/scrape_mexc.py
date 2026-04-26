"""
MEXC New Listings Scraper - Fixed v2
Fixes:
  - networkidle timeout  domcontentloaded + manual wait
  - Bot detection  stealth Chromium args + realistic headers
  - API interception  captures MEXC's own XHR calls (most reliable)
"""

import os
import re
import json
import requests
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, Response


MEXC_URL = "https://www.mexc.com/newlisting"
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

API_KEYWORDS = [
    "new_listing", "newlisting", "new-listing",
    "upcomingList", "upcoming_list", "activity/query",
    "spot/listing", "listing/list", "operateactivity",
]


def scrape_listings() -> list[dict]:
    intercepted_data = []
    listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,900",
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
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        page = context.new_page()

        def handle_response(response: Response):
            url = response.url.lower()
            if any(kw in url for kw in API_KEYWORDS):
                try:
                    body = response.json()
                    print(f"[+] Intercepted API: {response.url[:120]}")
                    intercepted_data.append({"url": response.url, "body": body})
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"[*] Loading {MEXC_URL} ...")
        try:
            page.goto(MEXC_URL, wait_until="domcontentloaded", timeout=45_000)
        except Exception as e:
            print(f"[!] goto error (continuing): {e}")

        print("[*] Waiting for XHR calls...")
        page.wait_for_timeout(8_000)

        for _ in range(4):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(1500)

        page.wait_for_timeout(3_000)

        if intercepted_data:
            print(f"[+] Processing {len(intercepted_data)} intercepted responses...")
            for item in intercepted_data:
                listings.extend(extract_from_json(item["body"]))
        else:
            print("[!] No API calls intercepted, falling back to DOM...")

        if not listings:
            listings = extract_from_dom(page)

        if not listings:
            print("[!] DOM fallback failed, trying raw HTML...")
            listings = extract_from_html(page.content())

        browser.close()

    seen, unique = set(), []
    for item in listings:
        k = f"{item['symbol']}_{item['listing_time_str']}"
        if k not in seen:
            seen.add(k)
            unique.append(item)
    return unique


def extract_from_dom(page) -> list[dict]:
    listings = []
    selectors = [
        "[class*='listing-item']", "[class*='ProjectItem']",
        "[class*='project-item']", "[class*='newListing']",
        "[class*='NewListing'] > div", "[class*='listItem']", ".listing-card",
    ]
    for sel in selectors:
        try:
            items = page.query_selector_all(sel)
            if items:
                print(f"[+] DOM: {len(items)} items via '{sel}'")
                for item in items:
                    parsed = parse_listing_text(item.inner_text())
                    if parsed:
                        listings.append(parsed)
                if listings:
                    break
        except Exception:
            continue
    if not listings:
        try:
            listings = parse_raw_text(page.inner_text("body"))
        except Exception as e:
            print(f"[!] Body parse failed: {e}")
    return listings


def extract_from_html(html: str) -> list[dict]:
    for pattern in [
        r'"listing"\s*:\s*(\[.*?\])',
        r'"newListing"\s*:\s*(\[.*?\])',
        r'"upcomingListings"\s*:\s*(\[.*?\])',
        r'"data"\s*:\s*(\[.*?"symbol".*?\])',
    ]:
        for match in re.findall(pattern, html, re.DOTALL):
            try:
                data = json.loads(match)
                extracted = extract_from_json(data)
                if extracted:
                    return extracted
            except json.JSONDecodeError:
                continue
    return []


def extract_from_json(data) -> list[dict]:
    listings = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                parsed = try_parse_json_item(item)
                listings.append(parsed) if parsed else listings.extend(extract_from_json(item))
    elif isinstance(data, dict):
        for value in data.values():
            listings.extend(extract_from_json(value))
    return listings


def try_parse_json_item(item: dict) -> dict | None:
    symbol = next(
        (item[k].upper() for k in ["symbol","coinName","name","token","currency","vcoinName"]
         if k in item and isinstance(item[k], str)), None
    )
    if not symbol:
        return None
    listing_time = None
    for key in ["listingTime","listing_time","openTime","releaseTime","launchTime","time","startTime","tradingTime"]:
        val = item.get(key)
        if not val:
            continue
        if isinstance(val, (int, float)) and val > 1_000_000_000:
            ts = val / 1000 if val > 1e12 else val
            listing_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            break
        if isinstance(val, str) and len(val) > 8:
            try:
                from dateutil import parser as dp
                listing_time = dp.parse(val)
                if not listing_time.tzinfo:
                    listing_time = listing_time.replace(tzinfo=timezone.utc)
                break
            except Exception:
                pass
    if symbol and listing_time and listing_time > datetime.now(tz=timezone.utc):
        return {"symbol": symbol, "listing_time": listing_time,
                "listing_time_str": listing_time.strftime("%Y-%m-%d %H:%M UTC")}
    return None


def parse_listing_text(text: str) -> dict | None:
    tm = re.search(r'(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}(?::\d{2})?)', text)
    sm = re.search(r'\b([A-Z]{2,10})(?:/USDT|/BTC|/ETH)?\b', text)
    if tm and sm:
        try:
            from dateutil import parser as dp
            lt = dp.parse(tm.group(1)).replace(tzinfo=timezone.utc)
            if lt > datetime.now(tz=timezone.utc):
                return {"symbol": sm.group(1), "listing_time": lt,
                        "listing_time_str": lt.strftime("%Y-%m-%d %H:%M UTC")}
        except Exception:
            pass
    return None


def parse_raw_text(text: str) -> list[dict]:
    IGNORE = {"USDT","UTC","AM","PM","THE","FOR","AND","NEW","ALL","BTC","ETH","LIST","OPEN","SPOT","API"}
    listings, seen = [], set()
    for line in text.split("\n"):
        tm = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)', line)
        if not tm:
            continue
        coins = [s for s in re.findall(r'\b([A-Z]{2,10})\b', line) if s not in IGNORE and len(s) >= 3]
        if not coins:
            continue
        try:
            from dateutil import parser as dp
            lt = dp.parse(tm.group(1)).replace(tzinfo=timezone.utc)
            if lt > datetime.now(tz=timezone.utc):
                k = f"{coins[0]}_{lt.strftime('%Y-%m-%d %H:%M UTC')}"
                if k not in seen:
                    seen.add(k)
                    listings.append({"symbol": coins[0], "listing_time": lt,
                                     "listing_time_str": lt.strftime("%Y-%m-%d %H:%M UTC")})
        except Exception:
            continue
    return listings


def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                                      "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=15)
        r.raise_for_status()
        print("[+] Telegram message sent!")
        return True
    except requests.RequestException as e:
        print(f"[!] Telegram error: {e}")
        return False


def format_telegram_message(listings: list[dict]) -> str:
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not listings:
        return (f"🪙 <b>MEXC New Listings</b>\n\n📅 Scan: {now_str}\n"
                f'📭 No upcoming listings found.\n\n🔗 <a href="{MEXC_URL}">Check manually</a>')

    listings.sort(key=lambda x: x["listing_time"])
    now = datetime.now(tz=timezone.utc)
    lines = ["🪙 <b>MEXC New Listings</b>", f"📅 Scan: {now_str}",
             f"✅ Found: <b>{len(listings)} coins</b>", "", "━━━━━━━━━━━━━━━━━━━━"]
    for i, item in enumerate(listings, 1):
        delta = item["listing_time"] - now
        d, rem = delta.days, delta.seconds
        h, m = rem // 3600, (rem % 3600) // 60
        countdown = f"{d}d {h}h {m}m" if d > 0 else f"{h}h {m}m" if h > 0 else f"{m}m"
        lines.append(f"\n{i}. <b>{item['symbol']}</b>\n   🕐 {item['listing_time_str']}\n   ⏳ In: {countdown}")
    lines += ["\n━━━━━━━━━━━━━━━━━━━━", f'🔗 <a href="{MEXC_URL}">MEXC New Listing</a>']
    return "\n".join(lines)


def main():
    print("=" * 50)
    print("MEXC New Listings Scraper v2")
    print("=" * 50)
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID!")

    print("\n[*] Starting scraper...")
    listings = scrape_listings()
    print(f"\n[+] Found {len(listings)} upcoming listings:")
    for item in listings:
        print(f"    • {item['symbol']} – {item['listing_time_str']}")

    message = format_telegram_message(listings)
    print(f"\n[*] Sending Telegram notification...\n{message}\n")
    if not send_telegram_message(message):
        raise RuntimeError("Failed to send Telegram message!")
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
