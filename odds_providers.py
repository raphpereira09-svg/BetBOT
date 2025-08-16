from __future__ import annotations
import os, requests
import pandas as pd

API_BASE = "https://api.the-odds-api.com/v4"

def _decimal_to_prob(odds: float) -> float:
    return 1.0/odds if odds>1.0 else 1.0

def _normalize(imps):
    s = sum(imps)
    return [x/s for x in imps] if s>0 else [0 for x in imps]

def _sport_family(sport_key: str) -> str:
    if sport_key.startswith("soccer_"): return "football"
    if sport_key.startswith("basketball_"): return "basketball"
    if sport_key.startswith("tennis_"): return "tennis"
    return sport_key.split("_",1)[0]

def _best_price_and_book(outcomes: list[dict]) -> dict[str, tuple[str,float]]:
    best = {}
    for o in outcomes:
        name = o.get("name")
        price = float(o.get("price"))
        book = o.get("_book_key","")
        if not name: continue
        if name not in best or price > best[name][1]:
            best[name] = (book, price)
    return best

def _consensus_probs(bookmakers: list[dict]) -> dict[str, float]:
    bucket = {}
    for b in bookmakers:
        for m in b.get("markets", []):
            if m.get("key") != "h2h": continue
            names, imps = [], []
            for oc in m.get("outcomes", []):
                names.append(oc.get("name"))
                imps.append(_decimal_to_prob(float(oc.get("price"))))
            if not names: continue
            norm = _normalize(imps)
            for name, p in zip(names, norm):
                bucket.setdefault(name, []).append(p)
    consensus = {}
    for name, arr in bucket.items():
        arr = sorted(arr)
        mid = len(arr)//2
        med = arr[mid] if len(arr)%2==1 else 0.5*(arr[mid-1]+arr[mid])
        consensus[name] = med
    tot = sum(consensus.values())
    if tot>0:
        for k in consensus: consensus[k] /= tot
    return consensus

def _outcome_stats(tagged: list[dict]) -> tuple[dict[str, float], dict[str, int]]:
    bucket = {}
    for oc in tagged:
        name = oc.get("name")
        price = float(oc.get("price", 0) or 0)
        if name and price:
            bucket.setdefault(name, []).append(price)
    med, n = {}, {}
    for name, arr in bucket.items():
        arr = sorted(arr)
        m = arr[len(arr)//2] if len(arr)%2==1 else 0.5*(arr[len(arr)//2-1]+arr[len(arr)//2])
        med[name] = m
        n[name] = len(arr)
    return med, n

def fetch_sports_list(api_key: str) -> list[dict]:
    url = f"{API_BASE}/sports/?apiKey={api_key}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def _resolve_sports_to_query(api_key: str, sports_env: str | None) -> list[str]:
    if sports_env:
        return [s.strip() for s in sports_env.split(",") if s.strip()]
    preferred = ["upcoming","soccer_france_ligue_1","soccer_epl","soccer_uefa_champions_league","basketball_nba","basketball_euroleague","tennis_atp","tennis_wta"]
    try:
        sports = fetch_sports_list(api_key)
        keys = {s["key"] for s in sports if s.get("active", False)}
        chosen = [k for k in preferred if k in keys]
        return chosen or ["upcoming"]
    except Exception:
        return ["upcoming"]

def fetch_today_odds_http(sports: list[str] | None = None) -> pd.DataFrame:
    api_key = os.environ.get("ODDS_API_KEY") or os.environ.get("THEODDS_API_KEY")
    if not api_key:
        raise RuntimeError("Set ODDS_API_KEY in environment")
    regions = os.environ.get("ODDS_REGIONS", "eu,uk,us,au")
    markets = os.environ.get("ODDS_MARKETS", "h2h")
    date_format = os.environ.get("ODDS_DATE_FORMAT", "iso")
    odds_format = os.environ.get("ODDS_FORMAT", "decimal")
    bookmakers = os.environ.get("ODDS_BOOKMAKERS", "").strip()
    include_links = os.environ.get("ODDS_INCLUDE_LINKS", "false").lower()

    sports = sports or _resolve_sports_to_query(api_key, os.environ.get("ODDS_SPORTS"))
    rows = []
    for sport in sports:
        params = {"apiKey": api_key, "regions": regions, "markets": markets, "oddsFormat": odds_format, "dateFormat": date_format}
        if bookmakers: params["bookmakers"] = bookmakers
        if include_links in ("true","false"): params["includeLinks"] = include_links
        url = f"{API_BASE}/sports/{sport}/odds"
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 429: break
            r.raise_for_status()
            events = r.json()
        except Exception:
            continue
        for ev in events:
            sport_key = ev.get("sport_key","")
            sport_family = _sport_family(sport_key)
            home = ev.get("home_team",""); away = ev.get("away_team","")
            teams_str = f"{home} vs {away}".strip()
            commence = ev.get("commence_time")
            bms = ev.get("bookmakers", [])
            tagged = []
            for b in bms:
                bkey = b.get("key","")
                for m in b.get("markets", []):
                    if m.get("key") != "h2h": continue
                    for oc in m.get("outcomes", []):
                        oc2 = dict(oc); oc2["_book_key"] = bkey
                        tagged.append(oc2)
            best = _best_price_and_book(tagged) if tagged else {}
            consensus = _consensus_probs(bms) if bms else {}
            med, nbooks = _outcome_stats(tagged)
            for outcome_name, (book_key, odds) in best.items():
                median_price = float(med.get(outcome_name, float("nan")))
                n_bks = int(nbooks.get(outcome_name, 0))
                rows.append({
                    "match_id": ev.get("id"),
                    "sport": sport_family,
                    "league": sport_key,
                    "teams": teams_str,
                    "start_time_iso": commence,
                    "market": "1X2" if sport_family=="football" else "Moneyline",
                    "outcome": outcome_name,
                    "book": book_key,
                    "book_odds": float(odds),
                    "model_prob": float(consensus.get(outcome_name, 0.0)),
                    "consensus_prob": float(consensus.get(outcome_name, 0.0)),
                    "median_odds": median_price,
                    "n_books": n_bks,
                    "best_vs_median": (float(odds)/median_price if (median_price and median_price>0) else float("nan")),
                })
    cols = ["match_id","sport","league","teams","start_time_iso","market","outcome","book","book_odds","model_prob","consensus_prob","median_odds","n_books","best_vs_median"]
    return pd.DataFrame(rows, columns=cols)
