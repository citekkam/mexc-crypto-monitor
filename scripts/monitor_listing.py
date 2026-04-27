"""
MEXC Listing Price Monitor - v4
"""

import os
import sys
import time
import requests
from datetime import datetime, timezone

SYMBOL             = os.environ.get("COIN_SYMBOL", "")
LISTING_TIME_TS    = int(os.environ.get("LISTING_TIME_TS", "0"))
LISTING_TIME_STR   = os.environ.get("LISTING_TIME_STR", "")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

PRICE_API    = "https://api.mexc.com/api/v3/ticker/price"
CHART_URL    = f"https://www.mexc.com/exchange/{SYMBOL}_USDT"
MONITOR_SECS = 20 * 60
POLL_SECS    = 30


def get_price() -> float | None:
    try:
        r = requests.get(PRICE_API, params={"symbol": f"{SYMBOL}USDT"}, timeout=10)
        if r.status_code == 200:
            p = float(r.json().get("price", 0))
            return p if p > 0 else None
        print(f"[!] Price API {r.status_code}: {r.text[:100]}")
    except Exception as e:
        print(f"[!] Price fetch error: {e}")
    return None


def wait_for_price(max_wait_secs: int = 120) -> float | None:
    deadline = time.time() + max_wait_secs
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        p = get_price()
        if p:
            print(f"[+] Price available after {attempt} attempt(s): {fmt_price(p)}")
            return p
        print(f"[*] Waiting for {SYMBOL}USDT pair... (attempt {attempt})")
        time.sleep(6)
    return None


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": False,
        }, timeout=15)
        r.raise_for_status()
        print(f"[+] Telegram OK: {text[:80].strip()}...")
    except Exception as e:
        print(f"[!] Telegram error: {e}")


def fmt_price(p: float) -> str:
    if p < 0.000001: return f"${p:.10f}"
    if p < 0.001:    return f"${p:.8f}"
    if p < 1:        return f"${p:.6f}"
    return f"${p:.4f}"


def format_result(ip, max_p, min_p, final_p) -> str:
    max_g = (max_p  - ip) / ip * 100
    max_d = (min_p  - ip) / ip * 100
    final = (final_p - ip) / ip * 100
    emoji = ("🚀🚀🚀" if max_g >= 100 else "🚀🚀" if max_g >= 50 else
             "🚀"    if max_g >= 20  else "📈"   if max_g >= 5  else
             "➡️"    if max_g >= 0   else "📉")
    return (
        f"{emoji} <b>{SYMBOL}/USDT – 20min Report</b>\n\n"
        f"📅 Listed: {LISTING_TIME_STR}\n\n"
        f"💰 <b>Ceny:</b>\n"
        f"   Open:  {fmt_price(ip)}\n"
        f"   Max:   {fmt_price(max_p)}  (<b>{max_g:+.1f}%</b>)\n"
        f"   Min:   {fmt_price(min_p)}  ({max_d:+.1f}%)\n"
        f"   Close: {fmt_price(final_p)}  ({final:+.1f}%)\n\n"
        f"📊 <b>Max zhodnocení za 20 min: {max_g:+.1f}%</b>\n\n"
        f'🔗 <a href="{CHART_URL}">Graf {SYMBOL}/USDT</a>'
    )


def main():
    print("="*50)
    print(f"MEXC Monitor v4 – {SYMBOL}")
    print(f"Listing: {LISTING_TIME_STR} (ts={LISTING_TIME_TS})")
    print("="*50)

    if not SYMBOL or os.environ.get("LISTING_TIME_TS", "") == "":
        print("[!] COIN_SYMBOL or LISTING_TIME_TS not set!")
        sys.exit(1)

    # Sleep until listing time
    now_ts = int(time.time())
    sleep_secs = LISTING_TIME_TS - now_ts
    if sleep_secs > 0:
        print(f"[*] Sleeping {sleep_secs}s ({sleep_secs//60}m {sleep_secs%60}s) until listing...")
        time.sleep(sleep_secs)
    else:
        print(f"[*] Past listing time by {-sleep_secs}s — starting immediately")

    print(f"\n[*] Listing time reached!")
    print(f"[*] Sending launch notification to Telegram...")
    send_telegram(
        f"🔔 <b>{SYMBOL} právě listoval na MEXC!</b>\n\n"
        f"📊 Spouštím 20min monitoring ceny...\n"
        f"📅 {LISTING_TIME_STR}\n"
        f'🔗 <a href="{CHART_URL}">Graf {SYMBOL}/USDT</a>'
    )

    print(f"[*] Waiting for {SYMBOL}USDT to become tradeable (up to 2 min)...")
    initial_price = wait_for_price(max_wait_secs=120)
    if not initial_price:
        print(f"[!] Price never became available")
        send_telegram(f"⚠️ <b>{SYMBOL}</b> – cena nedostupná ani 2 minuty po listingu.")
        return

    steps = MONITOR_SECS // POLL_SECS
    print(f"[*] Starting 20 min monitoring — {steps} samples every {POLL_SECS}s")
    prices = [initial_price]

    for i in range(steps):
        time.sleep(POLL_SECS)
        p = get_price()
        elapsed_min = (i + 1) * POLL_SECS // 60
        if p:
            prices.append(p)
            pct = (p - initial_price) / initial_price * 100
            print(f"  [{elapsed_min:2d}min] {fmt_price(p)}  ({pct:+.1f}%)  peak={fmt_price(max(prices))}")
        else:
            print(f"  [{elapsed_min:2d}min] fetch failed, skipping")

    print(f"\n[*] Done. {len(prices)} samples collected")
    print(f"    Open={fmt_price(initial_price)}  Max={fmt_price(max(prices))}  "
          f"Min={fmt_price(min(prices))}  Close={fmt_price(prices[-1])}")
    print(f"[*] Sending final report to Telegram...")

    msg = format_result(initial_price, max(prices), min(prices), prices[-1])
    send_telegram(msg)
    print("✅ Done!")


if __name__ == "__main__":
    main()
