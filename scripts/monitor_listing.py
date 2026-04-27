"""
MEXC Listing Price Monitor - v2
Triggered by repository_dispatch from scraper.
Receives symbol + listing_time_ts as env vars.
Sleeps until exact listing time, then polls price every 30s for 20 min.
"""

import os
import time
import requests
from datetime import datetime, timezone

SYMBOL           = os.environ["COIN_SYMBOL"]
LISTING_TIME_TS  = int(os.environ["LISTING_TIME_TS"])
LISTING_TIME_STR = os.environ.get("LISTING_TIME_STR", "")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

MEXC_CHART_URL   = f"https://www.mexc.com/exchange/{SYMBOL}_USDT"
PRICE_API        = "https://api.mexc.com/api/v3/ticker/price"
MONITOR_SECS     = 20 * 60   # 20 minutes
POLL_SECS        = 30


# ─── Price ────────────────────────────────────────────────────────────────────

def get_price() -> float | None:
    try:
        r = requests.get(PRICE_API, params={"symbol": f"{SYMBOL}USDT"}, timeout=10)
        if r.status_code == 200:
            return float(r.json()["price"])
    except Exception:
        pass
    return None


def wait_for_price(retries: int = 20) -> float | None:
    """Wait up to ~2 min for trading pair to become available."""
    for i in range(retries):
        p = get_price()
        if p and p > 0:
            return p
        print(f"[*] Pair not yet available ({i+1}/{retries}), waiting 6s...")
        time.sleep(6)
    return None


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": False,
    }, timeout=15).raise_for_status()


def fmt_price(p: float) -> str:
    if p < 0.000001:  return f"${p:.10f}"
    if p < 0.001:     return f"${p:.8f}"
    if p < 1:         return f"${p:.6f}"
    return f"${p:.4f}"


def format_result(ip, max_p, min_p, final_p) -> str:
    max_g  = (max_p  - ip) / ip * 100
    max_d  = (min_p  - ip) / ip * 100
    final  = (final_p - ip) / ip * 100

    emoji = "🚀🚀🚀" if max_g >= 100 else "🚀🚀" if max_g >= 50 else \
            "🚀"    if max_g >= 20  else "📈"   if max_g >= 5  else \
            "➡️"    if max_g >= 0   else "📉"

    return (
        f"{emoji} <b>{SYMBOL}/USDT – 20min Report</b>\n\n"
        f"📅 Listed: {LISTING_TIME_STR}\n\n"
        f"💰 <b>Ceny:</b>\n"
        f"   Open:  {fmt_price(ip)}\n"
        f"   Max:   {fmt_price(max_p)}  (<b>{max_g:+.1f}%</b>)\n"
        f"   Min:   {fmt_price(min_p)}  ({max_d:+.1f}%)\n"
        f"   Close: {fmt_price(final_p)}  ({final:+.1f}%)\n\n"
        f"📊 <b>Max zhodnocení za 20 min: {max_g:+.1f}%</b>\n\n"
        f'🔗 <a href="{MEXC_CHART_URL}">Graf {SYMBOL}/USDT</a>'
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    sleep_secs = LISTING_TIME_TS - now_ts

    print("="*50)
    print(f"MEXC Monitor – {SYMBOL}")
    print(f"Listing: {LISTING_TIME_STR}")
    print("="*50)

    if sleep_secs > 0:
        print(f"[*] Sleeping {sleep_secs}s until listing time...")
        time.sleep(sleep_secs)
    else:
        print(f"[*] Listing time already passed by {-sleep_secs}s, starting now")

    print(f"\n[*] {SYMBOL} listing time reached!")

    # Notify Telegram that monitoring started
    send_telegram(
        f"🔔 <b>{SYMBOL} právě listoval na MEXC!</b>\n\n"
        f"📊 Spouštím 20min monitoring ceny...\n"
        f'🔗 <a href="{MEXC_CHART_URL}">Graf {SYMBOL}/USDT</a>'
    )

    # Wait for pair to be tradeable
    initial_price = wait_for_price()
    if not initial_price:
        send_telegram(f"⚠️ <b>{SYMBOL}</b> – cena nedostupná ani po 2 minutách od listingu.")
        return

    print(f"[+] Initial price: {fmt_price(initial_price)}")

    # Monitor loop
    prices = [initial_price]
    steps  = MONITOR_SECS // POLL_SECS

    for i in range(steps):
        time.sleep(POLL_SECS)
        p = get_price()
        if p:
            prices.append(p)
            elapsed = (i + 1) * POLL_SECS // 60
            pct = (p - initial_price) / initial_price * 100
            print(f"  [{elapsed:2d}min] {fmt_price(p)}  ({pct:+.1f}%)")

    max_p   = max(prices)
    min_p   = min(prices)
    final_p = prices[-1]

    msg = format_result(initial_price, max_p, min_p, final_p)
    print(f"\n{msg}")
    send_telegram(msg)
    print("✅ Done!")


if __name__ == "__main__":
    main()
