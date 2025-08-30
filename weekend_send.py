\
# weekend_send.py — Rapport week‑end (Top‑5) avec:
# - fenêtre week‑end stricte (ven 00:00 → dim 23:59:59, Europe/Paris) + fallback
# - affichage chrono + scores exacts + meilleur bet
# - et SI trop de matchs => on ne garde que EPL, Bundesliga, La Liga
#
# Variables utiles (env):
#   WEEKEND_MIN_EV (def 0.01)
#   WEEKEND_STRICT (def 1) / WEEKEND_ALLOW_FALLBACK (def 1)
#   TIMEZONE (def Europe/Paris)
#   MAX_MATCHES (def 40)  -> au‑delà, on restreint les ligues
#   LEAGUES_WHEN_TOO_MANY (def "soccer_epl,soccer_germany_bundesliga,soccer_spain_la_liga")
import os, math, requests, pandas as pd, pytz
from datetime import timedelta
from odds_providers import fetch_soccer_odds, OddsApiError
from foot_model import summarize_match
from foot_selector import build_consensus, best_price_and_book

WEEKDAY_FR = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"]
MONTH_FR   = ["janv.","févr.","mars","avr.","mai","juin","juil.","août","sept.","oct.","nov.","déc."]

def send_long_message(chat_id: str, text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]; url = f"https://api.telegram.org/bot{token}/sendMessage"
    CHUNK = 3500
    for i in range(0, len(text), CHUNK):
        part = text[i:i+CHUNK]
        r = requests.post(url, data={"chat_id": chat_id, "text": part, "parse_mode":"HTML"}, timeout=30)
        if r.status_code >= 400:
            try: detail = r.json()
            except Exception: detail = {"raw": r.text}
            raise RuntimeError(f"Telegram error {r.status_code}: {detail}")

def fmt_day_header(dt):
    return f"<b>{WEEKDAY_FR[dt.weekday()]} {dt.day} {MONTH_FR[dt.month-1]}</b>"

def weekend_window(now_paris):
    wd = now_paris.weekday()  # Lun=0..Dim=6
    if wd <= 3:  # Lun..Jeu -> prochain vendredi
        days_to_fri = 4 - wd
        fri = (now_paris + timedelta(days=days_to_fri)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:        # Ven..Dim -> vendredi courant
        fri = (now_paris - timedelta(days=wd - 4)).replace(hour=0, minute=0, second=0, microsecond=0)
    sun = (fri + timedelta(days=2)).replace(hour=23, minute=59, second=59, microsecond=0)
    return fri, sun

def fetch_upcoming_soccer_dataframe():
    key = os.environ.get("ODDS_API_KEY") or os.environ.get("THEODDS_API_KEY")
    if not key: return pd.DataFrame(columns=["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"])
    regions = os.environ.get("ODDS_REGIONS", "eu,uk,us,au")
    url = "https://api.the-odds-api.com/v4/sports/upcoming/odds"
    params = {"apiKey": key, "regions": regions, "markets": "h2h,totals", "oddsFormat": "decimal", "dateFormat": "iso"}
    try:
        r = requests.get(url, params=params, timeout=25)
        if not r.ok: return pd.DataFrame(columns=["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"])
        events = r.json()
    except Exception:
        return pd.DataFrame(columns=["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"])
    rows = []
    for ev in events:
        league = ev.get("sport_key","")
        if not str(league).startswith("soccer_"):  # garde seulement soccer
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
                        try: price = float(oc.get("price"))
                        except Exception: continue
                        rows.append({"match_id": mid,"sport":"football","league":league,"teams":teams,"start_time_iso":start,"market":"h2h","outcome":out,"point": float('nan'),"book":book_key,"price":price,"book_home":home,"book_away":away})
                elif mkey == "totals":
                    for oc in m.get("outcomes", []):
                        out = str(oc.get("name","")).lower()
                        try: price = float(oc.get("price"))
                        except Exception: continue
                        pt = oc.get("point", None)
                        try: pt = float(pt)
                        except Exception: pt = float("nan")
                        rows.append({"match_id": mid,"sport":"football","league":league,"teams":teams,"start_time_iso":start,"market":"totals","outcome":out,"point":pt,"book":book_key,"price":price,"book_home":home,"book_away":away})
    cols = ["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"]
    return pd.DataFrame(rows, columns=cols)

def main():
    tzname = os.getenv("TIMEZONE","Europe/Paris"); tz = pytz.timezone(tzname)
    now_paris = pd.Timestamp.now(tz)
    strict = os.getenv("WEEKEND_STRICT","1") == "1"
    allow_fallback = os.getenv("WEEKEND_ALLOW_FALLBACK","1") == "1"
    min_ev = float(os.getenv("WEEKEND_MIN_EV","0.01"))
    max_matches = int(os.getenv("MAX_MATCHES","40"))
    leagues_limit = [s.strip() for s in os.getenv("LEAGUES_WHEN_TOO_MANY","soccer_epl,soccer_germany_bundesliga,soccer_spain_la_liga").split(",") if s.strip()]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # 1) Fetch principal
    try:
        df = fetch_soccer_odds()
    except OddsApiError as e:
        msg = f"<b>📣 Foot — Rapport week‑end</b>\n⚠️ The Odds API: {str(e)}"
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=20)
        return

    # 2) Fallback data si vide
    if df.empty and allow_fallback:
        df_fb = fetch_upcoming_soccer_dataframe()
        if not df_fb.empty:
            df = df_fb

    if df.empty:
        send_long_message(chat_id, "<b>📣 Foot — Rapport week‑end</b>\nAucune rencontre disponible (API vide).")
        return

    # 3) Local time + fenêtre
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(tz)

    if strict:
        win_start, win_end = weekend_window(now_paris)
    else:
        win_start, win_end = weekend_window(now_paris)  # peut être remplacé par une recherche dynamique si besoin
    df = df[(df["start_dt"] >= win_start) & (df["start_dt"] <= win_end)].copy()

    if df.empty:
        send_long_message(chat_id, (f"<b>📣 Foot — Rapport week‑end</b>\n"
                                    f"Aucun match entre {win_start.strftime('%a %d %b')} et {win_end.strftime('%a %d %b')}."))
        return

    # 3.5) Si trop de matchs -> restreindre aux ligues choisies
    games = df[["match_id","league","start_dt"]].drop_duplicates("match_id")
    if games.shape[0] > max_matches:
        df = df[df["league"].isin(leagues_limit)].copy()
        games = df[["match_id","league","start_dt"]].drop_duplicates("match_id")

    # 4) Marchés & consensus
    df_h2h = df[(df["market"]=="h2h") & (df["outcome"].isin(["home","draw","away"]))].copy()
    df_tot = df[(df["market"]=="totals") & (df["outcome"].isin(["over","under"]))].copy()
    if "point" in df_tot.columns: df_tot["point"] = pd.to_numeric(df_tot["point"], errors="coerce")

    cons = build_consensus(df_h2h)
    if cons.empty:
        send_long_message(chat_id, "<b>📣 Foot — Rapport week‑end</b>\nImpossible de calculer le consensus (données insuffisantes).")
        return
    cons = cons.merge(df[["match_id","start_dt"]].drop_duplicates("match_id"), on="match_id", how="left")
    cons = cons.sort_values(["start_dt","league","teams"]).reset_index(drop=True)

    # 5) Message
    title = (f"<b>📣 Foot — Week‑end</b> "
             f"({WEEKDAY_FR[win_start.weekday()]} {win_start.day} {MONTH_FR[win_start.month-1]}"
             f" → {WEEKDAY_FR[win_end.weekday()]} {win_end.day} {MONTH_FR[win_end.month-1]})\n"
             f"Seuil value: EV ≥ {min_ev:.0%}. "
             f"{'(Ligues restreintes: EPL/Bundesliga/LaLiga)' if games.shape[0] > max_matches else ''}\n— — —")
    parts = [title]
    current_day = None
    n_value = 0; n_total = 0

    for _, r in cons.iterrows():
        n_total += 1
        mid = r["match_id"]; start = r["start_dt"]
        if (current_day is None) or (start.date() != current_day.date()):
            current_day = start
            parts.append("\n" + fmt_day_header(start))

        g_h2h = df_h2h[df_h2h["match_id"]==mid]
        g_tot = df_tot[df_tot["match_id"]==mid]

        summ = summarize_match(r["home"], r["away"], r["p_home"], r["p_draw"], r["p_away"], rho=0.12, totals_lines=[2.5])
        mean_score = f"{summ['mean_home']:.2f}-{summ['mean_away']:.2f}"
        hda = f"{summ['p_home']*100:.0f}/{summ['p_draw']*100:.0f}/{summ['p_away']*100:.0f}%"
        p_over = summ['totals_over'].get(2.5, float('nan'))
        over_s = (f"{p_over*100:.0f}%" if not math.isnan(p_over) else "—")
        top3 = ", ".join([f"{i}–{j} {p*100:.1f}%" for i,j,p in summ["top_scores"]])

        # Best bet H2H/Totals
        best = None
        for side in ["home","draw","away"]:
            sub = g_h2h[g_h2h["outcome"]==side]
            price, book = best_price_and_book(sub)
            if price and price>1.0:
                p = float(summ[f"p_{side}"]); ev = p*price - 1.0
                cand = {"type":"H2H","sel":side.capitalize(),"odds":price,"p":p,"ev":ev,"book":book}
                if (best is None) or (cand["ev"]>best["ev"]): best = cand
        tot25 = g_tot[g_tot["point"].round(2)==2.50]
        if not tot25.empty and not math.isnan(p_over):
            over_odds, over_book = best_price_and_book(tot25[tot25["outcome"]=="over"])
            under_odds, under_book= best_price_and_book(tot25[tot25["outcome"]=="under"])
            ev_over = p_over*over_odds - 1.0 if over_odds and over_odds>1.0 else -9
            p_under = 1.0 - p_over; ev_under = p_under*under_odds - 1.0 if under_odds and under_odds>1.0 else -9
            if ev_over >= ev_under and (best is None or ev_over > best["ev"]):
                best = {"type":"Totals","sel":"Over 2.5","odds":over_odds,"p":p_over,"ev":ev_over,"book":over_book}
            elif ev_under > (best["ev"] if best else -9):
                best = {"type":"Totals","sel":"Under 2.5","odds":under_odds,"p":p_under,"ev":ev_under,"book":under_book}

        time_s = start.strftime("%H:%M")
        head = f"🕒 <b>{time_s}</b> — {r['teams']}"
        info = f"🧮 {mean_score}   •   H/D/A {hda}   •   Over2.5 {over_s}"
        scores = f"🔢 Scores probables: {top3}"

        if best and best["ev"] >= min_ev:
            n_value += 1
            pick = (f"✅ <b>{best['type']}</b> {best['sel']} @ <b>{best['odds']:.2f}</b>  •  "
                    f"P {best['p']*100:.1f}%  •  EV <b>{best['ev']*100:.1f}%</b>  •  {best['book']}")
        else:
            lean = ("Home" if summ['p_home']>max(summ['p_draw'], summ['p_away'])
                    else ("Away" if summ['p_away']>max(summ['p_home'], summ['p_draw']) else "Draw"))
            pick = f"⚪️ Lean {lean} (pas de value)"

        parts.append(f"{head}\n{info}\n{scores}\n{pick}")

    header = parts[0] + f"\n<b>{n_value}</b> value bets détectés sur <b>{n_total}</b> matchs analysés."
    message = header + "\n" + "\n".join(parts[1:])
    send_long_message(chat_id, message)

if __name__ == '__main__':
    main()
