from __future__ import annotations
import os, requests
import pandas as pd

API_BASE = "https://api.the-odds-api.com/v4"

class OddsApiError(RuntimeError):
    pass

def _handle_response(r, sport):
    if r.status_code == 200:
        try:
            return r.json()
        except Exception as e:
            raise OddsApiError(f"[{sport}] JSON parse error: {e}")
    # surface common problems clearly
    try:
        detail = r.json()
    except Exception:
        detail = r.text[:400]
    if r.status_code in (401, 403):
        raise OddsApiError(f"[{sport}] Auth error {r.status_code}. Check ODDS_API_KEY. Details: {detail}")
    if r.status_code == 429:
        remaining = r.headers.get("x-requests-remaining")
        used = r.headers.get("x-requests-used")
        allowed = r.headers.get("x-requests-allowed")
        raise OddsApiError(f"[{sport}] Rate limit 429. Remaining={remaining}, Used={used}, Allowed={allowed}")
    raise OddsApiError(f"[{sport}] HTTP {r.status_code}: {detail}")

def fetch_soccer_odds(debug: bool=False) -> pd.DataFrame:
    api_key = os.environ.get("ODDS_API_KEY") or os.environ.get("THEODDS_API_KEY")
    if not api_key:
        raise OddsApiError("Missing ODDS_API_KEY")
    regions = os.environ.get("ODDS_REGIONS", "eu,uk")
    odds_format = os.environ.get("ODDS_FORMAT", "decimal")
    date_format = os.environ.get("ODDS_DATE_FORMAT", "iso")

    sports_env = os.environ.get("ODDS_SPORTS")
    if sports_env:
        sport_keys = [s.strip() for s in sports_env.split(",") if s.strip()]
    else:
        sport_keys = [
            "soccer_france_ligue_1",
            "soccer_epl",
            "soccer_spain_la_liga",
            "soccer_italy_serie_a",
            "soccer_germany_bundesliga",
        ]

    rows = []
    counts = {}
    for sport in sport_keys:
        url = f"{API_BASE}/sports/{sport}/odds"
        params = {
            "apiKey": api_key,
            "regions": regions,
            "markets": "h2h,totals",
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        r = requests.get(url, params=params, timeout=25)
        events = _handle_response(r, sport)
        counts[sport] = len(events)
        for ev in events:
            league = ev.get("sport_key","")
            if not str(league).startswith("soccer_"):
                continue
            home = ev.get("home_team",""); away = ev.get("away_team","")
            teams = f"{home} vs {away}".strip()
            start = ev.get("commence_time",""); mid = ev.get("id","")
            for b in ev.get("bookmakers", []):
                book_key = b.get("key","")
                for m in b.get("markets", []):
                    mkey = m.get("key")
                    if mkey == "h2h":
                        for oc in m.get("outcomes", []):
                            nm = str(oc.get("name","")).lower()
                            if nm in (home.lower(), "home", "1"):
                                out = "home"
                            elif nm in (away.lower(), "away", "2"):
                                out = "away"
                            elif nm in ("draw","x","tie"):
                                out = "draw"
                            else:
                                if home.lower() in nm: out = "home"
                                elif away.lower() in nm: out = "away"
                                else: out = nm
                            try: price = float(oc.get("price"))
                            except Exception: continue
                            rows.append({
                                "match_id": mid,"sport":"football","league":league,"teams":teams,
                                "start_time_iso":start,"market":"h2h","outcome":out,"point": float('nan'),
                                "book":book_key,"price":price,"book_home":home,"book_away":away
                            })
                    elif mkey == "totals":
                        for oc in m.get("outcomes", []):
                            out = str(oc.get("name","")).lower()
                            try: price = float(oc.get("price"))
                            except Exception: continue
                            pt = oc.get("point", None)
                            try: pt = float(pt)
                            except Exception: pt = float("nan")
                            rows.append({
                                "match_id": mid,"sport":"football","league":league,"teams":teams,
                                "start_time_iso":start,"market":"totals","outcome":out,"point":pt,
                                "book":book_key,"price":price,"book_home":home,"book_away":away
                            })
    if debug:
        print("DEBUG The Odds API — events per sport:", counts)
    cols = ["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"]
    return pd.DataFrame(rows, columns=cols)
