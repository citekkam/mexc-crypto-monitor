#!/usr/bin/env python3
"""
MEXC Crypto Monitor - Jednoduchá verze
Sleduje nové coiny a jejich výkonnost za 20 minut
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path

# Config
DATA_FILE = "weekly_data.json"
TIMEOUT = 10

# Secrets
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print(f"\n{'='*60}")
print(f"🚀 MEXC Monitor START - {datetime.utcnow().strftime('%H:%M:%S UTC')}")
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
            print(f"✅ Telegram OK: {text[:50]}...")
            return True
        else:
            print(f"❌ Telegram failed: {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False

# ========== MEXC API ==========
def get_coins():
    """Stáhne trading páry z MEXC"""
    print("\n📍 Stahuju MEXC coiny...")
    try:
        url = "https://api.mexc.com/api/v3/exchangeInfo"
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        
        coins = []
        for sym in data.get("symbols", []):
            if sym.get("status") == "TRADING" and sym.get("symbol", "").endswith("USDT"):
                coins.append(sym["symbol"])
                if len(coins) >= 5:  # Stačí 5 pro test
                    break
        
        print(f"✅ Nalezeno {len(coins)} coinů")
        return coins
    except Exception as e:
        print(f"❌ MEXC API error: {e}")
        return []

def get_prices(symbol):
    """Stáhne ceny za posledních 20 minut"""
    print(f"  📈 Stahuji {symbol}...")
    try:
        url = "https://api.mexc.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": "1m",
            "limit": 25  # 20 minut + rezerva
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

print("\n📌 Kontrola MEXC...")
coins = get_coins()

if coins:
    print(f"\n📌 Zpracování {len(coins)} coinů...")
    data = load_data()
    
    for symbol in coins:
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

# Nedělí report
if datetime.utcnow().weekday() == 6:
    coins_list = data.get("coins", [])
    msg = f"📊 <b>Týdenní Report</b>\n"
    msg += f"Počet: {len(coins_list)}\n\n"
    
    if coins_list:
        perf_list = [c["perf"] for c in coins_list]
        for coin in coins_list[:10]:  # Max 10 v report
            msg += f"<b>{coin['symbol']}</b>: +{coin['perf']}%\n"
        msg += f"\n<b>Avg: +{round(sum(perf_list)/len(perf_list), 2)}%</b>"
    
    send_msg(msg)
    
    # Reset
    save_data({"week_start": datetime.utcnow().isoformat(), "coins": []})

print(f"\n✅ HOTOVO - {datetime.utcnow().strftime('%H:%M:%S UTC')}")
print(f"{'='*60}\n")
