# 🪙 MEXC New Listings → Telegram Bot

Automatický scraper, který každý den stáhne budoucí listingy z [MEXC New Listing](https://www.mexc.com/newlisting) a pošle shrnutí přes Telegram bota.

## 📁 Struktura souborů

```
.github/
  workflows/
    mexc-listings.yml   ← GitHub Actions workflow
scripts/
  scrape_mexc.py        ← Scraper + Telegram notifikace
```

## 🚀 Nastavení (krok za krokem)

### 1. Vytvoř Telegram bota

1. Otevři Telegram a napiš **@BotFather**
2. Napiš `/newbot` a vyplň jméno bota
3. BotFather ti dá **token** – vypadá takto: `123456789:ABCdefGhIJKlmNoPQRstuVWXyz`
4. Zapiš si ho!

### 2. Zjisti svoje Chat ID

1. Napiš svému novému botovi `/start`
2. Otevři v prohlížeči: `https://api.telegram.org/bot<TVŮJ_TOKEN>/getUpdates`
3. Najdi `"chat":{"id":123456789}` – to je tvoje **Chat ID**

### 3. Přidej GitHub Secrets

V repozitáři jdi na **Settings → Secrets and variables → Actions → New repository secret**:

| Název | Hodnota |
|-------|---------|
| `TELEGRAM_BOT_TOKEN` | Token od BotFathera |
| `TELEGRAM_CHAT_ID` | Tvoje Chat ID |

### 4. Nahraj soubory do repozitáře

```bash
git add .github/workflows/mexc-listings.yml
git add scripts/scrape_mexc.py
git commit -m "feat: MEXC listings scraper with Telegram notifications"
git push
```

### 5. Spusť ručně (test)

1. Jdi na **Actions** tab v repozitáři
2. Klikni na **🪙 MEXC New Listings Scraper**
3. Klikni na **Run workflow** → **Run workflow**

## ⏰ Automatické spouštění

Workflow se spouští automaticky každý den v **9:00 UTC** (11:00 Praha).

Změnit čas lze v `mexc-listings.yml`:
```yaml
- cron: '0 9 * * *'   # každý den v 9:00 UTC
- cron: '0 */6 * * *' # každých 6 hodin
- cron: '0 9,17 * * *' # v 9:00 a 17:00 UTC
```

## 📱 Ukázka Telegram zprávy

```
🪙 MEXC New Listings
📅 Sken: 2025-01-15 09:00 UTC
✅ Nalezeno celkem: 5 coinů

━━━━━━━━━━━━━━━━━━━━

1. NEWCOIN
   🕐 2025-01-16 10:00 UTC
   ⏳ Za: 1d 1h 0m

2. ALTTOKEN
   🕐 2025-01-17 14:00 UTC
   ⏳ Za: 2d 5h 0m
...
━━━━━━━━━━━━━━━━━━━━
🔗 MEXC New Listing
```

## ⚠️ Poznámky

- MEXC je JavaScript SPA – scraper používá **Playwright** (headless Chromium)
- Stránka může změnit strukturu DOM, v tom případě uprav selektory v `scrape_mexc.py`
- Pokud scraper nic nenajde, pošle zprávu "Žádné nalezeny" a odkaz na ruční kontrolu
