from __future__ import annotations
import os, requests
import pandas as pd

API_BASE = "https://api.the-odds-api.com/v4"

class OddsApiError(RuntimeError):
    pass

def _iter_api_keys():
    """Yield API keys from env: ODDS_API_KEYS (semicolon-separated) then ODDS_API_KEY."""
    keys = []
    multi = os.environ.get("ODDS_API_KEYS")
    if multi:
        keys.extend([k.strip() for k in multi.split(";") if k.strip()])
    single = os.environ.get("ODDS_API_KEY") or os.environ.get("THEODDS_API_KEY")
    if single:
        keys.append(single.strip())
    # de-dup while preserving order
    seen = set(); out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k); out.append(k)
    return out

def _handle_response(r, sport_label):
    if r.status_code == 200:
        try:
            return r.json()
        except Exception as e:
            raise OddsApiError(f"[{sport_label}] JSON parse error: {e}")
    try:
        detail = r.json()
    except Exception:
        detail = r.text[:400]
    if r.status_code in (401, 403):
        raise OddsApiError(f"[{sport_label}] Auth error {r.status_code}. Details: {detail}")
    if r.status_code == 429:
        remaining = r.headers.get("x-requests-remaining")
        used = r.headers.get("x-requests-used")
        allowed = r.headers.get("x-requests-allowed")
        raise OddsApiError(f"[{sport_label}] Rate limit 429. Remaining={remaining}, Used={used}, Allowed={allowed}")
    raise OddsApiError(f"[{sport_label}] HTTP {r.status_code}: {detail}")

def _call_endpoint(url, params, sport_label):
    """Try all keys in order until one succeeds."""
    last_err = None
    for key in _iter_api_keys() or [None]:
        if not key:
            raise OddsApiError("Missing ODDS_API_KEY (and no ODDS_API_KEYS).")
        params = dict(params)  # copy
        params["apiKey"] = key
        r = requests.get(url, params=params, timeout=25)
        if r.status_code == 200:
            return r.json()
        else:
            try:
                _handle_response(r, sport_label)
            except OddsApiError as e:
                last_err = e
                # try next key on 401/429/403; otherwise fail fast
                if r.status_code not in (401, 403, 429):
                    raise
                continue
    # if we reach here, all keys failed
    raise last_err or OddsApiError("Unknown error while contacting The Odds API.")

def _row_h2h(mid, league, teams, start, book_key, out, price, home, away):
    return {
        "match_id": mid,"sport":"football","league":league,"teams":teams,"start_time_iso":start,
        "market":"h2h","outcome":out,"point": float('nan'),"book":book_key,"price":float(price),
        "book_home":home,"book_away":away
    }

def _row_totals(mid, league, teams, start, book_key, out, price, pt, home, away):
    try:
        pt = float(pt)
    except Exception:
        pt = float("nan")
    return {
        "match_id": mid,"sport":"football","league":league,"teams":teams,"start_time_iso":start,
        "market":"totals","outcome":out,"point": pt,"book":book_key,"price":float(price),
        "book_home":home,"book_away":away
    }

def fetch_soccer_odds(debug: bool=False) -> pd.DataFrame:
    """Fetch odds for soccer using one of two modes:
       - Default (efficient): if ODDS_USE_UPCOMING="1", call /sports/upcoming/odds ONCE then filter by leagues
       - Classic: loop over each league in ODDS_SPORTS and call /sports/{league}/odds (more requests)
       Supports multi-key failover via ODDS_API_KEYS="key1;key2" (tries next key on 401/403/429).
    """
    regions = os.environ.get("ODDS_REGIONS", "eu,uk")
    odds_format = os.environ.get("ODDS_FORMAT", "decimal")
    date_format = os.environ.get("ODDS_DATE_FORMAT", "iso")
    use_upcoming = os.environ.get("ODDS_USE_UPCOMING","1") == "1"

    sports_env = os.environ.get("ODDS_SPORTS")
    if sports_env:
        wanted = [s.strip() for s in sports_env.split(",") if s.strip()]
    else:
        wanted = ["soccer_epl","soccer_france_ligue_1","soccer_spain_la_liga","soccer_italy_serie_a","soccer_germany_bundesliga"]

    rows = []
    if use_upcoming:
        # Single call, then filter
        url = f"{API_BASE}/sports/upcoming/odds"
        params = {"regions": regions, "markets": "h2h,totals", "oddsFormat": odds_format, "dateFormat": date_format}
        events = _call_endpoint(url, params, "upcoming")
        counts = {}
        for ev in events:
            league = ev.get("sport_key","") or ""
            if not league.startswith("soccer_"):
                continue
            if league not in wanted:
                continue
            counts[league] = counts.get(league,0) + 1
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
                            if nm in (home.lower(), "home", "1"): out = "home"
                            elif nm in (away.lower(), "away", "2"): out = "away"
                            elif nm in ("draw","x","tie"): out = "draw"
                            else:
                                if home.lower() in nm: out = "home"
                                elif away.lower() in nm: out = "away"
                                else: out = nm
                            price = oc.get("price"); 
                            try: price = float(price)
                            except Exception: continue
                            rows.append(_row_h2h(mid, league, teams, start, book_key, out, price, home, away))
                    elif mkey == "totals":
                        for oc in m.get("outcomes", []):
                            out = str(oc.get("name","")).lower()
                            price = oc.get("price")
                            try: price = float(price)
                            except Exception: continue
                            rows.append(_row_totals(mid, league, teams, start, book_key, out, price, oc.get("point"), home, away))
        if debug:
            print("DEBUG upcoming counts per league:", counts)
    else:
        counts = {}
        for sport in wanted:
            url = f"{API_BASE}/sports/{sport}/odds"
            params = {"regions": regions, "markets": "h2h,totals", "oddsFormat": odds_format, "dateFormat": date_format}
            events = _call_endpoint(url, params, sport)
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
                                if nm in (home.lower(), "home", "1"): out = "home"
                                elif nm in (away.lower(), "away", "2"): out = "away"
                                elif nm in ("draw","x","tie"): out = "draw"
                                else:
                                    if home.lower() in nm: out = "home"
                                    elif away.lower() in nm: out = "away"
                                    else: out = nm
                                price = oc.get("price")
                                try: price = float(price)
                                except Exception: continue
                                rows.append(_row_h2h(mid, league, teams, start, book_key, out, price, home, away))
                        elif mkey == "totals":
                            for oc in m.get("outcomes", []):
                                out = str(oc.get("name","")).lower()
                                price = oc.get("price")
                                try: price = float(price)
                                except Exception: continue
                                rows.append(_row_totals(mid, league, teams, start, book_key, out, price, oc.get("point"), home, away))
        if debug:
            print("DEBUG per-sport counts:", counts)

    cols = ["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"]
    return pd.DataFrame(rows, columns=cols)
