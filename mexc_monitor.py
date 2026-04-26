#!/usr/bin/env python3
"""
MEXC Crypto Monitor - Web Scraping z newlisting stránky
Sleduje https://www.mexc.com/newlisting pro nové coiny
"""
import os
import json
import requests
import re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

# Config
DATA_FILE = "weekly_data.json"
TIMEOUT = 10
MAX_COINS = 5

# Secrets
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print(f"\n{'='*60}")
print(f"🚀 MEXC Monitor (Web Scraping) - {datetime.utcnow().strftime('%H:%M:%S UTC')}")
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

# ========== WEB SCRAPING ==========
def get_new_listings():
    """Scrapuje MEXC newlisting stránku"""
    print("\n📍 Stahuji MEXC newlisting stránku...")
    try:
        url = "https://www.mexc.com/newlisting"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # Hledá se data v JSON formátu nebo data attributech
        # MEXC obvykle má data v <script> tagech
        scripts = soup.find_all('script')
        coins_data = []
        
        for script in scripts:
            if script.string:
                script_text = script.string
                
                # Hledá vzor s symbol a listen time
                # Typicky: "symbol":"BTC/USDT","listingTime":"2024-01-01T10:00:00Z"
                symbol_matches = re.findall(r'"symbol"\s*:\s*"([A-Z0-9/]+)"', script_text)
                time_matches = re.findall(r'"listingTime"\s*:\s*"([^"]+)"', script_text)
                
                if symbol_matches:
                    for i, symbol in enumerate(symbol_matches[:MAX_COINS]):
                        if symbol.endswith('USDT') or symbol.endswith('BTC'):
                            coins_data.append({
                                "symbol": symbol,
                                "time": time_matches[i] if i < len(time_matches) else None
                            })
        
        # Fallback: pokud se nepodařilo najít v script tagech, zkusí tabulku
        if not coins_data:
            print("  ⚠️ Nebyla data v <script> tagech, hledám v tabulce...")
            
            # Hledá libovolné prvky s coin symbolem
            rows = soup.find_all(['tr', 'div'], class_=re.compile(r'(coin|listing|row)', re.I))
            
            for row in rows[:MAX_COINS]:
                text = row.get_text()
                # Hledá vzor: XXX/USDT
                match = re.search(r'([A-Z0-9]+/USDT)', text)
                if match:
                    symbol = match.group(1)
                    if symbol not in [c["symbol"] for c in coins_data]:
                        coins_data.append({
                            "symbol": symbol,
                            "time": None
                        })
        
        # Deduplikace
        seen = set()
        unique_coins = []
        for coin in coins_data:
            if coin["symbol"] not in seen:
                seen.add(coin["symbol"])
                unique_coins.append(coin)
        
        print(f"✅ Nalezeno {len(unique_coins)} coinů")
        return unique_coins[:MAX_COINS]
        
    except Exception as e:
        print(f"❌ Scraping error: {e}")
        # Fallback na API
        print("  ℹ️ Fallback na MEXC API...")
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
print("📌 Kontrola Telegram...")
send_msg(f"🤖 Monitor check: {datetime.utcnow().strftime('%H:%M UTC')}")

print("\n📌 Scraping MEXC newlisting...")
coins = get_new_listings()

if coins:
    print(f"\n📌 Zpracování {len(coins)} coinů...")
    data = load_data()
    
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
    
    send_msg(msg)
    
    # Reset
    save_data({"week_start": datetime.utcnow().isoformat(), "coins": []})

print(f"\n✅ HOTOVO - {datetime.utcnow().strftime('%H:%M:%S UTC')}")
print(f"{'='*60}\n")
