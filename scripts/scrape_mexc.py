"""
MEXC New Listings Scraper
Scrapuje budoucí release časy z https://www.mexc.com/newlisting
a odesílá shrnutí přes Telegram bota.
"""

import os
import re
import json
import requests
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright


MEXC_URL = "https://www.mexc.com/newlisting"
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def scrape_listings() -> list[dict]:
    """Scrape budoucích coin listingů z MEXC pomocí Playwright."""
    listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        print(f"[*] Načítám {MEXC_URL} ...")
        page.goto(MEXC_URL, wait_until="networkidle", timeout=60_000)

        # Počkáme, až se načtou karty s listingy
        try:
            page.wait_for_selector(
                "div[class*='listing'], div[class*='project'], "
                "div[class*='token'], div[class*='coin'], "
                ".new-listing-item, [data-testid*='listing']",
                timeout=20_000,
            )
        except Exception:
            print("[!] Specifický selektor nenalezen, zkouším obecnější přístup...")

        # Scroll dolů, aby se načetly lazy-loaded položky
        for _ in range(5):
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(1000)

        # --- Pokus 1: zachytit API odpovědi přes síť (nejspolehlivější) ---
        # MEXC typicky volá interní API – zkusíme interceptovat
        page.reload(wait_until="networkidle")

        # Získej celý HTML pro parsování
        html_content = page.content()

        # --- Pokus 2: přímá extrakce z DOM ---
        listings = extract_from_dom(page)

        if not listings:
            print("[!] DOM extrakce selhala, zkouším zachytit JSON data...")
            listings = extract_from_html(html_content)

        browser.close()

    return listings


def extract_from_dom(page) -> list[dict]:
    """Extrahuj listing data přímo z DOM elementů."""
    listings = []

    # Zkus různé selektory, které MEXC používá
    selectors_to_try = [
        # Obecné karty
        "div[class*='listing-item']",
        "div[class*='ProjectItem']",
        "div[class*='project-item']",
        "div[class*='token-item']",
        "div[class*='newListing']",
        ".listing-card",
        "[class*='NewListing'] > div",
        "[class*='listItem']",
    ]

    for selector in selectors_to_try:
        try:
            items = page.query_selector_all(selector)
            if items:
                print(f"[+] Nalezeno {len(items)} položek s selektorem: {selector}")
                for item in items:
                    try:
                        text = item.inner_text()
                        listing = parse_listing_text(text)
                        if listing:
                            listings.append(listing)
                    except Exception:
                        continue
                break
        except Exception:
            continue

    # Fallback: hledáme všechny texty s coiny a časy
    if not listings:
        print("[*] Zkouším fallback – hledám libovolné texty s časy...")
        try:
            all_text = page.inner_text("body")
            listings = parse_raw_text(all_text)
        except Exception as e:
            print(f"[!] Fallback selhal: {e}")

    return listings


def extract_from_html(html: str) -> list[dict]:
    """Extrahuj data ze surového HTML / JSON chunků vložených do stránky."""
    listings = []

    # Hledej JSON data vložená do stránky (Next.js / Nuxt pattern)
    json_patterns = [
        r'window\.__NUXT__\s*=\s*(\{.*?\});',
        r'"listing"\s*:\s*(\[.*?\])',
        r'"newListing"\s*:\s*(\[.*?\])',
        r'"upcomingListings"\s*:\s*(\[.*?\])',
        r'"data"\s*:\s*(\[.*?"symbol".*?\])',
    ]

    for pattern in json_patterns:
        matches = re.findall(pattern, html, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match)
                extracted = extract_from_json(data)
                if extracted:
                    listings.extend(extracted)
                    print(f"[+] Nalezeno {len(extracted)} listingů z JSON patternu")
                    return listings
            except json.JSONDecodeError:
                continue

    return listings


def extract_from_json(data) -> list[dict]:
    """Rekurzivně prohledej JSON strukturu a hledej listing záznamy."""
    listings = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                listing = try_parse_json_item(item)
                if listing:
                    listings.append(listing)
                else:
                    listings.extend(extract_from_json(item))
    elif isinstance(data, dict):
        for value in data.values():
            listings.extend(extract_from_json(value))

    return listings


def try_parse_json_item(item: dict) -> dict | None:
    """Pokus se parsovat jeden JSON objekt jako listing."""
    # Hledáme záznamy s názvem coinu a časem
    symbol_keys = ["symbol", "coinName", "name", "token", "currency", "vcoinName"]
    time_keys = [
        "listingTime", "listing_time", "openTime", "releaseTime",
        "launchTime", "time", "startTime", "tradingTime"
    ]

    symbol = None
    for key in symbol_keys:
        if key in item and isinstance(item[key], str):
            symbol = item[key].upper()
            break

    listing_time = None
    for key in time_keys:
        if key in item:
            val = item[key]
            # Unix timestamp (ms nebo s)
            if isinstance(val, (int, float)) and val > 1_000_000_000:
                ts = val / 1000 if val > 1e12 else val
                listing_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                break
            # ISO string
            elif isinstance(val, str) and len(val) > 8:
                try:
                    from dateutil import parser as date_parser
                    listing_time = date_parser.parse(val)
                    if listing_time.tzinfo is None:
                        listing_time = listing_time.replace(tzinfo=timezone.utc)
                    break
                except Exception:
                    pass

    if symbol and listing_time:
        now = datetime.now(tz=timezone.utc)
        if listing_time > now:  # pouze budoucí
            return {
                "symbol": symbol,
                "listing_time": listing_time,
                "listing_time_str": listing_time.strftime("%Y-%m-%d %H:%M UTC"),
                "raw": item,
            }
    return None


def parse_listing_text(text: str) -> dict | None:
    """Parsuj text karty a extrahuj symbol + čas."""
    # Hledáme pattern jako "SYMBOL/USDT ... 2025-01-15 10:00"
    time_pattern = r'(\d{4}-\d{2}-\d{2}[\s\T]\d{2}:\d{2}(?::\d{2})?)'
    time_match = re.search(time_pattern, text)

    symbol_pattern = r'\b([A-Z]{2,10})(?:/USDT|/BTC|/ETH)?\b'
    symbol_match = re.search(symbol_pattern, text)

    if time_match and symbol_match:
        try:
            from dateutil import parser as date_parser
            listing_time = date_parser.parse(time_match.group(1))
            if listing_time.tzinfo is None:
                listing_time = listing_time.replace(tzinfo=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            if listing_time > now:
                return {
                    "symbol": symbol_match.group(1),
                    "listing_time": listing_time,
                    "listing_time_str": listing_time.strftime("%Y-%m-%d %H:%M UTC"),
                    "raw_text": text[:200],
                }
        except Exception:
            pass
    return None


def parse_raw_text(text: str) -> list[dict]:
    """Fallback parser pro surový text celé stránky."""
    listings = []
    time_pattern = r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)'
    symbol_pattern = r'\b([A-Z]{2,10})\b'

    lines = text.split('\n')
    for line in lines:
        time_match = re.search(time_pattern, line)
        if time_match:
            symbols = re.findall(symbol_pattern, line)
            # Filtruj běžná anglická slova
            ignore = {
                "USDT", "UTC", "AM", "PM", "THE", "FOR", "AND", "NEW",
                "ALL", "BTC", "ETH", "LIST", "OPEN", "SPOT", "API"
            }
            coins = [s for s in symbols if s not in ignore and len(s) >= 3]
            if coins:
                try:
                    from dateutil import parser as date_parser
                    listing_time = date_parser.parse(time_match.group(1))
                    if listing_time.tzinfo is None:
                        listing_time = listing_time.replace(tzinfo=timezone.utc)
                    now = datetime.now(tz=timezone.utc)
                    if listing_time > now:
                        listings.append({
                            "symbol": coins[0],
                            "listing_time": listing_time,
                            "listing_time_str": listing_time.strftime(
                                "%Y-%m-%d %H:%M UTC"
                            ),
                            "raw_text": line[:200],
                        })
                except Exception:
                    continue

    # Deduplikace
    seen = set()
    unique = []
    for item in listings:
        key = f"{item['symbol']}_{item['listing_time_str']}"
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def send_telegram_message(text: str) -> bool:
    """Odešli zprávu přes Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        print("[+] Telegram zpráva odeslána úspěšně!")
        return True
    except requests.RequestException as e:
        print(f"[!] Chyba při odesílání Telegram zprávy: {e}")
        return False


def format_telegram_message(listings: list[dict]) -> str:
    """Naformátuj zprávu pro Telegram."""
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not listings:
        return (
            "🪙 <b>MEXC New Listings – Žádné nalezeny</b>\n\n"
            f"Sken proběhl: {now_str}\n"
            "📭 Nebyly nalezeny žádné budoucí listingy.\n\n"
            f'🔗 <a href="{MEXC_URL}">Zkontroluj ručně</a>'
        )

    # Seřaď podle času
    listings.sort(key=lambda x: x["listing_time"])

    lines = [
        f"🪙 <b>MEXC New Listings</b>",
        f"📅 Sken: {now_str}",
        f"✅ Nalezeno celkem: <b>{len(listings)} coinů</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for i, listing in enumerate(listings, 1):
        symbol = listing["symbol"]
        time_str = listing["listing_time_str"]

        # Výpočet zbývajícího času
        now = datetime.now(tz=timezone.utc)
        delta = listing["listing_time"] - now
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60

        if days > 0:
            countdown = f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            countdown = f"{hours}h {minutes}m"
        else:
            countdown = f"{minutes}m"

        lines.append(
            f"\n{i}. <b>{symbol}</b>\n"
            f"   🕐 {time_str}\n"
            f"   ⏳ Za: {countdown}"
        )

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
    lines.append(f'🔗 <a href="{MEXC_URL}">MEXC New Listing</a>')

    return "\n".join(lines)


def main():
    print("=" * 50)
    print("MEXC New Listings Scraper")
    print("=" * 50)

    # Ověř environment variables
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError(
            "Chybí TELEGRAM_BOT_TOKEN nebo TELEGRAM_CHAT_ID env proměnné!"
        )

    # Scraping
    print("\n[*] Spouštím scraper...")
    listings = scrape_listings()

    print(f"\n[+] Nalezeno {len(listings)} budoucích listingů")
    for listing in listings:
        print(f"    • {listing['symbol']} – {listing['listing_time_str']}")

    # Formátování a odeslání
    message = format_telegram_message(listings)
    print("\n[*] Odesílám Telegram notifikaci...")
    print(f"\nZpráva:\n{message}\n")

    success = send_telegram_message(message)
    if not success:
        raise RuntimeError("Nepodařilo se odeslat Telegram zprávu!")

    print("\n✅ Hotovo!")


if __name__ == "__main__":
    main()
