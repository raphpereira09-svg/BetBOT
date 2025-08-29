from __future__ import annotations
import os, requests
import pandas as pd
API_BASE = "https://api.the-odds-api.com/v4"
def fetch_soccer_odds() -> pd.DataFrame:
    api_key = os.environ.get("ODDS_API_KEY") or os.environ.get("THEODDS_API_KEY")
    if not api_key: raise RuntimeError("Set ODDS_API_KEY")
    regions = os.environ.get("ODDS_REGIONS", "eu,uk,us,au")
    odds_format = os.environ.get("ODDS_FORMAT", "decimal")
    date_format = os.environ.get("ODDS_DATE_FORMAT", "iso")
    sports_env = os.environ.get("ODDS_SPORTS")
    if sports_env:
        sport_keys = [s.strip() for s in sports_env.split(",") if s.strip().startswith("soccer_")]
    else:
        sport_keys = ["soccer_epl","soccer_france_ligue_1","soccer_spain_la_liga","soccer_italy_serie_a","soccer_germany_bundesliga","upcoming"]
    rows = []
    for sport in sport_keys:
        url = f"{API_BASE}/sports/{sport}/odds"
        params = {"apiKey": api_key, "regions": regions, "markets": "h2h,totals", "oddsFormat": odds_format, "dateFormat": date_format}
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 429: break
            r.raise_for_status()
            events = r.json()
        except Exception:
            continue
        for ev in events:
            league = ev.get("sport_key","")
            if not str(league).startswith("soccer_"): continue
            home = ev.get("home_team",""); away = ev.get("away_team","")
            teams = f"{home} vs {away}".strip()
            start = ev.get("commence_time",""); mid = ev.get("id","")
            bms = ev.get("bookmakers", [])
            for b in bms:
                book_key = b.get("key","")
                for m in b.get("markets", []):
                    mkey = m.get("key")
                    if mkey == "h2h":
                        for oc in m.get("outcomes", []):
                            nm = str(oc.get("name","")).lower()
                            if nm in (home.lower(), "home", "1"): out = "home"
                            elif nm in (away.lower(), "away", "2"): out = "away"
                            elif nm in ("draw","x","tie"): out = "draw"
                            else:
                                if home.lower() in nm: out = "home"
                                elif away.lower() in nm: out = "away"
                                else: out = nm
                            price = float(oc.get("price"))
                            rows.append({"match_id": mid,"sport":"football","league":league,"teams":teams,"start_time_iso":start,"market":"h2h","outcome":out,"point": float('nan'),"book":book_key,"price":price,"book_home":home,"book_away":away})
                    elif mkey == "totals":
                        for oc in m.get("outcomes", []):
                            out = str(oc.get("name","")).lower(); price = float(oc.get("price"))
                            pt = oc.get("point", None)
                            try: pt = float(pt)
                            except Exception: pt = float("nan")
                            rows.append({"match_id": mid,"sport":"football","league":league,"teams":teams,"start_time_iso":start,"market":"totals","outcome":out,"point":pt,"book":book_key,"price":price,"book_home":home,"book_away":away})
    cols = ["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"]
    return pd.DataFrame(rows, columns=cols)
