# MEXC Crypto Monitor 🚀

Automatické sledování nových coinů na MeXC burze pomocí GitHub Actions + Telegram notifikace.

## Co to dělá?

✅ **2x denně** (9:00 a 15:00 CZ) se kontroluje MeXC API na nové coiny  
✅ **Sleduje graf** každého nového coinu 20 minut od spuštění  
✅ **Počítá výkonnost** - jaký je maximální nárůst v těch 20 minutách  
✅ **Pošle Telegram** zprávu s detaily okamžitě  
✅ **Sbírá data celý týden**  
✅ **V neděli** pošle kompletní shrnutí se všemi novými coiny a jejich výkonností  

---

## Instalace (5 minut)

### 1️⃣ Zkopíruj soubory do GitHubu

Ke stažení jsem ti připravil:
- `mexc_monitor.py` - Python skript
- `schedule.yml` - GitHub Actions workflow
- `requirements.txt` - Dependencies

**Postup:**
1. Jdi do svého repo `citekkam/mexc-crypto-monitor`
2. Klikni **Add file → Create new file**
3. Cestu piš: `.github/workflows/schedule.yml` a zkopíruj obsah `schedule.yml`
4. Klikni **Commit**
5. Stejně přidej `mexc_monitor.py` v root adresáři
6. Stejně přidej `requirements.txt` v root adresáři

### 2️⃣ Ověř GitHub Secrets

Měly bys je mít už zadané:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MEXC_ACCESS_KEY`
- `MEXC_SECRET_KEY`

Zkontroluj v **Settings → Secrets and variables → Actions**

### 3️⃣ Povolení GitHub Actions

1. Jdi do **Settings → Actions → General**
2. Vyber **Allow all actions and reusable workflows**
3. Klikni **Save**

### 4️⃣ Ověř timezone

Skript je nastaven na 9:00 a 15:00 CZ čas. GitHub Actions běží v UTC, proto jsou cron joby nastavené na:
- **7:00-8:00 UTC** (9:00 CZ)
- **13:00-14:00 UTC** (15:00 CZ)

Pokud chceš jiný čas, uprav `schedule.yml` (cron formát).

---

## Cron časy

```
# 9:00 CZ (změňuje se podle letního/zimního času)
- cron: '0 7 * * *'  # Zima (UTC+1)
- cron: '0 8 * * *'  # Léto (UTC+2)

# 15:00 CZ
- cron: '0 13 * * *'  # Zima
- cron: '0 14 * * *'  # Léto
```

---

## Jak to funguje?

### Kontrola nových coinů (9:00 & 15:00)
1. Skript zavolá MEXC API `/api/v3/defaultSymbols`
2. Najde coiny spuštěné v poslední hodině
3. Pro každý coin:
   - Čeká 20 minut
   - Stáhne cenový graf (1min kandly)
   - Spočítá: `((max_cena - start_cena) / start_cena) * 100`
   - Pošle Telegram zprávu

### Ukládání dat
- Každý nový coin se uloží do `weekly_data.json`
- Data se commitují do GitHubu (aby se neztratila)

### Nedělní report (neděle 18:00 UTC ≈ 19:00 nebo 20:00 CZ)
- Skript spočítá všechny coiny z týdne
- Pošle na Telegram shrnutí:
  - Počet nových coinů
  - Seznam s jednotlivými výkonnostmi
  - Průměrný nárůst
- Resetuje data pro nový týden

---

## Telegram zprávy

### Denní notifikace
```
🔥 Nový coin: BTC/USDT

📈 Nárůst (20 min): +15.42%
Cena otevření: $0.00001234
Max cena: $0.00001425
```

### Nedělní report
```
📊 Nedělní Report - MEXC

Týden od: 2024-12-01
Počet nových coinů: 12

BTC2/USDT
  🚀 Spuštěno: 2024-12-02 14:30
  📈 Max nárůst (20 min): +18.54%

ETH2/USDT
  🚀 Spuštěno: 2024-12-03 09:15
  📈 Max nárůst (20 min): +12.33%

...

Průměrný nárůst: +15.12%
```

---

## Kontrola stavu

1. Jdi do repo → **Actions**
2. Vidíš všechny spuštění
3. Klikni na workflow → Vidíš logs
4. Pokud je 🟢 zelené, je OK. 🔴 červené = chyba

---

## Řešení problémů

### ❌ "API Error" v logu
- Zkontroluj API klíče v Secrets
- Zkontroluj, že nejsou s mezerami

### ❌ Telegram neposílá zprávy
- Zkontroluj token a Chat ID
- Zkontroluj, že sis napsal zprávu botovi (`/start`)

### ❌ Workflow se nespustil
- Jdi do **Settings → Actions → General**
- Vyber "Allow all actions"
- Zkontroluj, že repo je Public (Free tier)

### ⏰ Spouští se v jiný čas
- Cron jobs běží v UTC
- Musíš přepočítat na svůj timezone
- Nebo klikni **Run workflow** tlačítko pro test

---

## Ruční spuštění

Chceš testovat bez čekání?

1. Jdi do **Actions**
2. Vyber **MEXC Crypto Monitor**
3. Klikni **Run workflow → Run workflow**
4. Skript se spustí hned!

---

## Editace skriptu

Pokud chceš něco změnit (čas čekání, počet minut, formát zprávy...):

1. Jdi do `mexc_monitor.py`
2. Klikni ✏️ (edit)
3. Změn to, co chceš
4. Klikni **Commit changes**

---

## Bezpečnost

⚠️ **NIKDY** nezveřejňuj API klíče v kódu!

- Máš je v GitHub Secrets ✅
- Skript je čte z `os.getenv()` ✅
- Logs si je neukazují ✅

---

## Kolik to stojí?

- GitHub Actions: **ZDARMA** (3000 minut/měsíc)
- MeXC API: **ZDARMA**
- Telegram: **ZDARMA**

**Total: $0**

---

## Support

Pokud ti něco nefunguje:
1. Zkontroluj Actions → logs
2. Zkontroluj GitHub Secrets
3. Zkontroluj, že repo je Public
4. Zkontroluj, že Actions jsou povolené

---

**Postav si to a budou ti chodit notifikace!** 🚀
