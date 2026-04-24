#!/usr/bin/env python3
"""
MEXC New Coins Monitor - Sleduje nové coiny a jejich performance
"""

import os
import json
import csv
import requests
import time
from datetime import datetime, timedelta
from pathlib import Path
import hmac
import hashlib
from urllib.parse import urlencode
import asyncio
from collections import defaultdict

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# MEXC API
MEXC_ACCESS_KEY = os.environ.get('MEXC_ACCESS_KEY')
MEXC_SECRET_KEY = os.environ.get('MEXC_SECRET_KEY')

MEXC_API_BASE = "https://api.mexc.com"
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

class MEXCMonitor:
    def __init__(self):
        self.session = requests.Session()
        self.new_coins_today = []
        
    def sign_request(self, params):
        """Podepíši MEXC request"""
        query_string = urlencode(params)
        signature = hmac.new(
            MEXC_SECRET_KEY.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def get_all_coins(self):
        """Získej seznam všech coinů s jejich info"""
        try:
            resp = self.session.get(f"{MEXC_API_BASE}/api/v3/exchangeInfo", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Chyba při získávání coinů: {e}")
            return None
    
    def get_recent_trades(self, symbol, limit=100):
        """Získej poslední transakce pro symbol"""
        try:
            params = {'symbol': symbol, 'limit': limit}
            resp = self.session.get(
                f"{MEXC_API_BASE}/api/v3/trades",
                params=params,
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Chyba při získávání obchodů pro {symbol}: {e}")
            return None
    
    def get_klines(self, symbol, interval='1m', limit=20):
        """Získej kline data (cenovní data)"""
        try:
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            resp = self.session.get(
                f"{MEXC_API_BASE}/api/v3/klines",
                params=params,
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Chyba při získávání klines pro {symbol}: {e}")
            return None
    
    def get_ticker_price(self, symbol):
        """Získej aktuální cenu"""
        try:
            resp = self.session.get(
                f"{MEXC_API_BASE}/api/v3/ticker/price",
                params={'symbol': symbol},
                timeout=10
            )
            resp.raise_for_status()
            return float(resp.json().get('price', 0))
        except Exception as e:
            print(f"Chyba při získávání ceny {symbol}: {e}")
            return None
    
    def load_monitored_coins(self):
        """Načti seznam monitorovaných coinů"""
        coins_file = DATA_DIR / "monitored_coins.json"
        if coins_file.exists():
            with open(coins_file, 'r') as f:
                return json.load(f)
        return {}
    
    def save_monitored_coins(self, data):
        """Ulož seznam monitorovaných coinů"""
        coins_file = DATA_DIR / "monitored_coins.json"
        with open(coins_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def detect_new_coins(self):
        """Detekuj nové coiny"""
        exchange_info = self.get_all_coins()
        if not exchange_info:
            return []
        
        # Filtruj jen USDT páry (relevantní coiny)
        current_coins = set()
        new_coins = []
        
        for symbol_info in exchange_info.get('symbols', []):
            symbol = symbol_info['symbol']
            if symbol.endswith('USDT'):
                current_coins.add(symbol)
        
        # Načti předchozí seznam
        monitored = self.load_monitored_coins()
        previous_coins = set(monitored.keys())
        
        # Najdi nové
        for coin in current_coins - previous_coins:
            timestamp = datetime.now().isoformat()
            new_coins.append({
                'symbol': coin,
                'discovered': timestamp,
                'measurements': []
            })
            monitored[coin] = {
                'discovered': timestamp,
                'measurements': [],
                'max_gain': 0
            }
        
        if new_coins:
            self.save_monitored_coins(monitored)
        
        return new_coins
    
    def measure_coin_performance(self, symbol, minutes=20):
        """Měř performance coinu po dobu X minut"""
        print(f"🕐 Měřím {symbol} po dobu {minutes} minut...")
        
        prices = []
        start_time = datetime.now()
        
        while (datetime.now() - start_time).seconds < (minutes * 60):
            try:
                price = self.get_ticker_price(symbol)
                if price:
                    prices.append({
                        'timestamp': datetime.now().isoformat(),
                        'price': price
                    })
                    print(f"  {symbol}: ${price:.8f}")
                
                # Počekej 1 minutu mezi měřeními
                time.sleep(60)
            except Exception as e:
                print(f"Chyba při měření: {e}")
                time.sleep(10)
        
        return prices
    
    def calculate_gain(self, prices):
        """Spočítej maximální nárůst v %"""
        if len(prices) < 2:
            return 0
        
        prices_only = [float(p['price']) for p in prices]
        min_price = min(prices_only)
        max_price = max(prices_only)
        
        if min_price == 0:
            return 0
        
        gain_percent = ((max_price - min_price) / min_price) * 100
        return round(gain_percent, 2)
    
    def check_and_measure(self):
        """Hlavní funkce - kontroluj nové coiny a měř je"""
        print("\n" + "="*50)
        print(f"🔍 Kontrola v {datetime.now().strftime('%H:%M:%S')}")
        print("="*50)
        
        new_coins = self.detect_new_coins()
        monitored = self.load_monitored_coins()
        
        if new_coins:
            print(f"\n✅ Nalezeno {len(new_coins)} nových coinů!")
            for coin_data in new_coins:
                symbol = coin_data['symbol']
                print(f"\n📍 Nový coin: {symbol}")
                
                # Počkej 1 minutu, aby se coin ustálil
                print("⏳ Čekám 1 minutu aby se coin ustálil...")
                time.sleep(60)
                
                # Měř 20 minut
                prices = self.measure_coin_performance(symbol, minutes=20)
                
                if prices:
                    gain = self.calculate_gain(prices)
                    monitored[symbol]['max_gain'] = gain
                    monitored[symbol]['measurements'] = prices
                    
                    print(f"\n📊 {symbol} - Maximální nárůst: {gain}%")
                    self.save_monitored_coins(monitored)
        else:
            print("ℹ️  Žádné nové coiny")
        
        return monitored
    
    def send_telegram_message(self, message, parse_mode='HTML'):
        """Pošli zprávu na Telegram"""
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': parse_mode
            }
            resp = requests.post(url, json=data, timeout=10)
            resp.raise_for_status()
            print(f"✅ Telegram zpráva odeslána")
        except Exception as e:
            print(f"❌ Chyba při odesílání Telegramu: {e}")
    
    def generate_weekly_report(self):
        """Vygeneruj týdenní zprávu (volaj v neděli)"""
        monitored = self.load_monitored_coins()
        
        # Filtruj coiny z tohoto týdne
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())
        
        week_coins = []
        for symbol, data in monitored.items():
            discovered = datetime.fromisoformat(data['discovered'])
            if discovered >= week_start:
                week_coins.append({
                    'symbol': symbol,
                    'discovered': discovered,
                    'max_gain': data.get('max_gain', 0),
                    'measurements': data.get('measurements', [])
                })
        
        if not week_coins:
            msg = "📊 Žádné nové coiny tento týden"
            self.send_telegram_message(msg)
            return
        
        # Seřaď podle maximálního zisku
        week_coins.sort(key=lambda x: x['max_gain'], reverse=True)
        
        # Vytvoř report
        msg = "📊 <b>MEXC TÝDENNÍ REPORT</b>\n\n"
        msg += f"<b>Počet nových coinů:</b> {len(week_coins)}\n\n"
        
        for i, coin in enumerate(week_coins, 1):
            msg += f"{i}. <b>{coin['symbol']}</b>\n"
            msg += f"   Zjištěno: {coin['discovered'].strftime('%d.%m %H:%M')}\n"
            msg += f"   Max. zisk: <code>{coin['max_gain']}%</code>\n"
            
            if coin['measurements']:
                first_price = float(coin['measurements'][0]['price'])
                last_price = float(coin['measurements'][-1]['price'])
                current_price = self.get_ticker_price(coin['symbol'])
                
                if current_price:
                    current_gain = ((current_price - first_price) / first_price) * 100
                    msg += f"   Aktuální zisk: <code>{current_gain:.2f}%</code>\n"
            
            msg += "\n"
        
        # Statistiky
        avg_gain = sum(c['max_gain'] for c in week_coins) / len(week_coins)
        best_coin = week_coins[0]
        
        msg += f"<b>Průměrný zisk (20min):</b> <code>{avg_gain:.2f}%</code>\n"
        msg += f"<b>Nejlepší coin:</b> {best_coin['symbol']} (<code>{best_coin['max_gain']}%</code>)\n"
        
        self.send_telegram_message(msg)
        print(msg)
        
        # Ulož report
        report_file = DATA_DIR / f"report_{today.strftime('%Y-%m-%d')}.txt"
        with open(report_file, 'w') as f:
            f.write(msg.replace('<b>', '').replace('</b>', '')
                     .replace('<code>', '').replace('</code>', ''))


def main():
    """Hlavní funkce"""
    monitor = MEXCMonitor()
    
    # Zkontroluj co má skript dělat
    action = os.environ.get('ACTION', 'monitor')
    
    if action == 'monitor':
        # Běžná kontrola a měření
        monitor.check_and_measure()
    elif action == 'report':
        # Týdenní report (volej v neděli)
        monitor.generate_weekly_report()


if __name__ == '__main__':
    main()
