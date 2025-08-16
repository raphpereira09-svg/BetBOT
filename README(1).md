# Telegram Value Bet Bot — v3 (Blending + Drift + Sport-aware)

Bot Telegram qui envoie chaque jour des **paris secs** (cote ≥ 1.30) en s’appuyant sur **The Odds API** et une stratégie v3 plus intelligente :
- **Blending (shrinkage)** : `blend_prob = (1-α)*consensus + α*adj_prob` (α dépend de la force du signal news/blessures/forme).
- **Filtre de drift** : on retient si la cote actuelle ≥ **médiane du marché** ET ≥ **médiane des 24h** (si l’historique local est dispo).
- **Règles par sport** (tennis/foot/basket) pour éviter les upsets aberrants.
- **Garde-fous marché** : ≥ *N* bookmakers, prix ≥ médiane marché, fenêtre horaire, edge dynamique plus strict sur petites cotes.
- **Mise conseillée** : Kelly fractionnel.

> ⚠️ Ce bot est un outil d’aide à la décision. **Aucune garantie** de gain. Parie de façon responsable.

---

## 🚀 Deux façons de l’utiliser

### A) 100% gratuit avec **GitHub Actions** (recommandé pour l’envoi quotidien)
1. Pousse ces fichiers sur **GitHub** (branche `main`) :  
   `cron_send.py`, `odds_providers.py`, `signals.py`, `strategy.py`, `history.py`, `requirements.txt`, `.github/workflows/daily.yml`.
2. Dans ton repo : **Settings → Secrets and variables → Actions** → crée **3 secrets** :
   - `TELEGRAM_BOT_TOKEN` – token BotFather (ex. `123456789:AA...`)
   - `TELEGRAM_CHAT_ID` – ton chat id (ex. `123456789` ou `-100123…` pour un groupe)
   - `ODDS_API_KEY` – clé The Odds API
3. Onglet **Actions** → **Daily picks (v3)** → **Run workflow** (test immédiat).  
   Le cron par défaut est `08:00 UTC` (~ **10:00 Paris** l’été).

### B) En **local** (PC/Mac) pour tester ou utiliser le bot complet (polling Telegram)
```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                # remplis tes clés
python bot.py                       # mode bot Telegram (polling + envoi quotidien)
# ou pour un envoi unique sans polling :
python cron_send.py
```
Dashboard local (optionnel) :  
```bash
streamlit run streamlit_app.py
```

---

## 🧩 Fichiers principaux

- `cron_send.py` — envoi **one-shot** (idéal pour GitHub Actions).
- `bot.py` — bot Telegram complet (polling commandes + job quotidien). *(Optionnel si tu n’utilises que GitHub Actions)*
- `odds_providers.py` — intégration **The Odds API** (v4) + stats marché (médiane, n_books).
- `signals.py` — signaux (news/blessures/forme) + **blending α**.
- `strategy.py` — **sélection v3** (market-aware, drift, sport-aware).
- `history.py` — historique local des médianes pour le **drift 24h**.
- `.github/workflows/daily.yml` — workflow **Daily picks (v3)**.
- `requirements.txt` — dépendances Python.
- `.env.example` — variables d’exemple pour usage local.
- `data/` — dossiers CSV (journal, signaux, history).

---

## 🔧 Variables utiles (défauts sûrs)
Tu peux les définir :
- en **secrets Actions** (sensibles) et/ou dans `daily.yml` (non sensibles),
- en local via `.env`.

### Générales
```
TIMEZONE=Europe/Paris
MIN_ODDS=1.30
MIN_EDGE=0.025         # 0.03 si tu veux plus strict
MAX_BETS=3
BANKROLL_START=100
KELLY_FRACTION=0.25    # 0.15 pour être plus prudent
MIN_BOOKS=3            # nb mini de bookmakers cotant l’issue
MIN_START_MINUTES=60   # pas de match qui démarre < 60 min
MAX_START_HOURS=36     # pas de match à > 36 h
```

### Blending & Drift (v3)
```
ALPHA_MIN=0.20
ALPHA_MAX=0.70
ALPHA_K=0.80
MIN_DELTA_EDGE=0.005   # l’ajustement doit apporter ≥ 0.5% d’edge
EPS_24H=0.01           # cote actuelle ≥ médiane 24 h +1% (si history présent)
```

### Caps par sport (anti-upsets)
```
TENNIS_MAX_ODDS=2.20
TENNIS_MIN_PROB=0.50
FOOT_MAX_ODDS=2.40
FOOT_MIN_PROB=0.45
BASKET_MAX_ODDS=2.20
BASKET_MIN_PROB=0.52
```

### The Odds API
```
ODDS_API_KEY=...
ODDS_REGIONS=eu
ODDS_MARKETS=h2h
ODDS_FORMAT=decimal
ODDS_DATE_FORMAT=iso
# ODDS_SPORTS= (optionnel, ex: soccer_france_ligue_1,basketball_nba,tennis_atp)
# ODDS_BOOKMAKERS= (optionnel, ex: pinnacle,betfair,williamhill)
ODDS_INCLUDE_LINKS=false
```

---

## 🧠 Stratégie v3 (en bref)
1) **Consensus marché** (vig retiré) + **signaux** (news/blessures/forme) → `adj_prob`.  
2) **Blending** : `blend_prob = (1-α)*consensus + α*adj_prob`, α ∈ [ALPHA_MIN, ALPHA_MAX], proportionnel à la force du signal.  
3) **Market checks** : ≥ `MIN_BOOKS`, **prix ≥ médiane** (tennis: +2 %, autres: +1 %).  
4) **Drift 24h** : prix ≥ **médiane 24 h** × (1 + `EPS_24H`) si l’historique existe.  
5) **Edge** : seuil global `MIN_EDGE` + **seuil dynamique** selon la cote (plus strict pour 1.30–1.45).  
6) **Sport-aware** : caps d’odds/proba, évite l’outsider vs **élites** (liste interne tennis/foot).  
7) **Tri final** : EV puis edge puis cote.

---

## 🆘 Dépannage rapide
- **Rien ne s’envoie (Actions)** : vérifie les **3 secrets** et les logs “Run daily sender”.  
- **0 sélection** : clé API, quotas, pas de matchs, filtres trop stricts (`MIN_BOOKS`, `MIN_EDGE`, caps).  
- **Sélections trop “fantaisistes”** : durcis les caps/proba mini, augmente `MIN_EDGE`, `MIN_BOOKS`.  
- **Chat ID** : parle au bot (`/start`) et lis `https://api.telegram.org/bot<token>/getUpdates` → "chat" → "id".

---

## 📄 Licence & responsabilité
Code fourni **à titre éducatif**. L’auteur ne garantit aucun résultat et n’endosse aucune responsabilité sur les pertes potentielles. Pariez de manière responsable.

— Généré le 2025-08-16.
