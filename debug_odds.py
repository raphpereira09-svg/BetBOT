# debug_odds.py — quick connectivity & counts check for The Odds API
import os, requests
key = os.environ.get("ODDS_API_KEY") or os.environ.get("THEODDS_API_KEY")
if not key:
    raise SystemExit("❌ Missing ODDS_API_KEY in env.")
regions = os.getenv("ODDS_REGIONS","eu,uk")
sports = os.getenv("ODDS_SPORTS","soccer_france_ligue_1,soccer_epl,soccer_spain_la_liga,soccer_italy_serie_a,soccer_germany_bundesliga").split(",")
print("Using key (masked):", (key[:4] + "***" if key else None))
print("Regions:", regions)
for s in sports:
    url=f"https://api.the-odds-api.com/v4/sports/{s}/odds"
    params={'apiKey':key,'regions':regions,'markets':'h2h,totals','oddsFormat':'decimal','dateFormat':'iso'}
    try:
        r = requests.get(url, params=params, timeout=25)
        rem = r.headers.get("x-requests-remaining"); used = r.headers.get("x-requests-used"); allowed = r.headers.get("x-requests-allowed")
        print(f"\n[{s}] status={r.status_code} remaining={rem} used={used} allowed={allowed}")
        if r.status_code != 200:
            print("Body:", r.text[:400])
            continue
        evs = r.json()
        print("Events:", len(evs))
        if evs:
            sample = evs[0]
            print("Sample teams:", sample.get('home_team'), "vs", sample.get('away_team'))
    except Exception as e:
        print(f"[{s}] EXCEPTION:", e)
