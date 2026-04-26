#!/usr/bin/env python3
"""
MEXC Crypto Monitor - s Playwright pro JavaScript
Sleduje https://www.mexc.com/newlisting pro nové coiny
"""
import os
import json
import requests
import re
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

# Config
DATA_FILE = "weekly_data.json"
TIMEOUT = 10
MAX_COINS = 10

# Secrets
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print(f"\n{'='*60}")
print(f"🚀 MEXC Monitor (Playwright) - {datetime.utcnow().strftime('%H:%M:%S UTC')}")
print(f"{'='*60}\n")

# ========== TELEGRAM ==========
def send_msg(text):
    """Pošle Telegram zprávu"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram config missing!")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        r = requests.post(url, json=payload, timeout=TIMEOUT)
        if r.status_code == 200:
            print(f"✅ Telegram OK")
            return True
        else:
            print(f"❌ Telegram failed: {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False

# ========== WEB SCRAPING S PLAYWRIGHT ==========
def get_new_listings():
    """Scrapuje MEXC newlisting stránku s Playwright"""
    print("\n📍 Otevírám MEXC newlisting v browseru...")
    try:
        with sync_playwright() as p:
            # Spusť browser
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Jdi na stránku
            print("  ⏳ Čekám na stránku...")
            page.goto("https://www.mexc.com/newlisting", wait_until="domcontentloaded", timeout=30000)
            
            # Čekej na obsah (max 10 sekund)
            try:
                page.wait_for_selector('[class*="coin"], [class*="symbol"], [class*="listing"]', timeout=10000)
                print("  ✅ Stránka se načetla")
            except:
                print("  ⚠️ Selektor nenalezen, zkusím obecný parser")
            
            # Vezmi HTML
            html = page.content()
            browser.close()
            
            # Parse HTML a hledej symboly
            coins_data = []
            
            # Hledá textové vzory: XXX/USDT, XXX/BUSD, atd
            # Musí být kapitálky a lomítko
            matches = re.findall(r'\b([A-Z][A-Z0-9]{0,10})/([A-Z]{4,6})\b', html)
            
            seen = set()
            for symbol, quote in matches:
                full_symbol = f"{symbol}/{quote}"
                
                # Filtruj jen USDT a podobné páry
                if quote in ['USDT', 'BUSD', 'USDC', 'BTC', 'ETH'] and full_symbol not in seen:
                    # Zkontroluj, že není to duplicita nebo garbage
                    if len(symbol) >= 2 and len(symbol) <= 15:
                        coins_data.append({
                            "symbol": full_symbol,
                            "time": None
                        })
                        seen.add(full_symbol)
                        
                        if len(coins_data) >= MAX_COINS:
                            break
            
            print(f"✅ Nalezeno {len(coins_data)} coinů z HTML")
            return coins_data
        
    except Exception as e:
        print(f"❌ Playwright error: {e}")
        print("  ℹ️ Fallback na API...")
        return get_coins_from_api()

def get_coins_from_api():
    """Fallback: získá coiny z API"""
    print("📍 Fallback: Stahuji z MEXC API...")
    try:
        url = "https://api.mexc.com/api/v3/exchangeInfo"
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        
        coins = []
        for sym in data.get("symbols", []):
            if sym.get("status") == "TRADING" and sym.get("symbol", "").endswith("USDT"):
                coins.append({
                    "symbol": sym["symbol"],
                    "time": None
                })
                if len(coins) >= MAX_COINS:
                    break
        
        print(f"✅ API: Nalezeno {len(coins)} coinů")
        return coins
    except Exception as e:
        print(f"❌ API fallback error: {e}")
        return []

# ========== MEXC API PRICES ==========
def get_prices(symbol):
    """Stáhne ceny za posledních 20 minut"""
    print(f"  📈 Stahuji {symbol}...")
    try:
        url = "https://api.mexc.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": "1m",
            "limit": 25
        }
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        klines = r.json()
        
        if not klines:
            print(f"    ⚠️ Žádná data")
            return None
        
        prices = []
        for kline in klines[:20]:
            try:
                prices.append({
                    "close": float(kline[4]),
                    "high": float(kline[2])
                })
            except:
                pass
        
        if len(prices) < 2:
            print(f"    ⚠️ Málo dat")
            return None
        
        print(f"    ✅ {len(prices)} minut")
        return prices
    except Exception as e:
        print(f"    ❌ Error: {e}")
        return None

def calc_perf(prices):
    """Spočítá nárůst"""
    if not prices:
        return 0
    start = prices[0]["close"]
    max_price = max(p["high"] for p in prices)
    if start == 0:
        return 0
    return round(((max_price - start) / start) * 100, 2)

# ========== DATA ==========
def load_data():
    """Načte týdenní data"""
    try:
        if Path(DATA_FILE).exists():
            with open(DATA_FILE) as f:
                return json.load(f)
    except:
        pass
    
    return {
        "week_start": datetime.utcnow().isoformat(),
        "coins": []
    }

def save_data(data):
    """Uloží data"""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print("✅ Data uložena")

# ========== MAIN ==========
# DŮLEŽITÉ: Vždycky načti data na začátku!
data = load_data()

print("📌 Kontrola Telegram...")
send_msg(f"🤖 Monitor check: {datetime.utcnow().strftime('%H:%M UTC')}")

print("\n📌 Scraping MEXC newlisting...")
coins = get_new_listings()

if coins:
    print(f"\n📌 Zpracování {len(coins)} coinů...")
    
    for coin in coins:
        symbol = coin["symbol"]
        prices = get_prices(symbol)
        
        if prices:
            perf = calc_perf(prices)
            price_start = prices[0]["close"]
            price_max = max(p["high"] for p in prices)
            
            # Ulož data
            data["coins"].append({
                "symbol": symbol,
                "perf": perf,
                "checked": datetime.utcnow().isoformat()
            })
            
            # Telegram notifikace
            msg = f"🔥 <b>{symbol}</b>\n"
            msg += f"📈 +{perf}% (20 min)\n"
            msg += f"Start: ${price_start:.8f}\n"
            msg += f"Max: ${price_max:.8f}"
            send_msg(msg)
            
            print(f"  ✅ {symbol}: +{perf}%")
    
    # Ulož data
    save_data(data)
else:
    send_msg("✔️ Žádné nové coiny")
    print("\n✔️ Žádné coiny")

# Nedělní report
if datetime.utcnow().weekday() == 6:
    coins_list = data.get("coins", [])
    msg = f"📊 <b>Týdenní Report</b>\n"
    msg += f"Počet: {len(coins_list)}\n\n"
    
    if coins_list:
        perf_list = [c["perf"] for c in coins_list]
        for coin in coins_list[:10]:
            msg += f"<b>{coin['symbol']}</b>: +{coin['perf']}%\n"
        msg += f"\n<b>Avg: +{round(sum(perf_list)/len(perf_list), 2)}%</b>"
    else:
        msg += "Žádné coiny v tomto týdnu"
    
    send_msg(msg)
    
    # Reset
    save_data({"week_start": datetime.utcnow().isoformat(), "coins": []})

print(f"\n✅ HOTOVO - {datetime.utcnow().strftime('%H:%M:%S UTC')}")
print(f"{'='*60}\n")
