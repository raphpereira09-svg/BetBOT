
## v3 — Blending & Drift (plus sport-aware)
- **Blending**: `blend_prob = (1-α)*consensus + α*adj_prob`, α dépend de la force du signal (news/blessures/forme).
- **Drift filter**: accepte si la cote actuelle ≥ médiane marché (déjà) et ≥ médiane 24h (si `data/odds_history.csv` est disponible).
- **Spécialisation par sport**: caps d'odds/proba + évite l'outsider vs élites (tennis/foot).

### Variables optionnelles
```
ALPHA_MIN=0.20
ALPHA_MAX=0.70
ALPHA_K=0.80
EPS_24H=0.01
MIN_DELTA_EDGE=0.005
TENNIS_MAX_ODDS=2.20
TENNIS_MIN_PROB=0.50
FOOT_MAX_ODDS=2.40
FOOT_MIN_PROB=0.45
BASKET_MAX_ODDS=2.20
BASKET_MIN_PROB=0.52
```
> Pour GitHub Actions, le step **Cache data** persiste `data/odds_history.csv` entre exécutions.
