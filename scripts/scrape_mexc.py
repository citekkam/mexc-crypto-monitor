"""
MEXC New Listings Scraper v3
- Logs ALL network requests so we can see exactly what MEXC calls
- Intercepts any JSON response that looks like listing data
- Falls back to direct MEXC public API
- Saves screenshot + HTML on failure for debugging
"""

import os
import re
import json
import base64
import requests
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, Response

MEXC_URL = "https://www.mexc.com/newlisting"
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ── Direct API attempts (tried before Playwright) ─────────────────────────────
DIRECT_API_URLS = [
    "https://www.mexc.com/api/operateactivity/api/v2/newlisting?pageNum=1&pageSize=50",
    "https://www.mexc.com/api/operateactivity/new/listing/query?pageNum=1&pageSize=50",
    "https://www.mexc.com/api/platform/spot/market-v2/web/new/listing?pageNum=1&pageSize=50",
    "https://www.mexc.com/api/operation/new_listing_v2/activity/query?pageNum=1&pageSize=50",
    "https://www.mexc.com/api/operation/new_listing/activity/query?pageNum=1&pageSize=50",
    "https://api.mexc.com/api/v3/defaultSymbols",
]

COMMON_HEADERS = {
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


# ─── Strategy 1: Direct API ───────────────────────────────────────────────────

def try_direct_api() -> list[dict]:
    """Try hitting MEXC's API directly without a browser."""
    listings = []
    for url in DIRECT_API_URLS:
        try:
            print(f"[*] Trying direct API: {url}")
            r = requests.get(url, headers=COMMON_HEADERS, timeout=15)
            print(f"    Status: {r.status_code}")
            if r.status_code == 200:
                try:
                    data = r.json()
                    print(f"    Response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    extracted = extract_from_json(data)
                    if extracted:
                        print(f"    [+] Found {len(extracted)} listings!")
                        listings.extend(extracted)
                except Exception as e:
                    print(f"    JSON parse error: {e} | Raw: {r.text[:200]}")
        except Exception as e:
            print(f"    Request failed: {e}")
    return listings


# ─── Strategy 2: Playwright with full network logging ────────────────────────

def scrape_with_playwright() -> list[dict]:
    all_responses = []   # (url, json_body) for every JSON response
    listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage", "--disable-gpu",
                "--window-size=1280,900",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=COMMON_HEADERS["User-Agent"],
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        page = context.new_page()

        # ── Log EVERY request URL ────────────────────────────────────────
        def on_request(request):
            if "mexc.com/api" in request.url or "mexc.com/api" in request.url.lower():
                print(f"  [REQ] {request.method} {request.url[:150]}")

        # ── Capture ALL JSON responses ───────────────────────────────────
        def on_response(response: Response):
            url = response.url
            ct = response.headers.get("content-type", "")
            # Log all API calls
            if "mexc.com" in url and ("/api/" in url or ".json" in url):
                print(f"  [RSP] {response.status} {url[:150]}")
            # Try to parse any JSON from the domain
            if "json" in ct and "mexc.com" in url:
                try:
                    body = response.json()
                    all_responses.append({"url": url, "body": body})
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        print(f"\n[*] Loading {MEXC_URL} with domcontentloaded...")
        try:
            page.goto(MEXC_URL, wait_until="domcontentloaded", timeout=45_000)
        except Exception as e:
            print(f"[!] goto error: {e}")

        # Wait generously for all XHR to fire
        print("[*] Waiting 12s for XHR calls...")
        page.wait_for_timeout(12_000)

        # Scroll to trigger lazy loading
        for i in range(5):
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(1500)

        page.wait_for_timeout(3_000)

        # ── Print all captured API URLs for debugging ────────────────────
        print(f"\n[*] Total JSON responses captured: {len(all_responses)}")
        for resp in all_responses:
            url = resp["url"]
            body = resp["body"]
            keys = list(body.keys()) if isinstance(body, dict) else f"list[{len(body)}]"
            print(f"    {url[:120]} → {keys}")

        # ── Extract listings from all captured responses ──────────────────
        for resp in all_responses:
            extracted = extract_from_json(resp["body"])
            if extracted:
                print(f"  [+] {len(extracted)} listings from: {resp['url'][:100]}")
                listings.extend(extracted)

        # ── DOM fallback ─────────────────────────────────────────────────
        if not listings:
            print("\n[!] No listings from API, trying DOM...")
            listings = extract_from_dom(page)

        # ── Save screenshot for debugging ─────────────────────────────────
        if not listings:
            try:
                page.screenshot(path="/tmp/mexc_debug.png", full_page=False)
                with open("/tmp/mexc_debug.png", "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                print(f"\n[DEBUG] Screenshot saved (b64 length: {len(img_b64)})")
                # Save HTML snippet
                with open("/tmp/mexc_debug.html", "w") as f:
                    f.write(page.content()[:50_000])
                print("[DEBUG] HTML saved to /tmp/mexc_debug.html")
            except Exception as e:
                print(f"[!] Screenshot failed: {e}")

        browser.close()

    return listings


# ─── Parsers (same as before) ─────────────────────────────────────────────────

def extract_from_dom(page) -> list[dict]:
    listings = []
    selectors = [
        "[class*='listing-item']", "[class*='ProjectItem']",
        "[class*='project-item']", "[class*='newListing']",
        "[class*='NewListing'] > div", "[class*='listItem']",
        "[class*='card']", "[class*='item']",
    ]
    for sel in selectors:
        try:
            items = page.query_selector_all(sel)
            if items and len(items) < 100:  # sanity check
                print(f"[+] DOM selector '{sel}': {len(items)} items")
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
            raw = page.inner_text("body")
            print(f"[*] Trying raw body text ({len(raw)} chars)...")
            listings = parse_raw_text(raw)
        except Exception as e:
            print(f"[!] Body text failed: {e}")
    return listings


def extract_from_json(data) -> list[dict]:
    listings = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                parsed = try_parse_json_item(item)
                if parsed:
                    listings.append(parsed)
                else:
                    listings.extend(extract_from_json(item))
    elif isinstance(data, dict):
        for value in data.values():
            listings.extend(extract_from_json(value))
    return listings


def try_parse_json_item(item: dict) -> dict | None:
    symbol = next(
        (item[k].upper() for k in
         ["symbol", "coinName", "name", "token", "currency", "vcoinName",
          "currencyName", "baseCurrency", "baseAsset"]
         if k in item and isinstance(item[k], str) and 1 < len(item[k]) < 20),
        None,
    )
    if not symbol:
        return None

    listing_time = None
    for key in [
        "listingTime", "listing_time", "openTime", "releaseTime",
        "launchTime", "time", "startTime", "tradingTime",
        "firstOpenTime", "onlineTime", "publishTime",
    ]:
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

    if symbol and listing_time:
        now = datetime.now(tz=timezone.utc)
        # Include listings up to 7 days in the past (still "recent")
        # and any future listings
        if listing_time > now:
            return {
                "symbol": symbol,
                "listing_time": listing_time,
                "listing_time_str": listing_time.strftime("%Y-%m-%d %H:%M UTC"),
            }
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
    IGNORE = {
        "USDT", "UTC", "AM", "PM", "THE", "FOR", "AND", "NEW", "ALL",
        "BTC", "ETH", "LIST", "OPEN", "SPOT", "API", "MEXC",
    }
    listings, seen = [], set()
    for line in text.split("\n"):
        tm = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)', line)
        if not tm:
            continue
        coins = [
            s for s in re.findall(r'\b([A-Z]{2,10})\b', line)
            if s not in IGNORE and len(s) >= 3
        ]
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


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=15)
        r.raise_for_status()
        print("[+] Telegram message sent!")
        return True
    except requests.RequestException as e:
        print(f"[!] Telegram error: {e}")
        return False


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


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("MEXC New Listings Scraper v3")
    print("=" * 50)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID!")

    # Strategy 1: direct API (fast, no browser)
    print("\n[*] Strategy 1: Direct API calls...")
    listings = try_direct_api()

    # Strategy 2: Playwright with full network logging
    if not listings:
        print("\n[*] Strategy 2: Playwright browser scraping...")
        listings = scrape_with_playwright()

    # Deduplicate
    seen, unique = set(), []
    for item in listings:
        k = f"{item['symbol']}_{item['listing_time_str']}"
        if k not in seen:
            seen.add(k)
            unique.append(item)
    listings = unique

    print(f"\n{'='*50}")
    print(f"[+] RESULT: Found {len(listings)} upcoming listings:")
    for item in listings:
        print(f"    • {item['symbol']} – {item['listing_time_str']}")

    message = format_message(listings)
    print(f"\n[*] Sending Telegram notification...")
    if not send_telegram_message(message):
        raise RuntimeError("Failed to send Telegram message!")
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
