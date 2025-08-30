\
# weekend_send.py — Rapport week‑end robuste (Top‑5) avec fallback intelligent
# - Mode strict: ne garde que ven 00:00 → dim 23:59:59 (Europe/Paris) du week‑end courant/prochain
# - Si aucune rencontre (API vide ou books pas encore publiés), fallback automatique :
#     1) Cherche le PROCHAIN week‑end (dans les 2 semaines) qui contient des matchs
#     2) À défaut, prend les prochains matchs dispo (≤ 7 jours) pour éviter un message vide (signalé dans l'en‑tête)
# - Affichage chrono par jour/heure, avec: score attendu, 3 scores exacts les + probables, H/D/A, Over2.5, meilleur bet
# - Paramètres via env:
#     WEEKEND_MIN_EV (def 0.01), WEEKEND_STRICT (def 1), WEEKEND_ALLOW_FALLBACK (def 1),
#     TIMEZONE (def Europe/Paris), ODDS_REGIONS (def eu,uk), ODDS_SPORTS (défini dans workflow)
import os, math, requests, pandas as pd, pytz
from datetime import timedelta
from odds_providers import fetch_soccer_odds
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
    """Retourne (début_local, fin_local) pour le week‑end courant/prochain (ven..dim).
       Lun‑Jeu -> prochain ven..dim ; Ven‑Dim -> ce ven..dim.
    """
    wd = now_paris.weekday()  # Lun=0..Dim=6
    if wd <= 3:  # Lun..Jeu -> prochain vendredi
        days_to_fri = 4 - wd
        fri = (now_paris + timedelta(days=days_to_fri)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:        # Ven..Dim -> vendredi courant
        fri = (now_paris - timedelta(days=wd - 4)).replace(hour=0, minute=0, second=0, microsecond=0)
    sun = (fri + timedelta(days=2)).replace(hour=23, minute=59, second=59, microsecond=0)
    return fri, sun

def fetch_upcoming_soccer_dataframe():
    """Fallback brut depuis /sports/upcoming/odds, filtré soccer, H2H+totals -> DataFrame même schéma."""
    key = os.environ.get("ODDS_API_KEY") or os.environ.get("THEODDS_API_KEY")
    if not key: return pd.DataFrame(columns=["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"])
    regions = os.environ.get("ODDS_REGIONS", "eu,uk,us,au")
    url = "https://api.the-odds-api.com/v4/sports/upcoming/odds"
    params = {"apiKey": key, "regions": regions, "markets": "h2h,totals", "oddsFormat": "decimal", "dateFormat": "iso"}
    try:
        r = requests.get(url, params=params, timeout=25)
        if not r.ok:
            return pd.DataFrame(columns=["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"])
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
                        except: continue
                        rows.append({"match_id": mid,"sport":"football","league":league,"teams":teams,"start_time_iso":start,"market":"h2h","outcome":out,"point": float('nan'),"book":book_key,"price":price,"book_home":home,"book_away":away})
                elif mkey == "totals":
                    for oc in m.get("outcomes", []):
                        out = str(oc.get("name","")).lower()
                        try: price = float(oc.get("price"))
                        except: continue
                        pt = oc.get("point", None)
                        try: pt = float(pt)
                        except: pt = float("nan")
                        rows.append({"match_id": mid,"sport":"football","league":league,"teams":teams,"start_time_iso":start,"market":"totals","outcome":out,"point":pt,"book":book_key,"price":price,"book_home":home,"book_away":away})
    cols = ["match_id","sport","league","teams","start_time_iso","market","outcome","point","book","price","book_home","book_away"]
    return pd.DataFrame(rows, columns=cols)

def choose_window_with_data(df_all, tz, start_from, weeks_ahead=2):
    """Essaie le week‑end courant/prochain, puis jusqu'à N week‑ends suivants pour trouver des matchs."""
    # 1) week-end courant/prochain
    win_start, win_end = weekend_window(start_from)
    mask = (df_all["start_dt"] >= win_start) & (df_all["start_dt"] <= win_end)
    if df_all[mask].shape[0] > 0:
        return win_start, win_end, "strict"
    # 2) Cherche le prochain week-end avec des matchs (1..weeks_ahead)
    for k in range(1, weeks_ahead+1):
        fri = (win_start + timedelta(days=7*k)).replace(hour=0, minute=0, second=0, microsecond=0)
        sun = (fri + timedelta(days=2)).replace(hour=23, minute=59, second=59, microsecond=0)
        mask2 = (df_all["start_dt"] >= fri) & (df_all["start_dt"] <= sun)
        if df_all[mask2].shape[0] > 0:
            return fri, sun, f"fallback_weekend+{7*k}d"
    # 3) Aucun week-end détecté -> retourne une fenêtre 7 jours dès maintenant (fallback dur)
    alt_start = start_from
    alt_end = (start_from + timedelta(days=7)).replace(hour=23, minute=59, second=59, microsecond=0)
    return alt_start, alt_end, "fallback_7days"

def main():
    tzname = os.getenv("TIMEZONE","Europe/Paris"); tz = pytz.timezone(tzname)
    now_paris = pd.Timestamp.now(tz)
    strict = os.getenv("WEEKEND_STRICT","1") == "1"
    allow_fallback = os.getenv("WEEKEND_ALLOW_FALLBACK","1") == "1"
    min_ev = float(os.getenv("WEEKEND_MIN_EV","0.01"))
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # 1) Fetch principal (Top‑5 via fetch_soccer_odds selon ODDS_SPORTS)
    df = fetch_soccer_odds()

    # 2) Fallback data si vide
    if df.empty and allow_fallback:
        df_fb = fetch_upcoming_soccer_dataframe()
        if not df_fb.empty:
            df = df_fb

    if df.empty:
        send_long_message(chat_id, "<b>📣 Foot — Rapport week‑end</b>\nAucune rencontre disponible (API vide).")
        return

    # 3) Local time
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(tz)

    # 4) Choix de la fenêtre
    if strict:
        win_start, win_end = weekend_window(now_paris)
        # si strict mais aucun match, et fallback autorisé -> cherche le prochain week-end avec data
        if allow_fallback and df[(df["start_dt"] >= win_start) & (df["start_dt"] <= win_end)].empty:
            win_start, win_end, mode = choose_window_with_data(df, tz, now_paris)
        else:
            mode = "strict"
    else:
        win_start, win_end, mode = choose_window_with_data(df, tz, now_paris)

    # 5) Filtre final de la fenêtre
    df = df[(df["start_dt"] >= win_start) & (df["start_dt"] <= win_end)].copy()
    if df.empty:
        send_long_message(chat_id, (f"<b>📣 Foot — Rapport week‑end</b>\n"
                                    f"Aucun match entre {win_start.strftime('%a %d %b')} et {win_end.strftime('%a %d %b')}."))
        return

    # 6) Marchés & consensus
    df_h2h = df[(df["market"]=="h2h") & (df["outcome"].isin(["home","draw","away"]))].copy()
    df_tot = df[(df["market"]=="totals") & (df["outcome"].isin(["over","under"]))].copy()
    if "point" in df_tot.columns: df_tot["point"] = pd.to_numeric(df_tot["point"], errors="coerce")

    cons = build_consensus(df_h2h)
    if cons.empty:
        send_long_message(chat_id, "<b>📣 Foot — Rapport week‑end</b>\nImpossible de calculer le consensus (données insuffisantes).")
        return
    cons = cons.merge(df[["match_id","start_dt"]].drop_duplicates("match_id"), on="match_id", how="left")
    cons = cons.sort_values(["start_dt","league","teams"]).reset_index(drop=True)

    # 7) Construction du message (chrono) avec top scores exacts
    title = (f"<b>📣 Foot — Période analysée</b> "
             f"({WEEKDAY_FR[win_start.weekday()]} {win_start.day} {MONTH_FR[win_start.month-1]}"
             f" → {WEEKDAY_FR[win_end.weekday()]} {win_end.day} {MONTH_FR[win_end.month-1]})\n"
             f"Mode: <code>{mode}</code> • Seuil value: EV ≥ {min_ev:.0%}.\n— — —")
    parts = [title]
    current_day = None
    n_value = 0; n_total = 0

    for _, r in cons.iterrows():
        n_total += 1
        mid = r["match_id"]; start = r["start_dt"]
        if (current_day is None) or (start.date() != current_day.date()):
            current_day = start
            parts.append("\n" + fmt_day_header(start))

        # Slices marchés
        g_h2h = df_h2h[df_h2h["match_id"]==mid]
        g_tot = df_tot[df_tot["match_id"]==mid]

        # Modèle scores
        summ = summarize_match(r["home"], r["away"], r["p_home"], r["p_draw"], r["p_away"], rho=0.12, totals_lines=[2.5])
        mean_score = f"{summ['mean_home']:.2f}-{summ['mean_away']:.2f}"
        hda = f"{summ['p_home']*100:.0f}/{summ['p_draw']*100:.0f}/{summ['p_away']*100:.0f}%"
        p_over = summ['totals_over'].get(2.5, float('nan'))
        over_s = (f"{p_over*100:.0f}%" if not math.isnan(p_over) else "—")
        top3 = ", ".join([f"{i}–{j} {p*100:.1f}%" for i,j,p in summ["top_scores"]])

        # Meilleur bet
        best = None
        # H2H
        for side in ["home","draw","away"]:
            sub = g_h2h[g_h2h["outcome"]==side]
            price, book = best_price_and_book(sub)
            if price and price>1.0:
                p = float(summ[f"p_{side}"]); ev = p*price - 1.0
                cand = {"type":"H2H","sel":side.capitalize(),"odds":price,"p":p,"ev":ev,"book":book}
                if (best is None) or (cand["ev"]>best["ev"]): best = cand
        # Totals 2.5
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

        # Texte
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
