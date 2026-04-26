"""
MEXC Listing Price Monitor
- Runs every 5 minutes via GitHub Actions
- Checks data/pending_listings.json for coins that just listed (within last 6 min)
- Monitors price every 30s for 20 minutes
- Sends Telegram report with max gain, chart link, and price history
"""

import os
import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

MEXC_URL = "https://www.mexc.com/newlisting"
LISTINGS_FILE = Path("data/pending_listings.json")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MONITOR_DURATION_SEC = 20 * 60   # 20 minutes
POLL_INTERVAL_SEC = 30            # check price every 30 seconds
TRIGGER_WINDOW_SEC = 6 * 60      # consider coins listed in last 6 min (covers cron drift)

MEXC_PRICE_API = "https://api.mexc.com/api/v3/ticker/price"
MEXC_KLINES_API = "https://api.mexc.com/api/v3/klines"


# ─── Price fetching ───────────────────────────────────────────────────────────

def get_price(symbol: str) -> float | None:
    """Get current price from MEXC public API."""
    try:
        r = requests.get(
            MEXC_PRICE_API,
            params={"symbol": f"{symbol}USDT"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            return float(data["price"])
    except Exception as e:
        print(f"[!] Price fetch error for {symbol}: {e}")
    return None


def get_initial_price(symbol: str, retries: int = 10) -> float | None:
    """Wait up to ~50s for the trading pair to become available."""
    for attempt in range(retries):
        price = get_price(symbol)
        if price and price > 0:
            return price
        print(f"[*] {symbol} not yet tradeable, waiting... ({attempt+1}/{retries})")
        time.sleep(5)
    return None


# ─── Core monitor ─────────────────────────────────────────────────────────────

def monitor_coin(symbol: str, listing_time_str: str) -> dict:
    """Monitor coin price for 20 minutes, return stats."""
    print(f"\n{'='*50}")
    print(f"[*] Monitoring {symbol} for 20 minutes...")
    print(f"{'='*50}")

    initial_price = get_initial_price(symbol)
    if not initial_price:
        print(f"[!] Could not get initial price for {symbol}")
        return {"symbol": symbol, "error": "Price not available at launch"}

    print(f"[+] Initial price: ${initial_price:.8f}")

    prices = [initial_price]
    timestamps = [datetime.now(tz=timezone.utc)]
    max_price = initial_price
    min_price = initial_price
    checks = MONITOR_DURATION_SEC // POLL_INTERVAL_SEC

    for i in range(checks):
        time.sleep(POLL_INTERVAL_SEC)
        price = get_price(symbol)
        if price:
            prices.append(price)
            timestamps.append(datetime.now(tz=timezone.utc))
            max_price = max(max_price, price)
            min_price = min(min_price, price)
            elapsed_min = (i + 1) * POLL_INTERVAL_SEC // 60
            pct = (price - initial_price) / initial_price * 100
            print(f"  [{elapsed_min:2d}min] ${price:.8f}  ({pct:+.1f}%)")

    max_gain_pct = (max_price - initial_price) / initial_price * 100
    max_drop_pct = (min_price - initial_price) / initial_price * 100
    final_price = prices[-1] if prices else initial_price
    final_pct = (final_price - initial_price) / initial_price * 100

    return {
        "symbol": symbol,
        "listing_time_str": listing_time_str,
        "initial_price": initial_price,
        "max_price": max_price,
        "min_price": min_price,
        "final_price": final_price,
        "max_gain_pct": max_gain_pct,
        "max_drop_pct": max_drop_pct,
        "final_pct": final_pct,
        "num_samples": len(prices),
        "chart_url": f"https://www.mexc.com/exchange/{symbol}_USDT",
    }


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": False,
    }, timeout=15)
    r.raise_for_status()


def format_monitor_result(result: dict) -> str:
    if "error" in result:
        return (
            f"⚠️ <b>{result['symbol']} – Monitor Error</b>\n\n"
            f"{result['error']}"
        )

    symbol = result["symbol"]
    ip = result["initial_price"]
    max_g = result["max_gain_pct"]
    max_d = result["max_drop_pct"]
    final = result["final_pct"]

    # Emoji based on performance
    if max_g >= 100:
        perf_emoji = "🚀🚀🚀"
    elif max_g >= 50:
        perf_emoji = "🚀🚀"
    elif max_g >= 20:
        perf_emoji = "🚀"
    elif max_g >= 5:
        perf_emoji = "📈"
    elif max_g >= 0:
        perf_emoji = "➡️"
    else:
        perf_emoji = "📉"

    def fmt_price(p):
        if p < 0.000001:
            return f"${p:.10f}"
        elif p < 0.001:
            return f"${p:.8f}"
        elif p < 1:
            return f"${p:.6f}"
        else:
            return f"${p:.4f}"

    return (
        f"{perf_emoji} <b>{symbol}/USDT – 20min Report</b>\n\n"
        f"📅 Listed: {result.get('listing_time_str', 'N/A')}\n\n"
        f"💰 <b>Ceny:</b>\n"
        f"   Open:  {fmt_price(ip)}\n"
        f"   Max:   {fmt_price(result['max_price'])}  (<b>+{max_g:.1f}%</b>)\n"
        f"   Min:   {fmt_price(result['min_price'])}  ({max_d:.1f}%)\n"
        f"   Close: {fmt_price(result['final_price'])}  ({final:+.1f}%)\n\n"
        f"📊 <b>Max zhodnocení za 20 min: {max_g:.1f}%</b>\n\n"
        f'🔗 <a href="{result["chart_url"]}">Otevřít graf {symbol}/USDT</a>'
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("MEXC Listing Monitor")
    print(f"Time: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 50)

    if not LISTINGS_FILE.exists():
        print("[*] No listings file found, nothing to monitor")
        return

    listings = json.loads(LISTINGS_FILE.read_text())
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())

    # Find coins that listed within the last TRIGGER_WINDOW_SEC and haven't been monitored
    to_monitor = [
        item for item in listings
        if not item.get("monitored", False)
        and 0 <= (now_ts - item["listing_time_ts"]) <= TRIGGER_WINDOW_SEC
    ]

    if not to_monitor:
        print("[*] No coins to monitor right now")
        # Show upcoming
        upcoming = [
            item for item in listings
            if not item.get("monitored", False) and item["listing_time_ts"] > now_ts
        ]
        if upcoming:
            next_coin = min(upcoming, key=lambda x: x["listing_time_ts"])
            mins_until = (next_coin["listing_time_ts"] - now_ts) // 60
            print(f"[*] Next listing: {next_coin['symbol']} in {mins_until} min")
        return

    print(f"[+] Found {len(to_monitor)} coin(s) to monitor: {[c['symbol'] for c in to_monitor]}")

    # Send Telegram alert that monitoring started
    for coin in to_monitor:
        send_telegram(
            f"🔔 <b>{coin['symbol']} právě listoval na MEXC!</b>\n\n"
            f"📊 Spouštím 20min monitoring ceny...\n"
            f'🔗 <a href="https://www.mexc.com/exchange/{coin["symbol"]}_USDT">'
            f"Graf {coin['symbol']}/USDT</a>"
        )

    # Monitor each coin and collect results
    results = []
    for coin in to_monitor:
        result = monitor_coin(coin["symbol"], coin["listing_time_str"])
        results.append(result)

        # Mark as monitored in the file
        for item in listings:
            if item["symbol"] == coin["symbol"]:
                item["monitored"] = True
                item["monitor_result"] = result
        LISTINGS_FILE.write_text(json.dumps(listings, indent=2))

        # Send result to Telegram
        send_telegram(format_monitor_result(result))
        print(f"[+] Sent result for {coin['symbol']} to Telegram")

    print(f"\n✅ Monitoring complete for {len(results)} coin(s)")


if __name__ == "__main__":
    main()
