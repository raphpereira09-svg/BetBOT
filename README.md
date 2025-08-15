# Telegram Value Bet Alert Bot — Odds API Ready

Bot Telegram autonome qui:
- récupère les **cotes** via **The Odds API**,
- calcule une proba **consensus** (vig retiré) et l'ajuste avec **news/blessures/forme**,
- filtre les **paris secs** (cote ≥ `MIN_ODDS`, défaut 1.30),
- sélectionne selon **edge/EV**, recommande une **mise (Kelly fractionnel)**,
- envoie des **alertes Telegram** joliment formatées,
- journalise, permet de **solder** les paris, et fournit un **dashboard**.

## 1) Installation locale

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# édite .env avec tes clés (Telegram + The Odds API)
python bot.py
```

Commandes Telegram: `/today`, `/bankroll`, `/setbankroll 200`, `/setedge 0.03`, `/setkelly 0.25`, `/setmaxbets 3`, `/settle <id> <selection> <win|loss|push> [cote]`.

## 2) Variables .env (essentiel)

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TIMEZONE=Europe/Paris
ALERT_HOUR=10

ODDS_API_KEY=...
ODDS_REGIONS=eu
ODDS_MARKETS=h2h
ODDS_FORMAT=decimal
ODDS_DATE_FORMAT=iso
ODDS_SPORTS=
ODDS_BOOKMAKERS=
ODDS_INCLUDE_LINKS=false

ENABLE_ODDS_API=1
ODDS_PROVIDER=http

MIN_ODDS=1.30
MIN_EDGE=0.025
KELLY_FRACTION=0.25
MAX_BETS=3
BANKROLL_START=100.0

DATA_DIR=data
STATE_PATH=state.json
```

## 3) Journal & Dashboard

- Les alertes écrivent dans `data/journal.csv` (`status=open`).  
- `/settle` met à jour `result`, calcule la **PNL**, met à jour la **bankroll** dans `state.json` et note `bankroll_before/after`.  
- Dashboard : `streamlit run streamlit_app.py` (filtre, courbe de bankroll, KPIs).

## 4) Déploiement Railway (résumé)

- Service depuis GitHub/ZIP → `Start Command: python bot.py`  
- **Variables**: mêmes que `.env` (et `DATA_DIR=/data` pour persister).  
- **Volume**: monter `/data` pour garder le journal.

## 5) Légal & quotas
- Respecte les CGU et les quotas The Odds API.  
- Le bot **n’automatise pas la mise**, il envoie des **alertes**.

Bon build !
