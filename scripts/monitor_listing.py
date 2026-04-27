"""
MEXC Listing Price Monitor - v4.2 (Fixed conditions)
"""

import os
import sys
import time
import requests
from datetime import datetime

# Načtení proměnných prostředí
SYMBOL             = os.environ.get("COIN_SYMBOL", "").strip().upper()
LISTING_TIME_STR   = os.environ.get("LISTING_TIME_STR", "N/A")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# API Konfigurace
PRICE_API    = "https://api.mexc.com/api/v3/ticker/price"
CHART_URL    = f"https://www.mexc.com/exchange/{SYMBOL}_USDT"
MONITOR_SECS = 20 * 60
POLL_SECS    = 30

def get_price() -> float | None:
    try:
        r = requests.get(PRICE_API, params={"symbol": f"{SYMBOL}USDT"}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            p = float(data.get("price", 0))
            return p if p > 0 else None
        return None
    except Exception as e:
        print(f"[!] Chyba API: {e}")
        return None

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Telegram token nebo Chat ID chybí!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": text,
            "parse_mode": "HTML", 
            "disable_web_page_preview": False,
        }, timeout=15)
        r.raise_for_status()
        print("[+] Telegram zpráva odeslána.")
    except Exception as e:
        print(f"[!] Telegram error: {e}")

def fmt_price(p: float) -> str:
    if p < 0.000001: return f"${p:.10f}"
    if p < 0.001:    return f"${p:.8f}"
    if p < 1:        return f"${p:.6f}"
    return f"${p:.4f}"

def main():
    print(f"[*] Spouštím monitor pro: {SYMBOL}")
    
    # OPRAVA PODMÍNKY: Kontrolujeme existenci, ne hodnotu 0
    env_ts = os.environ.get("LISTING_TIME_TS")
    if not SYMBOL or env_ts is None:
        print(f"[!] CHYBA: Symbol='{SYMBOL}', TS='{env_ts}'")
        sys.exit(1)

    try:
        target_ts = int(env_ts)
    except ValueError:
        print(f"[!] CHYBA: Neplatný formát timestampu: {env_ts}")
        sys.exit(1)

    # 1. Čekání na listing
    now_ts = int(time.time())
    wait_time = target_ts - now_ts
    if target_ts > 0 and wait_time > 0:
        print(f"[*] Čekám {wait_time}s do listingu ({LISTING_TIME_STR})...")
        time.sleep(wait_time)
    else:
        print("[*] Startuji okamžitě (timestamp je 0 nebo v minulosti).")

    # 2. Úvodní notifikace
    send_telegram(
        f"🔔 <b>{SYMBOL} právě listoval na MEXC!</b>\n"
        f"📊 Spouštím 20min monitoring ceny...\n"
        f'🔗 <a href="{CHART_URL}">Otevřít Graf</a>'
    )

    # 3. Získání startovní ceny (Open)
    initial_price = None
    print("[*] Hledám úvodní cenu...")
    for attempt in range(20): # Pokusy po dobu 2 minut
        initial_price = get_price()
        if initial_price:
            print(f"[+] Úvodní cena nalezena: {initial_price}")
            break
        print(f"    Zkouším znovu ({attempt+1}/20)...")
        time.sleep(6)

    if not initial_price:
        send_telegram(f"⚠️ <b>{SYMBOL}</b>: Cena nebyla dostupná ani po 2 minutách od startu.")
        return

    # 4. Monitoring 20 minut
    prices = [initial_price]
    steps = MONITOR_SECS // POLL_SECS
    
    print(f"[*] Monitoruji po dobu 20 minut (každých {POLL_SECS}s)...")
    for i in range(steps):
        time.sleep(POLL_SECS)
        p = get_price()
        if p:
            prices.append(p)
            peak = max(prices)
            change = (p - initial_price) / initial_price * 100
            print(f"    [{i+1}/{steps}] {fmt_price(p)} ({change:+.2f}%) | Peak: {fmt_price(peak)}")
        else:
            print(f"    [{i+1}/{steps}] Výpadek API...")

    # 5. Finální report
    max_p = max(prices)
    min_p = min(prices)
    final_p = prices[-1]
    
    gain_max = (max_p - initial_price) / initial_price * 100
    gain_final = (final_p - initial_price) / initial_price * 100
    
    emoji = "🚀🚀🚀" if gain_max > 100 else "🚀" if gain_max > 20 else "📈" if gain_max > 0 else "📉"
    
    report = (
        f"{emoji} <b>{SYMBOL}/USDT – Report (20 min)</b>\n\n"
        f"💰 <b>Ceny:</b>\n"
        f"  • Open: {fmt_price(initial_price)}\n"
        f"  • Max:  <b>{fmt_price(max_p)} (+{gain_max:.1f}%)</b>\n"
        f"  • Min:  {fmt_price(min_p)}\n"
        f"  • Close: {fmt_price(final_p)} ({gain_final:+.1f}%)\n\n"
        f"📊 <b>Max zhodnocení: {gain_max:+.1f}%</b>\n\n"
        f'🔗 <a href="{CHART_URL}">Zobrazit graf na MEXC</a>'
    )
    
    send_telegram(report)
    print("[*] Hotovo. Všechny reporty odeslány.")

if __name__ == "__main__":
    main()
