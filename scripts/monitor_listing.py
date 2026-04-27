"""
MEXC Listing Price Monitor - v4.1 (Bugfixed)
"""

import os
import sys
import time
import requests
from datetime import datetime

SYMBOL             = os.environ.get("COIN_SYMBOL", "").upper()
LISTING_TIME_TS    = int(os.environ.get("LISTING_TIME_TS", "0"))
LISTING_TIME_STR   = os.environ.get("LISTING_TIME_STR", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

PRICE_API    = "https://api.mexc.com/api/v3/ticker/price"
CHART_URL    = f"https://www.mexc.com/exchange/{SYMBOL}_USDT"
MONITOR_SECS = 20 * 60
POLL_SECS    = 30

def get_price() -> float | None:
    try:
        # MEXC vyžaduje přesný symbol, např. BTCUSDT
        r = requests.get(PRICE_API, params={"symbol": f"{SYMBOL}USDT"}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            p = float(data.get("price", 0))
            return p if p > 0 else None
        return None
    except Exception as e:
        print(f"[!] Chyba pripojeni k API: {e}")
        return None

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Telegram credentials chybi!")
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
    except Exception as e:
        print(f"[!] Telegram error: {e}")

def fmt_price(p: float) -> str:
    if p < 0.000001: return f"${p:.10f}"
    if p < 0.001:    return f"${p:.8f}"
    if p < 1:        return f"${p:.6f}"
    return f"${p:.4f}"

def main():
    if not SYMBOL or not LISTING_TIME_TS:
        print("[!] Chybi SYMBOL nebo LISTING_TIME_TS!")
        return

    # 1. CEKANI NA LISTING
    now_ts = int(time.time())
    wait_time = LISTING_TIME_TS - now_ts
    if wait_time > 0:
        print(f"[*] Cekam {wait_time}s do listingu...")
        time.sleep(wait_time)

    # 2. START NOTIFIKACE
    send_telegram(
        f"🔔 <b>{SYMBOL} právě listoval na MEXC!</b>\n"
        f"📊 Spouštím 20min monitoring...\n"
        f'🔗 <a href="{CHART_URL}">Otevřít Graf</a>'
    )

    # 3. ZISKANI OPEN PRICE (Zkousime az 2 minuty v cyklu)
    initial_price = None
    for attempt in range(20): # 20 pokusu po 6s = 2 minuty
        initial_price = get_price()
        if initial_price:
            print(f"[+] Prvni cena ziskana: {initial_price}")
            break
        print(f"[*] Pokus {attempt+1}: Par {SYMBOL}USDT jeste neni k dispozici...")
        time.sleep(6)

    if not initial_price:
        send_telegram(f"⚠️ <b>{SYMBOL}</b>: Ani po 2 minutách se nepodařilo získat cenu z API.")
        return

    # 4. MONITORING CYKLUS
    prices = [initial_price]
    steps = MONITOR_SECS // POLL_SECS
    
    print(f"[*] Start monitoringu na 20 minut...")
    for i in range(steps):
        time.sleep(POLL_SECS)
        p = get_price()
        if p:
            prices.append(p)
            print(f"   [{i*POLL_SECS//60}min] Aktuální: {p}")
        else:
            print(f"   [{i*POLL_SECS//60}min] API vypadek, preskakuji...")

    # 5. FINALNI VYHODNOCENI
    max_p = max(prices)
    min_p = min(prices)
    final_p = prices[-1]
    
    max_g = (max_p - initial_price) / initial_price * 100
    final_g = (final_p - initial_price) / initial_price * 100
    
    emoji = "🚀" if max_g > 20 else "📈" if max_g > 0 else "📉"
    
    report = (
        f"{emoji} <b>{SYMBOL}/USDT – Report (20 min)</b>\n\n"
        f"💰 Open: {fmt_price(initial_price)}\n"
        f"🔝 Max: <b>{fmt_price(max_p)} (+{max_g:.1f}%)</b>\n"
        f"📉 Min: {fmt_price(min_p)}\n"
        f"🏁 Close: {fmt_price(final_p)} ({final_g:+.1f}%)\n\n"
        f'📊 <a href="{CHART_URL}">Zobrazit graf na MEXC</a>'
    )
    
    send_telegram(report)
    print("✅ Hotovo, report odeslan.")

if __name__ == "__main__":
    main()
